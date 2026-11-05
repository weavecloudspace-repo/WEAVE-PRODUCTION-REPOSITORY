"""Persist closure-specific TMA rosters; fail closed when history is untrusted.

No existing scores, attempts or revision-wide snapshots are modified.
"""
from alembic import op
import sqlalchemy as sa

revision = "20261105_tma_closure_eligibility"
down_revision = "20261105_tma_attempt_provenance"
branch_labels = None
depends_on = None

CAPTURE_SQL = r"""
CREATE OR REPLACE FUNCTION public.tma_capture_closure_eligibility(
    p_tenant uuid, p_closure uuid
) RETURNS boolean
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE
    c public.tma_closure_runs%ROWTYPE;
    a public.tma_assignments%ROWTYPE;
    r public.tma_assignment_revisions%ROWTYPE;
BEGIN
    SELECT * INTO c FROM public.tma_closure_runs
    WHERE tenant_id = p_tenant AND id = p_closure FOR UPDATE;
    IF NOT FOUND THEN RETURN false; END IF;
    IF c.eligibility_captured_at IS NOT NULL THEN RETURN true; END IF;
    SELECT * INTO a FROM public.tma_assignments
    WHERE tenant_id = p_tenant AND id = c.assignment_id;
    IF NOT FOUND THEN RETURN false; END IF;
    SELECT * INTO r FROM public.tma_assignment_revisions
    WHERE tenant_id = p_tenant AND id = c.revision_id AND assignment_id = a.id;
    IF NOT FOUND OR r.published_at IS NULL OR r.invalidated_at IS NOT NULL
        OR r.eligibility_tracking_started_at IS NULL
        OR r.eligibility_tracking_started_at > c.cutoff_at
        OR c.cutoff_at > c.closed_at THEN RETURN false; END IF;
    INSERT INTO public.tma_closure_eligibility
        (tenant_id, closure_run_id, student_id, student_enrollment_id, class_id, subject_id)
    SELECT p_tenant, p_closure, e.student_id, e.id, e.class_id, cs.subject_id
    FROM public.student_enrollments e
    JOIN public.students s ON s.tenant_id = p_tenant AND s.id = e.student_id
    JOIN public.classes c ON c.tenant_id = p_tenant AND c.id = e.class_id
    JOIN public.academic_levels l ON l.tenant_id = p_tenant AND l.id = c.academic_level_id
    JOIN public.curricula cu ON cu.tenant_id = p_tenant AND cu.academic_level_id = l.id
    JOIN public.curriculum_subjects cs ON cs.tenant_id = p_tenant AND cs.curriculum_id = cu.id
    JOIN public.subjects sub ON sub.tenant_id = p_tenant AND sub.id = cs.subject_id
    JOIN public.academic_terms t ON t.tenant_id = p_tenant AND t.id = a.academic_term_id
    LEFT JOIN public.class_term_department_assignments cd
        ON cd.tenant_id = p_tenant AND cd.class_id = c.id AND cd.academic_term_id = t.id
    LEFT JOIN public.academic_level_departments ld
        ON ld.tenant_id = p_tenant AND ld.id = cd.academic_level_department_id
        AND ld.academic_level_id = l.id AND ld.is_active AND ld.archived_at IS NULL
    LEFT JOIN public.departments d
        ON d.tenant_id = p_tenant AND d.id = ld.department_id
        AND d.is_active AND d.archived_at IS NULL
    WHERE e.tenant_id = p_tenant
        AND e.academic_session_id = a.academic_session_id
        AND e.academic_level_id = a.academic_level_id
        AND e.started_on <= (c.cutoff_at AT TIME ZONE 'UTC')::date
        AND (e.ended_on IS NULL OR e.ended_on >=
            (c.cutoff_at AT TIME ZONE 'UTC')::date)
        AND e.created_at <= c.cutoff_at
        AND s.status::text = 'active' AND s.is_active AND NOT s.is_archived
        AND c.is_active AND c.archived_at IS NULL
        AND l.status::text = 'active'
        AND cs.id = a.curriculum_subject_id AND cs.is_active
        AND sub.is_active AND sub.archived_at IS NULL
        AND (NOT cs.is_elective OR cs.elective_group_id IS NULL OR EXISTS (
            SELECT 1 FROM public.student_elective_selections es
            WHERE es.tenant_id = p_tenant AND es.student_id = s.id
                AND es.curriculum_subject_id = cs.id
        ))
        AND (l.specialization_required_from_term_position IS NULL
            OR (CASE t.name::text WHEN 'first_term' THEN 1
                WHEN 'second_term' THEN 2 ELSE 3 END)
                < l.specialization_required_from_term_position
            OR (d.id IS NOT NULL AND (
                NOT EXISTS (SELECT 1 FROM public.curriculum_subject_departments sd
                    WHERE sd.tenant_id = p_tenant AND sd.curriculum_subject_id = cs.id)
                OR EXISTS (SELECT 1 FROM public.curriculum_subject_departments sd
                    WHERE sd.tenant_id = p_tenant AND sd.curriculum_subject_id = cs.id
                        AND sd.academic_level_department_id = ld.id))))
    ON CONFLICT (tenant_id, closure_run_id, student_id) DO NOTHING;
    UPDATE public.tma_closure_runs SET eligibility_captured_at = statement_timestamp()
    WHERE tenant_id = p_tenant AND id = p_closure;
    RETURN true;
END $$;
"""

PRESERVE_SQL = r"""
CREATE OR REPLACE FUNCTION public.tma_preserve_closure_eligibility()
RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE
    p_tenant uuid;
    p_assignment uuid;
    a public.tma_assignments%ROWTYPE;
    r public.tma_assignment_revisions%ROWTYPE;
    v_closed_at timestamptz;
    v_closure uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN p_tenant := OLD.tenant_id;
    ELSE p_tenant := NEW.tenant_id; END IF;
    -- Capture BEFORE enrollment or curriculum mutation and close atomically.
    -- Assignment row locks serialize automatic and manual closure.
    FOR p_assignment IN
        SELECT id FROM public.tma_assignments
        WHERE tenant_id = p_tenant AND status::text = 'active'
            AND closes_at IS NOT NULL AND closes_at <= statement_timestamp()
        ORDER BY id
    LOOP
        SELECT * INTO a FROM public.tma_assignments
        WHERE tenant_id = p_tenant AND id = p_assignment FOR UPDATE;
        IF NOT FOUND OR a.status::text <> 'active'
           OR a.closes_at IS NULL OR a.closes_at > statement_timestamp() THEN
           CONTINUE;
        END IF;
        SELECT * INTO r FROM public.tma_assignment_revisions
        WHERE tenant_id = p_tenant AND assignment_id = a.id
            AND revision_number = a.current_revision_number;
        IF NOT FOUND THEN CONTINUE; END IF;
        v_closed_at := statement_timestamp();
        v_closure := gen_random_uuid();
        INSERT INTO public.tma_closure_runs
            (id, tenant_id, assignment_id, revision_id, closed_at,
             cutoff_at, original_deadline_at, kind)
        VALUES (v_closure, p_tenant, a.id, r.id, v_closed_at,
                a.closes_at, a.closes_at, 'automatic');
        PERFORM public.tma_capture_closure_eligibility(p_tenant, v_closure);
        UPDATE public.tma_assignments SET
            status = 'closed', closed_at = v_closed_at,
            zero_grading_requested_at = v_closed_at,
            zero_grading_completed_at = NULL, zero_grading_error = NULL
        WHERE tenant_id = p_tenant AND id = a.id;
    END LOOP;
    IF TG_OP = 'DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END $$;
"""

TRACKED_TABLES = (
    "students", "student_enrollments", "student_elective_selections",
    "classes", "academic_levels", "curricula", "curriculum_subjects",
    "subjects", "curriculum_subject_departments",
    "class_term_department_assignments", "academic_level_departments",
    "departments", "academic_terms",
)

def upgrade() -> None:
    op.add_column("tma_closure_runs", sa.Column(
        "eligibility_captured_at", sa.DateTime(timezone=True), nullable=True
    ), schema="public")
    op.create_unique_constraint("uq_tma_closure_tenant_id", "tma_closure_runs",
                                ["tenant_id", "id"], schema="public")
    op.create_table(
        "tma_closure_eligibility",
        sa.Column("tenant_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("closure_run_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("student_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("student_enrollment_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("class_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_id", sa.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "closure_run_id", "student_id"),
        sa.ForeignKeyConstraint(["tenant_id", "closure_run_id"],
            ["public.tma_closure_runs.tenant_id", "public.tma_closure_runs.id"],
            name="fk_tma_closure_eligibility_run", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "student_enrollment_id", "student_id", "class_id"],
            ["public.student_enrollments.tenant_id", "public.student_enrollments.id",
             "public.student_enrollments.student_id", "public.student_enrollments.class_id"],
            name="fk_tma_closure_eligibility_enrollment",
        ),
        schema="public",
    )
    # Existing revision-wide snapshots are not automatically attributable
    # to one closure after reopens. Preserve them without assigning marks.
    op.execute(CAPTURE_SQL)
    op.execute(PRESERVE_SQL)
    for table in TRACKED_TABLES:
        op.execute(
            f"CREATE TRIGGER tma_preserve_closure_eligibility "
            f"BEFORE INSERT OR UPDATE OR DELETE ON public.{table} "
            "FOR EACH ROW EXECUTE FUNCTION public.tma_preserve_closure_eligibility()"
        )

def downgrade() -> None:
    raise RuntimeError("Closure rosters are academic history; use a forward repair.")
