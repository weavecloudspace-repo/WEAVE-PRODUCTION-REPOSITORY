"""Queue tenant TMA cache invalidation only for committed ORM changes."""

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.cache.events import CACHE_INVALIDATION_EVENTS, CacheInvalidationEvent
from app.modules.classes.models import AcademicLevel, ClassRoom, AcademicLevelDepartment
from app.modules.student_academics.models import (
    AcademicSession,
    AcademicTerm,
    AssessmentScheme,
    AssessmentComponent,
    TeacherAssignment,
)
from app.modules.student_academics.curriculum_models import (
    Curriculum,
    CurriculumSubject,
    ClassTermDepartmentAssignment,
    CurriculumSubjectDepartment,
)
from app.modules.students.models import Student, StudentEnrollment
from app.modules.subjects.models import Subject
from app.modules.teachers.models import TeacherMembership
from app.modules.tma.cache import generation_key
from app.modules.tma.models import (
    TMAAssignment,
    TMAAssignmentRevision,
    TMAQuestion,
    TMAQuestionOption,
    TMAMediaAsset,
)

DEPENDENCIES = (
    AcademicLevel,
    ClassRoom,
    AcademicLevelDepartment,
    AcademicSession,
    AcademicTerm,
    AssessmentScheme,
    AssessmentComponent,
    TeacherAssignment,
    Curriculum,
    CurriculumSubject,
    ClassTermDepartmentAssignment,
    CurriculumSubjectDepartment,
    Student,
    StudentEnrollment,
    Subject,
    TeacherMembership,
    TMAAssignment,
    TMAAssignmentRevision,
    TMAQuestion,
    TMAQuestionOption,
    TMAMediaAsset,
)


def queue_tma_invalidations(session, _context=None):
    for obj in (*session.new, *session.dirty, *session.deleted):
        if isinstance(obj, DEPENDENCIES) and obj.tenant_id is not None:
            session.info.setdefault(CACHE_INVALIDATION_EVENTS, set()).add(
                CacheInvalidationEvent(kind="key", value=generation_key(obj.tenant_id))
            )


def discard_tma_invalidations(session, previous_transaction=None):
    # A savepoint rollback must not discard invalidations from earlier writes
    # in the surrounding transaction. Extra invalidations are safe on commit.
    if previous_transaction is not None and previous_transaction.parent is not None:
        return
    bucket = session.info.get(CACHE_INVALIDATION_EVENTS, set())
    session.info[CACHE_INVALIDATION_EVENTS] = {
        event for event in bucket if not event.value.endswith(":tma:v1:generation")
    }


if not event.contains(Session, "after_flush", queue_tma_invalidations):
    event.listen(Session, "after_flush", queue_tma_invalidations)
    event.listen(Session, "after_soft_rollback", discard_tma_invalidations)
