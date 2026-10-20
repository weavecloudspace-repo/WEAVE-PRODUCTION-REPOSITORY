"""Bulk bootstrap projector for the canonical CBT v5 contract."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.cbt.academics.schemas import (
    CBTAdminSnapshot,
    CBTAcademicLevelSnapshot,
    CBTAcademicSessionSnapshot,
    CBTAcademicTermSnapshot,
    CBTArmLabelSnapshot,
    CBTAssessmentComponentSnapshot,
    CBTAssessmentSchemeSnapshot,
    CBTClassSnapshot,
    CBTClassTermDepartmentSnapshot,
    CBTCurriculumSnapshot,
    CBTCurriculumSubjectDepartmentSnapshot,
    CBTCurriculumSubjectSnapshot,
    CBTDepartmentSnapshot,
    CBTStudentEnrollmentSnapshot,
    CBTSubjectSnapshot,
    CBTTeacherAssignmentSnapshot,
    CBTTeacherSnapshot,
)
from app.modules.classes.models import (
    AcademicLevel,
    AcademicLevelDepartment,
    ArmLabel,
    ClassRoom,
    Department,
)
import app.modules.student_academics.assessment_examinability  # noqa: F401
from app.modules.student_academics.curriculum_models import (
    ClassTermDepartmentAssignment,
    Curriculum,
    CurriculumSubject,
    CurriculumSubjectDepartment,
)
from app.modules.student_academics.models import (
    AcademicSession,
    AcademicSessionStatus,
    AcademicTerm,
    AcademicTermStatus,
    AssessmentComponent,
    AssessmentScheme,
    AssessmentSchemeStatus,
    TeacherAssignment,
)
from app.modules.students.models import AcademicStatus, Student, StudentEnrollment
from app.modules.subjects.models import Subject
from app.modules.tenant_admins.models import TenantAdmin, TenantAdminStatus
from app.modules.teachers.models import (
    TeacherAccount,
    TeacherAccountStatus,
    TeacherMembership,
    TeacherMembershipStatus,
)


def _value(value: Any) -> Any:
    return getattr(value, "value", value)


def _visible(row: Any) -> bool:
    if row is None:
        return False
    status = getattr(row, "status", None)
    if status is not None and _value(status) != "active":
        return False
    return bool(getattr(row, "is_active", True) and getattr(row, "archived_at", None) is None)


def _ordered(items: list[BaseModel]) -> list[BaseModel]:
    return sorted(items, key=lambda item: str(item.id))  # type: ignore[attr-defined]


def _tenant_rows(session: Session, model: type[Any], tenant_id: uuid.UUID) -> list[Any]:
    return list(session.execute(select(model).where(model.tenant_id == tenant_id)).scalars())


def build_bootstrap_sections(
    session: Session, *, tenant_id: uuid.UUID
) -> dict[str, list[BaseModel]]:
    sections: dict[str, list[BaseModel]] = {}

    session_rows = _tenant_rows(session, AcademicSession, tenant_id)
    visible_sessions = {
        row.id: row
        for row in session_rows
        if row.is_current
        and row.status in {AcademicSessionStatus.OPEN, AcademicSessionStatus.CLOSING}
    }
    sections["sessions"] = _ordered(
        [
            CBTAcademicSessionSnapshot(
                id=row.id,
                name=row.name,
                status=_value(row.status),
                is_current=row.is_current,
            )
            for row in visible_sessions.values()
        ]
    )

    term_rows = _tenant_rows(session, AcademicTerm, tenant_id)
    visible_terms = {
        row.id: row
        for row in term_rows
        if row.academic_session_id in visible_sessions
        and row.is_current
        and row.status in {AcademicTermStatus.OPEN, AcademicTermStatus.CLOSING}
    }
    sections["terms"] = _ordered(
        [
            CBTAcademicTermSnapshot(
                id=row.id,
                academic_session_id=row.academic_session_id,
                name=_value(row.name),
                status=_value(row.status),
                is_current=row.is_current,
            )
            for row in visible_terms.values()
        ]
    )

    level_rows = _tenant_rows(session, AcademicLevel, tenant_id)
    visible_levels = {row.id: row for row in level_rows if _visible(row)}
    sections["levels"] = _ordered(
        [
            CBTAcademicLevelSnapshot(
                id=row.id,
                name=row.name,
                category=_value(row.category),
                position=row.position,
                specialization_required_from_term_position=(
                    row.specialization_required_from_term_position
                ),
            )
            for row in visible_levels.values()
        ]
    )

    arm_rows = _tenant_rows(session, ArmLabel, tenant_id)
    visible_arms = {row.id: row for row in arm_rows if _visible(row)}
    sections["arm_labels"] = _ordered(
        [CBTArmLabelSnapshot(id=row.id, label=row.label) for row in visible_arms.values()]
    )

    canonical_department_rows = _tenant_rows(session, Department, tenant_id)
    visible_canonical_departments = {
        row.id: row for row in canonical_department_rows if _visible(row)
    }
    level_department_rows = _tenant_rows(session, AcademicLevelDepartment, tenant_id)
    visible_level_departments = {
        row.id: row
        for row in level_department_rows
        if _visible(row)
        and row.academic_level_id in visible_levels
        and row.department_id in visible_canonical_departments
    }
    sections["departments"] = _ordered(
        [
            CBTDepartmentSnapshot(
                id=row.id,
                academic_level_id=row.academic_level_id,
                name=visible_canonical_departments[row.department_id].name,
            )
            for row in visible_level_departments.values()
        ]
    )

    class_rows = _tenant_rows(session, ClassRoom, tenant_id)
    visible_classes = {
        row.id: row
        for row in class_rows
        if _visible(row)
        and row.academic_level_id in visible_levels
        and row.arm_label_id in visible_arms
    }
    sections["classes"] = _ordered(
        [
            CBTClassSnapshot(
                id=row.id,
                academic_level_id=row.academic_level_id,
                arm_label_id=row.arm_label_id,
                display_name=(
                    f"{visible_levels[row.academic_level_id].name} "
                    f"{visible_arms[row.arm_label_id].label}"
                ).strip(),
                is_active=row.is_active,
            )
            for row in visible_classes.values()
        ]
    )

    ctd_rows = _tenant_rows(session, ClassTermDepartmentAssignment, tenant_id)
    visible_ctds: dict[uuid.UUID, ClassTermDepartmentAssignment] = {}
    for row in ctd_rows:
        term = visible_terms.get(row.academic_term_id)
        classroom = visible_classes.get(row.class_id)
        link = visible_level_departments.get(row.academic_level_department_id)
        if (
            term is None
            or term.status != AcademicTermStatus.OPEN
            or classroom is None
            or link is None
            or link.academic_level_id != classroom.academic_level_id
        ):
            continue
        visible_ctds[row.id] = row
    sections["class_term_departments"] = _ordered(
        [
            CBTClassTermDepartmentSnapshot(
                id=row.id,
                class_id=row.class_id,
                academic_term_id=row.academic_term_id,
                department_id=row.academic_level_department_id,
            )
            for row in visible_ctds.values()
        ]
    )

    subject_rows = _tenant_rows(session, Subject, tenant_id)
    visible_subjects = {row.id: row for row in subject_rows if _visible(row)}
    sections["subjects"] = _ordered(
        [
            CBTSubjectSnapshot(
                id=row.id,
                name=row.name,
                code=row.code,
                is_active=row.is_active,
            )
            for row in visible_subjects.values()
        ]
    )

    curriculum_rows = _tenant_rows(session, Curriculum, tenant_id)
    visible_curricula = {
        row.id: row for row in curriculum_rows if row.academic_level_id in visible_levels
    }
    sections["curricula"] = _ordered(
        [
            CBTCurriculumSnapshot(
                id=row.id,
                academic_level_id=row.academic_level_id,
            )
            for row in visible_curricula.values()
        ]
    )

    curriculum_subject_rows = _tenant_rows(session, CurriculumSubject, tenant_id)
    visible_curriculum_subjects = {
        row.id: row
        for row in curriculum_subject_rows
        if _visible(row)
        and row.curriculum_id in visible_curricula
        and row.subject_id in visible_subjects
    }
    sections["curriculum_subjects"] = _ordered(
        [
            CBTCurriculumSubjectSnapshot(
                id=row.id,
                curriculum_id=row.curriculum_id,
                subject_id=row.subject_id,
                is_elective=row.is_elective,
                is_active=row.is_active,
            )
            for row in visible_curriculum_subjects.values()
        ]
    )

    scope_rows = _tenant_rows(session, CurriculumSubjectDepartment, tenant_id)
    visible_scopes = {
        row.id: row
        for row in scope_rows
        if row.curriculum_subject_id in visible_curriculum_subjects
        and row.academic_level_department_id in visible_level_departments
        and visible_level_departments[row.academic_level_department_id].academic_level_id
        == visible_curricula[
            visible_curriculum_subjects[row.curriculum_subject_id].curriculum_id
        ].academic_level_id
    }
    sections["curriculum_subject_departments"] = _ordered(
        [
            CBTCurriculumSubjectDepartmentSnapshot(
                id=row.id,
                curriculum_subject_id=row.curriculum_subject_id,
                department_id=row.academic_level_department_id,
            )
            for row in visible_scopes.values()
        ]
    )
    scheme_rows = _tenant_rows(session, AssessmentScheme, tenant_id)
    visible_schemes = {
        row.id: row for row in scheme_rows if row.status == AssessmentSchemeStatus.ACTIVE
    }
    sections["assessment_schemes"] = _ordered(
        [
            CBTAssessmentSchemeSnapshot(
                id=row.id,
                name=row.name,
                status=_value(row.status),
            )
            for row in visible_schemes.values()
        ]
    )

    component_rows = _tenant_rows(session, AssessmentComponent, tenant_id)
    sections["assessment_components"] = _ordered(
        [
            CBTAssessmentComponentSnapshot(
                id=row.id,
                assessment_scheme_id=row.assessment_scheme_id,
                name=row.name,
                code=row.code,
                maximum_score=row.maximum_score,
                position=row.position,
                is_active=row.is_active,
                is_hybrid=getattr(row, "is_hybrid", False),
            )
            for row in component_rows
            if row.is_active and row.is_examinable and row.assessment_scheme_id in visible_schemes
        ]
    )

    admin_rows = _tenant_rows(session, TenantAdmin, tenant_id)
    sections["admins"] = _ordered(
        [
            CBTAdminSnapshot(
                id=row.id,
                email=row.email,
                status=_value(row.account_status),
            )
            for row in admin_rows
            if row.account_status == TenantAdminStatus.ACTIVE and row.is_active and row.is_verified
        ]
    )

    teacher_rows = list(
        session.execute(
            select(TeacherMembership, TeacherAccount)
            .join(TeacherAccount, TeacherAccount.id == TeacherMembership.teacher_account_id)
            .where(TeacherMembership.tenant_id == tenant_id)
        ).all()
    )
    visible_teachers: dict[uuid.UUID, tuple[TeacherMembership, TeacherAccount]] = {}
    teacher_snapshots: list[BaseModel] = []
    for membership, account in teacher_rows:
        if (
            membership.status != TeacherMembershipStatus.ACTIVE
            or account.account_status != TeacherAccountStatus.ACTIVE
            or not account.is_active
        ):
            continue
        visible_teachers[membership.id] = (membership, account)
        teacher_snapshots.append(
            CBTTeacherSnapshot(
                id=membership.id,
                teacher_account_id=membership.teacher_account_id,
                first_name=account.first_name,
                last_name=account.last_name,
                staff_id=membership.staff_id,
                status=_value(membership.status),
            )
        )
    sections["teachers"] = _ordered(teacher_snapshots)

    enrollment_rows = list(
        session.execute(
            select(StudentEnrollment, Student)
            .join(Student, Student.id == StudentEnrollment.student_id)
            .where(StudentEnrollment.tenant_id == tenant_id)
        ).all()
    )
    enrollment_snapshots: list[BaseModel] = []
    for enrollment, student in enrollment_rows:
        academic_session = visible_sessions.get(enrollment.academic_session_id)
        level = visible_levels.get(enrollment.academic_level_id)
        classroom = visible_classes.get(enrollment.class_id)
        if (
            not enrollment.is_current
            or academic_session is None
            or student.status != AcademicStatus.ACTIVE
            or student.is_archived
            or level is None
            or classroom is None
            or classroom.academic_level_id != enrollment.academic_level_id
        ):
            continue
        enrollment_snapshots.append(
            CBTStudentEnrollmentSnapshot(
                id=enrollment.id,
                student_id=student.id,
                admission_number=student.admission_number,
                first_name=student.first_name,
                last_name=student.last_name,
                academic_level_id=enrollment.academic_level_id,
                class_id=enrollment.class_id,
                academic_session_id=enrollment.academic_session_id,
                is_current=enrollment.is_current,
                student_status=_value(student.status),
            )
        )
    sections["student_enrollments"] = _ordered(enrollment_snapshots)

    assignment_snapshots: list[BaseModel] = []
    assignment_rows = _tenant_rows(session, TeacherAssignment, tenant_id)
    for assignment in assignment_rows:
        if (
            (assignment.effective_to is not None and assignment.effective_to < date.today())
            or assignment.teacher_membership_id not in visible_teachers
            or assignment.class_id not in visible_classes
            or assignment.curriculum_subject_id not in visible_curriculum_subjects
        ):
            continue
        classroom = visible_classes[assignment.class_id]
        curriculum_subject = visible_curriculum_subjects[assignment.curriculum_subject_id]
        curriculum = visible_curricula[curriculum_subject.curriculum_id]
        if curriculum.academic_level_id != classroom.academic_level_id:
            continue
        assignment_snapshots.append(
            CBTTeacherAssignmentSnapshot(
                id=assignment.id,
                teacher_membership_id=assignment.teacher_membership_id,
                class_id=assignment.class_id,
                curriculum_subject_id=assignment.curriculum_subject_id,
                effective_from=assignment.effective_from,
                effective_to=assignment.effective_to,
            )
        )
    sections["teacher_assignments"] = _ordered(assignment_snapshots)
    return sections
