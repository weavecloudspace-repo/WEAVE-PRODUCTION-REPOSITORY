"""Configuration evidence for the existing administrator setup guide."""

from sqlalchemy import func, select

from app.modules.classes.models import AcademicLevel, AcademicLevelStatus, ArmLabel, ClassRoom
from app.modules.student_academics.curriculum_models import Curriculum, CurriculumSubject
from app.modules.student_academics.models import (
    AcademicSession,
    AcademicTerm,
    AssessmentScheme,
    TeacherAssignment,
)
from app.modules.student_academics.service import StudentAcademicService
from app.modules.student_academics.specialization_workspace import specialization_workspace
from app.modules.school_calendar.models import SchoolCalendar
from app.modules.students.models import StudentEnrollment
from app.modules.teachers.models import TeacherMembership
from app.tenant_management.repository import TenantRepository


async def get_setup_readiness(db, tenant_id):
    tenant = await TenantRepository.get_by_id(db, tenant_id)

    def count(model, *conditions):
        return (
            select(func.count())
            .select_from(model)
            .where(model.tenant_id == tenant_id, *conditions)
            .scalar_subquery()
        )

    counts = (
        (
            await db.execute(
                select(
                    count(AcademicLevel, AcademicLevel.status == AcademicLevelStatus.ACTIVE).label(
                        "levels"
                    ),
                    count(
                        ArmLabel, ArmLabel.is_active.is_(True), ArmLabel.archived_at.is_(None)
                    ).label("arms"),
                    count(
                        ClassRoom, ClassRoom.is_active.is_(True), ClassRoom.archived_at.is_(None)
                    ).label("classes"),
                    count(
                        TeacherMembership,
                        TeacherMembership.status == "active",
                        TeacherMembership.ended_at.is_(None),
                    ).label("teachers"),
                    count(AssessmentScheme, AssessmentScheme.status == "active").label(
                        "assessment"
                    ),
                )
            )
        )
        .mappings()
        .one()
    )
    # Each active level must have an active subject, rather than counting a visit.
    curriculum_levels = (
        await db.execute(
            select(func.count(func.distinct(Curriculum.academic_level_id)))
            .select_from(Curriculum)
            .join(CurriculumSubject, CurriculumSubject.curriculum_id == Curriculum.id)
            .join(AcademicLevel, AcademicLevel.id == Curriculum.academic_level_id)
            .where(
                Curriculum.tenant_id == tenant_id,
                CurriculumSubject.tenant_id == tenant_id,
                AcademicLevel.tenant_id == tenant_id,
                AcademicLevel.status == AcademicLevelStatus.ACTIVE,
                CurriculumSubject.is_active.is_(True),
            )
        )
    ).scalar_one()
    sessions = list(
        (
            await db.execute(
                select(AcademicSession)
                .where(
                    AcademicSession.tenant_id == tenant_id,
                    AcademicSession.status.in_(["draft", "open"]),
                )
                .order_by(AcademicSession.start_date.asc())
            )
        ).scalars()
    )
    session = next(
        (row for row in sessions if row.status == "open"), sessions[0] if sessions else None
    )
    terms = list(
        (
            await db.execute(
                select(AcademicTerm)
                .where(
                    AcademicTerm.tenant_id == tenant_id,
                    AcademicTerm.academic_session_id == (session.id if session else None),
                    AcademicTerm.status.in_(["draft", "open"]),
                )
                .order_by(AcademicTerm.start_date.asc(), AcademicTerm.name.asc())
            )
        ).scalars()
    )
    term = next(
        (row for row in terms if row.is_current and row.status == "open"),
        terms[0] if terms else None,
    )
    completion = {key: value > 0 for key, value in counts.items()}
    completion.update(
        {
            "school_basics": bool(tenant and tenant.school_name and tenant.institution_type),
            "session": bool(session),
            "term": bool(term),
            "curriculum": counts["levels"] > 0 and curriculum_levels == counts["levels"],
            "departments": None,
            "calendar": False,
            "students": False,
            "assignments": False,
            "readiness": False,
            "start_term": bool(
                session
                and session.status == "open"
                and getattr(session, "is_current", False)
                and term
                and term.status == "open"
                and getattr(term, "is_current", False)
            ),
        }
    )
    from app.modules.subjects.models import Subject

    completion["subjects"] = bool(
        (
            await db.execute(
                select(count(Subject, Subject.is_active.is_(True), Subject.archived_at.is_(None)))
            )
        ).scalar_one()
    )
    grading = await StudentAcademicService.preview_grading_scale_readiness(db, tenant_id)
    completion["grading"] = grading.is_ready and completion.pop("assessment")
    blockers = list(grading.messages) if not grading.is_ready else []
    if term:
        workspace = await specialization_workspace(db, tenant_id, term.id)
        required = [row for row in workspace["classes"] if row["specialization_required"]]
        completion["departments"] = (
            all(row["readiness"] == "configured" for row in required) if required else None
        )
        evidence = (
            (
                await db.execute(
                    select(
                        count(
                            SchoolCalendar,
                            SchoolCalendar.academic_term_id == term.id,
                            SchoolCalendar.status == "active",
                        ).label("calendar"),
                        count(
                            StudentEnrollment,
                            StudentEnrollment.academic_session_id == session.id,
                            StudentEnrollment.is_current.is_(True),
                            StudentEnrollment.class_id.is_not(None),
                        ).label("students"),
                        count(TeacherAssignment, TeacherAssignment.is_active.is_(True)).label(
                            "assignments"
                        ),
                    )
                )
            )
            .mappings()
            .one()
        )
        completion.update({key: value > 0 for key, value in evidence.items()})
        if term.status == "draft":
            preview = await StudentAcademicService.academic_term_dependency_preview(
                db, tenant_id, term.id
            )
            blockers.extend(preview.blocker_messages)
            completion["readiness"] = preview.can_open
        else:
            # An already-open term is not operationally ready if its calendar
            # was removed or was never activated (legacy/inconsistent data).
            completion["readiness"] = completion["calendar"]
            if not completion["calendar"]:
                blockers.append("The current open term has no active calendar.")
    return {
        "completion": completion,
        "blockers": blockers,
        "academic_term_id": term.id if term else None,
        "term_name": term.name if term else None,
        "session_name": session.name if session else None,
        "academic_session_id": session.id if session else None,
        "session_status": session.status if session else None,
        "session_is_current": bool(session and getattr(session, "is_current", False)),
        "term_status": term.status if term else None,
        "term_is_current": bool(term and getattr(term, "is_current", False)),
        "session_dates_ready": bool(
            session and getattr(session, "start_date", None) and getattr(session, "end_date", None)
        ),
        "term_dates_ready": bool(
            term and getattr(term, "start_date", None) and getattr(term, "end_date", None)
        ),
        "note": "Configuration evidence is checked for the current open term, or the first draft term in the open or first draft session. Review all classes and teacher coverage before operating.",
    }
