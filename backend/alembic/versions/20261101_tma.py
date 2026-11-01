"""Create WEAVE TMA tables and tenant-safe academic references.

Revision ID: 20261101_tma
Revises: 20261020_hybrid_exam_scores
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261101_tma"
down_revision = "20261020_hybrid_exam_scores"
branch_labels = None
depends_on = None

SCHEMA = "public"

assignment_status = postgresql.ENUM(
    "draft", "active", "closed",
    name="tma_assignment_status", schema=SCHEMA, create_type=False,
)
actor_type = postgresql.ENUM(
    "teacher", "tenant_admin",
    name="tma_actor_type", schema=SCHEMA, create_type=False,
)
attempt_status = postgresql.ENUM(
    "in_progress", "submitted",
    name="tma_attempt_status", schema=SCHEMA, create_type=False,
)

# These are existing academic tables. Global UUID primary keys already make
# these combinations unique; these constraints enable PostgreSQL to enforce
# tenant-aware, composite foreign keys on the new TMA tables.
PARENT_KEYS = (
    ("academic_levels", "uq_academic_levels_tenant_id", ("tenant_id", "id")),
    ("classes", "uq_classes_tenant_id", ("tenant_id", "id")),
    ("academic_sessions", "uq_academic_sessions_tenant_id", ("tenant_id", "id")),
    (
        "academic_terms",
        "uq_academic_terms_tenant_id_session",
        ("tenant_id", "id", "academic_session_id"),
    ),
    (
        "assessment_components",
        "uq_assessment_components_tenant_id",
        ("tenant_id", "id"),
    ),
    ("students", "uq_students_tenant_id", ("tenant_id", "id")),
    (
        "student_enrollments",
        "uq_student_enrollments_tenant_id_student_class",
        ("tenant_id", "id", "student_id", "class_id"),
    ),
)


def _base_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "id", sa.UUID(), primary_key=True, unique=True, nullable=False,
        ),
        sa.Column(
            "tenant_id", sa.UUID(),
            sa.ForeignKey("public.tenants.id"), nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
    ]


def _create(name: str, *columns_and_constraints: object) -> None:
    op.create_table(
        name,
        *_base_columns(),
        *columns_and_constraints,
        schema=SCHEMA,
    )


def upgrade() -> None:
    for table, name, columns in PARENT_KEYS:
        op.create_unique_constraint(name, table, list(columns), schema=SCHEMA)

    bind = op.get_bind()
    for enum_type in (assignment_status, actor_type, attempt_status):
        enum_type.create(bind, checkfirst=True)

    _create(
        "tma_assignments",
        sa.Column("academic_level_id", sa.UUID(), nullable=False),
        sa.Column("curriculum_subject_id", sa.UUID(), nullable=False),
        sa.Column("academic_session_id", sa.UUID(), nullable=False),
        sa.Column("academic_term_id", sa.UUID(), nullable=False),
        sa.Column("assessment_component_id", sa.UUID(), nullable=False),
        sa.Column(
            "status", assignment_status,
            server_default="draft", nullable=False,
        ),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "current_revision_number", sa.Integer(),
            server_default="1", nullable=False,
        ),
        sa.Column("created_by_actor_type", actor_type, nullable=False),
        sa.Column("created_by_actor_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "academic_level_id"],
            ["public.academic_levels.tenant_id", "public.academic_levels.id"],
            name="fk_tma_assignment_tenant_level", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "curriculum_subject_id"],
            ["public.curriculum_subjects.tenant_id", "public.curriculum_subjects.id"],
            name="fk_tma_assignment_tenant_subject", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "academic_session_id"],
            ["public.academic_sessions.tenant_id", "public.academic_sessions.id"],
            name="fk_tma_assignment_tenant_session", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "academic_term_id", "academic_session_id"],
            [
                "public.academic_terms.tenant_id",
                "public.academic_terms.id",
                "public.academic_terms.academic_session_id",
            ],
            name="fk_tma_assignment_term_session", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "assessment_component_id"],
            [
                "public.assessment_components.tenant_id",
                "public.assessment_components.id",
            ],
            name="fk_tma_assignment_tenant_component", ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id", "id",
            name="uq_tma_assignments_tenant_id",
        ),
        sa.UniqueConstraint(
            "tenant_id", "academic_level_id", "curriculum_subject_id",
            "academic_session_id", "academic_term_id", "assessment_component_id",
            name="uq_tma_assignment_component_scope",
        ),
        sa.CheckConstraint(
            "current_revision_number >= 1",
            name="ck_tma_assignment_revision_positive",
        ),
    )
    op.create_index(
        "ix_tma_assignments_tenant_term_status",
        "tma_assignments", ["tenant_id", "academic_term_id", "status"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_tma_assignments_tenant_level_subject",
        "tma_assignments",
        ["tenant_id", "academic_level_id", "curriculum_subject_id"],
        schema=SCHEMA,
    )

    _create(
        "tma_assignment_revisions",
        sa.Column("assignment_id", sa.UUID(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_by_actor_type", actor_type, nullable=True),
        sa.Column("invalidated_by_actor_id", sa.UUID(), nullable=True),
        sa.Column("invalidation_reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id", "assignment_id"],
            ["public.tma_assignments.tenant_id", "public.tma_assignments.id"],
            name="fk_tma_revisions_tenant_assignment", ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id", "assignment_id", "revision_number",
            name="uq_tma_revisions_assignment_number",
        ),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_tma_revisions_tenant_id",
        ),
        sa.UniqueConstraint(
            "tenant_id", "id", "assignment_id",
            name="uq_tma_revisions_tenant_id_assignment",
        ),
        sa.CheckConstraint(
            "revision_number >= 1", name="ck_tma_revisions_number_positive",
        ),
        sa.CheckConstraint(
            """
            (invalidated_at IS NULL
             AND invalidated_by_actor_type IS NULL
             AND invalidated_by_actor_id IS NULL)
            OR
            (invalidated_at IS NOT NULL
             AND invalidated_by_actor_type IS NOT NULL
             AND invalidated_by_actor_id IS NOT NULL)
            """,
            name="ck_tma_revisions_invalidation_metadata",
        ),
        sa.CheckConstraint(
            """
            invalidated_at IS NULL OR (
                published_at IS NOT NULL AND invalidated_at >= published_at
            )
            """,
            name="ck_tma_revisions_invalidation_chronology",
        ),
    )

    _create(
        "tma_media_assets",
        sa.Column("assignment_id", sa.UUID(), nullable=False),
        sa.Column("object_key", sa.String(length=1024), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id", "assignment_id"],
            ["public.tma_assignments.tenant_id", "public.tma_assignments.id"],
            name="fk_tma_media_assets_tenant_assignment", ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id", "object_key",
            name="uq_tma_media_assets_tenant_object_key",
        ),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_tma_media_assets_tenant_id",
        ),
        sa.UniqueConstraint(
            "tenant_id", "assignment_id", "id",
            name="uq_tma_media_tenant_assignment_id",
        ),
        sa.CheckConstraint(
            "size_bytes > 0", name="ck_tma_media_assets_size_positive",
        ),
        sa.CheckConstraint(
            "LENGTH(BTRIM(object_key)) > 0",
            name="ck_tma_media_assets_object_key_required",
        ),
        sa.CheckConstraint(
            "LENGTH(BTRIM(content_type)) > 0",
            name="ck_tma_media_assets_content_type_required",
        ),
        sa.CheckConstraint(
            "checksum_sha256 IS NULL OR checksum_sha256 ~ '^[0-9a-fA-F]{64}$'",
            name="ck_tma_media_assets_checksum_sha256",
        ),
    )
    op.create_index(
        "ix_tma_media_assets_tenant_assignment",
        "tma_media_assets", ["tenant_id", "assignment_id"],
        schema=SCHEMA,
    )

    _create(
        "tma_questions",
        sa.Column("revision_id", sa.UUID(), nullable=False),
        sa.Column("assignment_id", sa.UUID(), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=True),
        sa.Column("image_asset_id", sa.UUID(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "version", sa.Integer(), server_default="1", nullable=False,
        ),
        sa.Column("author_actor_type", actor_type, nullable=False),
        sa.Column("author_actor_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "revision_id", "assignment_id"],
            [
                "public.tma_assignment_revisions.tenant_id",
                "public.tma_assignment_revisions.id",
                "public.tma_assignment_revisions.assignment_id",
            ],
            name="fk_tma_questions_tenant_revision", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "assignment_id", "image_asset_id"],
            [
                "public.tma_media_assets.tenant_id",
                "public.tma_media_assets.assignment_id",
                "public.tma_media_assets.id",
            ],
            name="fk_tma_questions_tenant_media", ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id", "revision_id", "position",
            name="uq_tma_questions_revision_position",
        ),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_tma_questions_tenant_id",
        ),
        sa.UniqueConstraint(
            "tenant_id", "id", "revision_id",
            name="uq_tma_questions_tenant_id_revision",
        ),
        sa.UniqueConstraint(
            "tenant_id", "id", "assignment_id",
            name="uq_tma_questions_tenant_id_assignment",
        ),
        sa.CheckConstraint(
            """
            (question_text IS NOT NULL AND LENGTH(BTRIM(question_text)) > 0)
            OR image_asset_id IS NOT NULL
            """,
            name="ck_tma_questions_content_required",
        ),
        sa.CheckConstraint(
            "position >= 1", name="ck_tma_questions_position_positive",
        ),
        sa.CheckConstraint(
            "version >= 1", name="ck_tma_questions_version_positive",
        ),
    )

    _create(
        "tma_question_options",
        sa.Column("question_id", sa.UUID(), nullable=False),
        sa.Column("assignment_id", sa.UUID(), nullable=False),
        sa.Column("option_text", sa.Text(), nullable=True),
        sa.Column("image_asset_id", sa.UUID(), nullable=True),
        sa.Column(
            "is_correct", sa.Boolean(), server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "question_id", "assignment_id"],
            [
                "public.tma_questions.tenant_id",
                "public.tma_questions.id",
                "public.tma_questions.assignment_id",
            ],
            name="fk_tma_question_options_tenant_question", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "assignment_id", "image_asset_id"],
            [
                "public.tma_media_assets.tenant_id",
                "public.tma_media_assets.assignment_id",
                "public.tma_media_assets.id",
            ],
            name="fk_tma_question_options_tenant_media", ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id", "question_id", "position",
            name="uq_tma_question_options_position",
        ),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_tma_question_options_tenant_id",
        ),
        sa.UniqueConstraint(
            "tenant_id", "question_id", "id",
            name="uq_tma_question_options_tenant_question_id",
        ),
        sa.CheckConstraint(
            """
            (option_text IS NOT NULL AND LENGTH(BTRIM(option_text)) > 0)
            OR image_asset_id IS NOT NULL
            """,
            name="ck_tma_question_options_content_required",
        ),
        sa.CheckConstraint(
            "position >= 1", name="ck_tma_question_options_position_positive",
        ),
    )
    op.create_index(
        "uq_tma_question_options_one_correct",
        "tma_question_options", ["tenant_id", "question_id"],
        unique=True, schema=SCHEMA,
        postgresql_where=sa.text("is_correct = true"),
    )

    _create(
        "tma_participants",
        sa.Column("revision_id", sa.UUID(), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("student_enrollment_id", sa.UUID(), nullable=False),
        sa.Column("class_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "revision_id"],
            [
                "public.tma_assignment_revisions.tenant_id",
                "public.tma_assignment_revisions.id",
            ],
            name="fk_tma_participants_tenant_revision", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "student_id"],
            ["public.students.tenant_id", "public.students.id"],
            name="fk_tma_participants_tenant_student", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "student_enrollment_id", "student_id", "class_id"],
            [
                "public.student_enrollments.tenant_id",
                "public.student_enrollments.id",
                "public.student_enrollments.student_id",
                "public.student_enrollments.class_id",
            ],
            name="fk_tma_participants_student_enrollment", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "class_id"],
            ["public.classes.tenant_id", "public.classes.id"],
            name="fk_tma_participants_tenant_class", ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id", "revision_id", "student_id",
            name="uq_tma_participants_revision_student",
        ),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_tma_participants_tenant_id",
        ),
        sa.UniqueConstraint(
            "tenant_id", "id", "revision_id",
            name="uq_tma_participants_tenant_id_revision",
        ),
    )
    op.create_index(
        "ix_tma_participants_tenant_student",
        "tma_participants", ["tenant_id", "student_id"],
        schema=SCHEMA,
    )

    _create(
        "tma_attempts",
        sa.Column("participant_id", sa.UUID(), nullable=False),
        sa.Column("revision_id", sa.UUID(), nullable=False),
        sa.Column(
            "status", attempt_status, server_default="in_progress",
            nullable=False,
        ),
        sa.Column(
            "started_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("correct_answers", sa.Integer(), nullable=True),
        sa.Column("total_questions", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id", "participant_id", "revision_id"],
            [
                "public.tma_participants.tenant_id",
                "public.tma_participants.id",
                "public.tma_participants.revision_id",
            ],
            name="fk_tma_attempts_tenant_participant", ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id", "participant_id",
            name="uq_tma_attempts_tenant_participant",
        ),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_tma_attempts_tenant_id",
        ),
        sa.UniqueConstraint(
            "tenant_id", "id", "revision_id",
            name="uq_tma_attempts_tenant_id_revision",
        ),
        sa.CheckConstraint(
            """
            (status = 'in_progress'
                AND submitted_at IS NULL
                AND correct_answers IS NULL
                AND total_questions IS NULL)
            OR
            (status = 'submitted'
                AND submitted_at IS NOT NULL
                AND correct_answers IS NOT NULL
                AND total_questions IS NOT NULL
                AND total_questions > 0
                AND correct_answers >= 0
                AND correct_answers <= total_questions)
            """,
            name="ck_tma_attempts_submission_consistency",
        ),
        sa.CheckConstraint(
            "submitted_at IS NULL OR submitted_at >= started_at",
            name="ck_tma_attempts_submission_chronology",
        ),
    )
    op.create_index(
        "ix_tma_attempts_tenant_status",
        "tma_attempts", ["tenant_id", "status"], schema=SCHEMA,
    )

    _create(
        "tma_answers",
        sa.Column("attempt_id", sa.UUID(), nullable=False),
        sa.Column("revision_id", sa.UUID(), nullable=False),
        sa.Column("question_id", sa.UUID(), nullable=False),
        sa.Column("selected_option_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "attempt_id", "revision_id"],
            [
                "public.tma_attempts.tenant_id",
                "public.tma_attempts.id",
                "public.tma_attempts.revision_id",
            ],
            name="fk_tma_answers_tenant_attempt", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "question_id", "revision_id"],
            [
                "public.tma_questions.tenant_id",
                "public.tma_questions.id",
                "public.tma_questions.revision_id",
            ],
            name="fk_tma_answers_tenant_question", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "question_id", "selected_option_id"],
            [
                "public.tma_question_options.tenant_id",
                "public.tma_question_options.question_id",
                "public.tma_question_options.id",
            ],
            name="fk_tma_answers_tenant_question_option", ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id", "attempt_id", "question_id",
            name="uq_tma_answers_attempt_question",
        ),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_tma_answers_tenant_id",
        ),
    )


def downgrade() -> None:
    # Drop children before parents so all FK dependencies are satisfied.
    op.drop_table("tma_answers", schema=SCHEMA)
    op.drop_index("ix_tma_attempts_tenant_status", table_name="tma_attempts", schema=SCHEMA)
    op.drop_table("tma_attempts", schema=SCHEMA)
    op.drop_index(
        "ix_tma_participants_tenant_student",
        table_name="tma_participants", schema=SCHEMA,
    )
    op.drop_table("tma_participants", schema=SCHEMA)
    op.drop_index(
        "uq_tma_question_options_one_correct",
        table_name="tma_question_options", schema=SCHEMA,
    )
    op.drop_table("tma_question_options", schema=SCHEMA)
    op.drop_table("tma_questions", schema=SCHEMA)
    op.drop_index(
        "ix_tma_media_assets_tenant_assignment",
        table_name="tma_media_assets", schema=SCHEMA,
    )
    op.drop_table("tma_media_assets", schema=SCHEMA)
    op.drop_table("tma_assignment_revisions", schema=SCHEMA)
    op.drop_index(
        "ix_tma_assignments_tenant_level_subject",
        table_name="tma_assignments", schema=SCHEMA,
    )
    op.drop_index(
        "ix_tma_assignments_tenant_term_status",
        table_name="tma_assignments", schema=SCHEMA,
    )
    op.drop_table("tma_assignments", schema=SCHEMA)

    for enum_type in (attempt_status, actor_type, assignment_status):
        enum_type.drop(op.get_bind(), checkfirst=True)

    for table, name, _ in reversed(PARENT_KEYS):
        op.drop_constraint(name, table, type_="unique", schema=SCHEMA)
