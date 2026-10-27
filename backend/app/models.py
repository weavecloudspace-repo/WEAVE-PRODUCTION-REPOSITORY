"""Central registry for SQLAlchemy ORM models and canonical pre-launch contracts."""

import app.tenant_management.models
import app.modules.communications.models
import app.modules.attendance.models
import app.modules.auth.models
import app.modules.auth_identity.models
import app.modules.bulk_imports.models
import app.modules.cbt.models
import app.modules.cbt.auth.models
import app.modules.cbt.ai.quota.models
import app.modules.cbt.ai.idempotency.models
import app.modules.cbt.sync.models
import app.modules.classes.models
import app.modules.email_outbox.models
import app.modules.finance.models
import app.modules.legal_compliance.models
import app.modules.media.models
import app.modules.parents.models
import app.modules.report_cards.models
import app.modules.report_cards.comment_models
import app.modules.results.models
import app.modules.school_calendar.models
import app.modules.students.models
import app.modules.student_academics.models
import app.modules.student_academics.curriculum_models
import app.modules.subjects.models
import app.modules.subscriptions.models
import app.modules.superadmin.models
import app.modules.teachers.models
import app.modules.tenant_admins.models
import app.modules.tenant_branding.models
import app.modules.user_guides.models

# Install canonical academic-level dependency accounting before request services execute.
import app.modules.classes.academic_level_dependency_contract  # noqa: E402,F401

# Extend the canonical assessment-component mapper with the examinability flag
# before projectors/services inspect SQLAlchemy metadata.
import app.modules.student_academics.assessment_examinability  # noqa: E402,F401

import app.modules.bulk_imports.model_events  # noqa: E402,F401
import app.modules.cbt.sync.model_events  # noqa: E402,F401
import app.modules.report_cards.model_events  # noqa: E402,F401
import app.modules.student_academics.elective_integrity  # noqa: E402,F401
import app.modules.student_academics.grading_scale_integrity  # noqa: E402,F401
import app.modules.cbt.results.models
import app.modules.cbt.results.rollback_models
