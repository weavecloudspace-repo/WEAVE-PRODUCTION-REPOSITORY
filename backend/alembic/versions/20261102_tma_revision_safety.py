"""Isolate revision grading and retain deadline eligibility before later changes.

Existing past deadlines cannot be reconstructed: tracking starts at migration time.
Deploy with writers stopped; resume only after upgrade completes. Downgrade refuses
if revision-specific failures would collide and preserves eligibility audit tables.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "20261102_tma_revision_safety"
down_revision = "20261102_tma_zero_reconcile"
branch_labels = None
depends_on = None

TRACKED_TABLES = (
    "students",
    "student_enrollments",
    "student_elective_selections",
    "classes",
    "academic_levels",
    "curricula",
    "curriculum_subjects",
    "subjects",
    "curriculum_subject_departments",
    "class_term_department_assignments",
    "academic_level_departments",
    "departments",
    "academic_terms",
)


def upgrade():
    for column in (
        "zero_grading_requested_at",
        "zero_grading_completed_at",
        "eligibility_tracking_started_at",
        "eligibility_captured_at",
    ):
        op.add_column(
            "tma_assignment_revisions",
            sa.Column(column, sa.DateTime(timezone=True)),
            schema="public",
        )
    op.add_column(
        "tma_assignment_revisions", sa.Column("zero_grading_error", sa.Text()), schema="public"
    )
    op.execute("""
        UPDATE public.tma_assignment_revisions r
        SET eligibility_tracking_started_at = statement_timestamp(),
            zero_grading_requested_at = a.zero_grading_requested_at,
            zero_grading_completed_at = a.zero_grading_completed_at,
            zero_grading_error = a.zero_grading_error
        FROM public.tma_assignments a
        WHERE r.tenant_id = a.tenant_id AND r.assignment_id = a.id
          AND r.revision_number = a.current_revision_number
    """)
    op.add_column(
        "tma_zero_grading_failures", sa.Column("revision_number", sa.Integer()), schema="public"
    )
    # last_failed_at is the only trustworthy recorded association. Fail migration
    # rather than invent provenance when no revision existed at that instant.
    op.execute("""
        UPDATE public.tma_zero_grading_failures f SET revision_number = (
            SELECT r.revision_number FROM public.tma_assignment_revisions r
            WHERE r.tenant_id = f.tenant_id AND r.assignment_id = f.assignment_id
              AND r.created_at <= f.last_failed_at
            ORDER BY r.revision_number DESC LIMIT 1
        )
    """)
    op.alter_column("tma_zero_grading_failures", "revision_number", nullable=False, schema="public")
    op.create_foreign_key(
        "fk_tma_zero_failure_revision",
        "tma_zero_grading_failures",
        "tma_assignment_revisions",
        ["tenant_id", "assignment_id", "revision_number"],
        ["tenant_id", "assignment_id", "revision_number"],
        source_schema="public",
        referent_schema="public",
    )
    op.drop_constraint(
        "uq_tma_zero_failure_tenant_assignment_student",
        "tma_zero_grading_failures",
        schema="public",
    )
    op.create_unique_constraint(
        "uq_tma_zero_failure_revision_student",
        "tma_zero_grading_failures",
        ["tenant_id", "assignment_id", "revision_number", "student_id"],
        schema="public",
    )
    op.add_column(
        "tma_assignments",
        sa.Column("zero_grading_last_processed_at", sa.DateTime(timezone=True)),
        schema="public",
    )
    op.create_table(
        "tma_deadline_eligibility",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("revision_id", UUID(as_uuid=True), nullable=False),
        sa.Column("student_id", UUID(as_uuid=True), nullable=False),
        sa.Column("student_enrollment_id", UUID(as_uuid=True), nullable=False),
        sa.Column("class_id", UUID(as_uuid=True), nullable=False),
        sa.Column("subject_id", UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "revision_id", "student_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "revision_id"],
            ["public.tma_assignment_revisions.tenant_id", "public.tma_assignment_revisions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "student_enrollment_id", "student_id", "class_id"],
            [
                "public.student_enrollments.tenant_id",
                "public.student_enrollments.id",
                "public.student_enrollments.student_id",
                "public.student_enrollments.class_id",
            ],
        ),
        schema="public",
    )
    op.execute(CAPTURE_SQL)
    op.execute(TRIGGER_SQL)
    for table in TRACKED_TABLES:
        op.execute(
            f"CREATE TRIGGER tma_preserve_deadline BEFORE INSERT OR UPDATE OR DELETE ON public.{table} "
            "FOR EACH ROW EXECUTE FUNCTION public.tma_preserve_deadline()"
        )


CAPTURE_SQL = r"""
CREATE FUNCTION public.tma_capture_deadline(p_tenant uuid, p_assignment uuid) RETURNS boolean
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE a public.tma_assignments%ROWTYPE;
        r public.tma_assignment_revisions%ROWTYPE;
BEGIN
    SELECT * INTO a FROM public.tma_assignments
    WHERE tenant_id = p_tenant AND id = p_assignment FOR UPDATE;
    IF NOT FOUND OR a.closes_at IS NULL OR a.closes_at > statement_timestamp()
        OR a.status::text NOT IN ('active', 'closed') THEN RETURN false; END IF;
    SELECT * INTO r FROM public.tma_assignment_revisions
    WHERE tenant_id = p_tenant AND assignment_id = a.id AND revision_number = a.current_revision_number;
    IF r.eligibility_captured_at IS NOT NULL THEN RETURN true; END IF;
    IF r.published_at IS NULL OR r.invalidated_at IS NOT NULL
        OR r.eligibility_tracking_started_at IS NULL
        OR r.eligibility_tracking_started_at > a.closes_at THEN RETURN false; END IF;
    INSERT INTO public.tma_deadline_eligibility
        (tenant_id, revision_id, student_id, student_enrollment_id, class_id, subject_id)
    SELECT p_tenant, r.id, s.id, e.id, c.id, cs.subject_id
    FROM public.student_enrollments e
    JOIN public.students s ON s.tenant_id = p_tenant AND s.id = e.student_id
    JOIN public.classes c ON c.tenant_id = p_tenant AND c.id = e.class_id
    JOIN public.academic_levels l ON l.tenant_id = p_tenant AND l.id = c.academic_level_id
    JOIN public.curricula cu ON cu.tenant_id = p_tenant AND cu.academic_level_id = l.id
    JOIN public.curriculum_subjects cs ON cs.tenant_id = p_tenant AND cs.curriculum_id = cu.id
    JOIN public.subjects sub ON sub.tenant_id = p_tenant AND sub.id = cs.subject_id
    JOIN public.academic_terms t ON t.tenant_id = p_tenant AND t.id = a.academic_term_id
    LEFT JOIN public.class_term_department_assignments cd ON cd.tenant_id = p_tenant
        AND cd.class_id = c.id AND cd.academic_term_id = t.id
    LEFT JOIN public.academic_level_departments ld ON ld.tenant_id = p_tenant
        AND ld.id = cd.academic_level_department_id AND ld.academic_level_id = l.id
        AND ld.is_active AND ld.archived_at IS NULL
    LEFT JOIN public.departments d ON d.tenant_id = p_tenant AND d.id = ld.department_id
        AND d.is_active AND d.archived_at IS NULL
    WHERE e.tenant_id = p_tenant AND e.academic_session_id = a.academic_session_id
        AND e.academic_level_id = a.academic_level_id
        AND e.started_on <= (a.closes_at AT TIME ZONE 'UTC')::date
        AND (e.ended_on IS NULL OR e.ended_on >= (a.closes_at AT TIME ZONE 'UTC')::date)
        AND e.created_at <= a.closes_at
        AND s.status::text = 'active' AND s.is_active AND NOT s.is_archived
        AND c.is_active AND c.archived_at IS NULL AND l.status::text = 'active'
        AND cs.id = a.curriculum_subject_id AND cs.is_active
        AND sub.is_active AND sub.archived_at IS NULL
        AND (NOT cs.is_elective OR cs.elective_group_id IS NULL OR EXISTS (
            SELECT 1 FROM public.student_elective_selections es
            WHERE es.tenant_id = p_tenant AND es.student_id = s.id AND es.curriculum_subject_id = cs.id))
        AND (l.specialization_required_from_term_position IS NULL
             OR (CASE t.name::text WHEN 'first_term' THEN 1 WHEN 'second_term' THEN 2 ELSE 3 END)
                < l.specialization_required_from_term_position
             OR (d.id IS NOT NULL AND (
                 NOT EXISTS (SELECT 1 FROM public.curriculum_subject_departments sd
                     WHERE sd.tenant_id = p_tenant AND sd.curriculum_subject_id = cs.id)
                 OR EXISTS (SELECT 1 FROM public.curriculum_subject_departments sd
                     WHERE sd.tenant_id = p_tenant AND sd.curriculum_subject_id = cs.id
                         AND sd.academic_level_department_id = ld.id))))
    ON CONFLICT DO NOTHING;
    UPDATE public.tma_assignment_revisions SET eligibility_captured_at = statement_timestamp()
    WHERE tenant_id = p_tenant AND id = r.id;
    RETURN true;
END $$;
"""

TRIGGER_SQL = r"""
CREATE FUNCTION public.tma_preserve_deadline() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE p_tenant uuid; assignment_id uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN p_tenant := OLD.tenant_id; ELSE p_tenant := NEW.tenant_id; END IF;
    FOR assignment_id IN
        SELECT a.id FROM public.tma_assignments a
        JOIN public.tma_assignment_revisions r ON r.tenant_id = a.tenant_id
            AND r.assignment_id = a.id AND r.revision_number = a.current_revision_number
        WHERE a.tenant_id = p_tenant AND a.status::text IN ('active', 'closed')
            AND a.closes_at <= statement_timestamp() AND r.eligibility_captured_at IS NULL
            AND r.eligibility_tracking_started_at <= a.closes_at
        ORDER BY a.id
    LOOP
        PERFORM public.tma_capture_deadline(p_tenant, assignment_id);
    END LOOP;
    IF TG_OP = 'DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END $$;
"""


def downgrade():
    # Audit history is intentionally retained. Rolling application code back to
    # assignment-wide reconciliation is unsafe once more than one revision exists.
    raise RuntimeError(
        "TMA revision safety requires a forward repair; audit data must be retained."
    )
