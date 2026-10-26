import uuid

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.core.cache.manager import CacheManager
from app.modules.communications.enums import CommunicationActorType, NotificationStatus
from app.modules.classes.models import AcademicLevel, ArmLabel, ClassRoom
from app.modules.metrics.cache import (
    parent_dashboard_cache_key,
    student_dashboard_cache_key,
    superadmin_dashboard_cache_key,
    teacher_dashboard_cache_key,
    tenant_admin_dashboard_cache_key,
)
from app.modules.metrics.repository import MetricsRepository
from app.modules.metrics.schemas import ChartPoint, DashboardMetricsResponse
from app.modules.parents.models import Parent
from app.modules.report_cards.models import ReportCard
from app.modules.students.models import Student, StudentParentLink
from app.modules.student_academics.models import (
    AcademicResultStatus,
    AcademicSession,
    AcademicTerm,
    StudentSubjectResult,
)
from app.modules.subjects.models import Subject
from app.modules.teachers.models import Teacher, TeacherAccount
from app.tenant_management.models import SubscriptionPlan


class MetricsService:
    """Business logic for dashboard metrics and cache orchestration."""

    @staticmethod
    def _enum_label(value: object) -> str:
        return value.value if hasattr(value, "value") else str(value)

    @staticmethod
    def _label(value: object, fallback: str = "Unknown") -> str:
        if value is None:
            return fallback
        return MetricsService._enum_label(value)

    @staticmethod
    def _percent(numerator: int | float, denominator: int | float) -> int:
        if not denominator:
            return 0
        return round((float(numerator) / float(denominator)) * 100)

    @staticmethod
    def _status_count_map(rows) -> dict[str, int]:
        return {MetricsService._enum_label(row.label): int(row.value or 0) for row in rows}

    @staticmethod
    async def _cached_dashboard(key: str, fetcher) -> DashboardMetricsResponse:
        dashboard = await CacheManager.get_or_set(
            key=key,
            fetcher=fetcher,
            ttl=settings.CACHE_DEFAULT_TTL_SECONDS,
        )
        return DashboardMetricsResponse.model_validate(dashboard)

    @staticmethod
    async def _report_card_status_chart(db: AsyncSession, tenant_id: uuid.UUID) -> list[ChartPoint]:
        rows = (
            await db.execute(
                select(ReportCard.status, func.count(ReportCard.id).label("value"))
                .where(ReportCard.tenant_id == tenant_id)
                .group_by(ReportCard.status)
            )
        ).all()
        return [
            ChartPoint(label=MetricsService._enum_label(row[0]), value=int(row.value or 0))
            for row in rows
        ]

    @staticmethod
    async def _performance_trend(db: AsyncSession, tenant_id: uuid.UUID) -> list[ChartPoint]:
        report_card_rows = (
            await db.execute(
                select(
                    AcademicSession.name.label("session_name"),
                    AcademicTerm.name.label("term_name"),
                    func.avg(ReportCard.average_score).label("average"),
                )
                .join(AcademicSession, AcademicSession.id == ReportCard.academic_session_id)
                .join(AcademicTerm, AcademicTerm.id == ReportCard.academic_term_id)
                .where(ReportCard.tenant_id == tenant_id)
                .group_by(AcademicSession.name, AcademicTerm.name)
                .order_by(AcademicSession.name.asc(), AcademicTerm.name.asc())
            )
        ).all()
        if report_card_rows:
            return [
                ChartPoint(
                    label=f"{row.session_name} / {MetricsService._enum_label(row.term_name).replace('_', ' ')}",
                    value=round(float(row.average or 0), 2),
                )
                for row in report_card_rows
            ]

        result_rows = (
            await db.execute(
                select(
                    AcademicSession.name.label("session_name"),
                    AcademicTerm.name.label("term_name"),
                    func.avg(StudentSubjectResult.total_score).label("average"),
                )
                .join(
                    AcademicSession,
                    AcademicSession.id == StudentSubjectResult.academic_session_id,
                )
                .join(AcademicTerm, AcademicTerm.id == StudentSubjectResult.academic_term_id)
                .where(
                    StudentSubjectResult.tenant_id == tenant_id,
                    StudentSubjectResult.status == AcademicResultStatus.SUBMITTED,
                )
                .group_by(AcademicSession.name, AcademicTerm.name)
                .order_by(AcademicSession.name.asc(), AcademicTerm.name.asc())
            )
        ).all()
        return [
            ChartPoint(
                label=f"{row.session_name} / {MetricsService._enum_label(row.term_name).replace('_', ' ')}",
                value=round(float(row.average or 0), 2),
            )
            for row in result_rows
        ]

    @staticmethod
    async def _class_performance(db: AsyncSession, tenant_id: uuid.UUID) -> list[ChartPoint]:
        rows = (
            await db.execute(
                select(
                    AcademicLevel.name,
                    ArmLabel.label.label("arm"),
                    func.avg(StudentSubjectResult.total_score).label("average"),
                )
                .join(ClassRoom, ClassRoom.id == StudentSubjectResult.class_id)
                .join(AcademicLevel, AcademicLevel.id == ClassRoom.academic_level_id)
                .outerjoin(ArmLabel, ArmLabel.id == ClassRoom.arm_label_id)
                .where(
                    StudentSubjectResult.tenant_id == tenant_id,
                    StudentSubjectResult.status == AcademicResultStatus.SUBMITTED,
                )
                .group_by(AcademicLevel.name, ArmLabel.label)
                .order_by(AcademicLevel.name.asc(), ArmLabel.label.asc())
            )
        ).all()
        return [
            ChartPoint(
                label=f"{row.name} {row.arm or ''}".strip(),
                value=round(float(row.average or 0), 2),
            )
            for row in rows
        ]

    @staticmethod
    async def _teacher_submission_progress(
        db: AsyncSession, tenant_id: uuid.UUID
    ) -> list[ChartPoint]:
        rows = (
            await db.execute(
                select(
                    TeacherAccount.first_name,
                    TeacherAccount.last_name,
                    Teacher.staff_id,
                    func.count(StudentSubjectResult.id).label("total_rows"),
                    func.count(StudentSubjectResult.id)
                    .filter(StudentSubjectResult.status == AcademicResultStatus.SUBMITTED)
                    .label("submitted_rows"),
                )
                .select_from(Teacher)
                .outerjoin(
                    StudentSubjectResult,
                    and_(
                        StudentSubjectResult.teacher_membership_id == Teacher.id,
                        StudentSubjectResult.tenant_id == Teacher.tenant_id,
                    ),
                )
                .join(TeacherAccount, TeacherAccount.id == Teacher.teacher_account_id)
                .where(Teacher.tenant_id == tenant_id)
                .group_by(
                    Teacher.id,
                    TeacherAccount.first_name,
                    TeacherAccount.last_name,
                    Teacher.staff_id,
                )
                .order_by(TeacherAccount.first_name.asc(), TeacherAccount.last_name.asc())
            )
        ).all()
        points: list[ChartPoint] = []
        for row in rows:
            total_rows = int(row.total_rows or 0)
            if total_rows <= 0:
                continue
            label = " ".join(part for part in [row.first_name, row.last_name] if part).strip()
            points.append(
                ChartPoint(
                    label=label or row.staff_id or "Teacher",
                    value=MetricsService._percent(int(row.submitted_rows or 0), total_rows),
                )
            )
        return points

    @staticmethod
    async def _result_completion_by_subject(
        db: AsyncSession, tenant_id: uuid.UUID
    ) -> list[ChartPoint]:
        rows = (
            await db.execute(
                select(
                    Subject.name,
                    func.count(StudentSubjectResult.id).label("total_rows"),
                    func.count(StudentSubjectResult.id)
                    .filter(StudentSubjectResult.status == AcademicResultStatus.SUBMITTED)
                    .label("submitted_rows"),
                )
                .join(Subject, Subject.id == StudentSubjectResult.subject_id)
                .where(StudentSubjectResult.tenant_id == tenant_id)
                .group_by(Subject.name)
                .order_by(Subject.name.asc())
            )
        ).all()
        return [
            ChartPoint(
                label=row.name or "Subject",
                value=MetricsService._percent(
                    int(row.submitted_rows or 0), int(row.total_rows or 0)
                ),
            )
            for row in rows
            if int(row.total_rows or 0) > 0
        ]

    @staticmethod
    async def _teacher_result_status_counts(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        teacher_id: uuid.UUID,
    ) -> list[ChartPoint]:
        rows = (
            await db.execute(
                select(
                    StudentSubjectResult.status,
                    func.count(StudentSubjectResult.id).label("value"),
                )
                .where(
                    StudentSubjectResult.tenant_id == tenant_id,
                    StudentSubjectResult.teacher_membership_id == teacher_id,
                )
                .group_by(StudentSubjectResult.status)
            )
        ).all()
        return [
            ChartPoint(label=MetricsService._enum_label(row[0]), value=int(row.value or 0))
            for row in rows
        ]

    @staticmethod
    async def _teacher_performance_trend(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        teacher_id: uuid.UUID,
    ) -> list[ChartPoint]:
        rows = (
            await db.execute(
                select(
                    AcademicSession.name.label("session_name"),
                    AcademicTerm.name.label("term_name"),
                    func.avg(StudentSubjectResult.total_score).label("average"),
                )
                .join(
                    AcademicSession,
                    AcademicSession.id == StudentSubjectResult.academic_session_id,
                )
                .join(AcademicTerm, AcademicTerm.id == StudentSubjectResult.academic_term_id)
                .where(
                    StudentSubjectResult.tenant_id == tenant_id,
                    StudentSubjectResult.teacher_membership_id == teacher_id,
                    StudentSubjectResult.status == AcademicResultStatus.SUBMITTED,
                )
                .group_by(AcademicSession.name, AcademicTerm.name)
                .order_by(AcademicSession.name.asc(), AcademicTerm.name.asc())
            )
        ).all()
        return [
            ChartPoint(
                label=f"{row.session_name} / {MetricsService._enum_label(row.term_name).replace('_', ' ')}",
                value=round(float(row.average or 0), 2),
            )
            for row in rows
        ]

    @staticmethod
    async def _student_result_metrics(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        student_id: uuid.UUID,
    ) -> tuple[dict[str, int | float], dict[str, list[ChartPoint]]]:
        rows = (
            await db.execute(
                select(
                    Subject.name.label("subject_name"),
                    StudentSubjectResult.grade,
                    StudentSubjectResult.total_score,
                    StudentSubjectResult.status,
                    AcademicSession.name.label("session_name"),
                    AcademicTerm.name.label("term_name"),
                )
                .join(Subject, Subject.id == StudentSubjectResult.subject_id)
                .join(
                    AcademicSession,
                    AcademicSession.id == StudentSubjectResult.academic_session_id,
                )
                .join(AcademicTerm, AcademicTerm.id == StudentSubjectResult.academic_term_id)
                .where(
                    StudentSubjectResult.tenant_id == tenant_id,
                    StudentSubjectResult.student_id == student_id,
                )
            )
        ).all()

        # Only locked academic results count as official student performance.
        finalized_rows = [row for row in rows if row.status == AcademicResultStatus.LOCKED]
        total_rows = len(rows)
        finalized_count = len(finalized_rows)
        average = (
            round(
                sum(float(row.total_score or 0) for row in finalized_rows) / finalized_count,
                2,
            )
            if finalized_count
            else 0
        )
        grade_counts: dict[str, int] = {}
        period_scores: dict[str, list[float]] = {}
        subject_scores: dict[str, list[float]] = {}
        for row in finalized_rows:
            grade_label = MetricsService._label(row.grade, "Ungraded")
            grade_counts[grade_label] = grade_counts.get(grade_label, 0) + 1
            period_label = f"{row.session_name} / {MetricsService._enum_label(row.term_name).replace('_', ' ')}"
            period_scores.setdefault(period_label, []).append(float(row.total_score or 0))
            subject_scores.setdefault(row.subject_name or "Subject", []).append(
                float(row.total_score or 0)
            )

        charts = {
            "grade_distribution": [
                ChartPoint(label=label, value=value) for label, value in grade_counts.items()
            ],
            "subject_comparison": [
                ChartPoint(label=label, value=round(sum(values) / len(values), 2))
                for label, values in subject_scores.items()
                if values
            ],
            "performance_trend": [
                ChartPoint(label=label, value=round(sum(values) / len(values), 2))
                for label, values in period_scores.items()
                if values
            ],
        }
        stats = {
            "current_average": average,
            "published_results": finalized_count,
            "pending_results": max(total_rows - finalized_count, 0),
            "result_rows_total": total_rows,
            "result_completion_percent": MetricsService._percent(finalized_count, total_rows),
        }
        return stats, charts

    @staticmethod
    async def _parent_link_counts(db: AsyncSession, parent: Parent) -> dict[str, int]:
        row = (
            await db.execute(
                select(
                    func.count(StudentParentLink.id).label("linked_students"),
                    func.count(StudentParentLink.id)
                    .filter(StudentParentLink.is_primary_contact.is_(True))
                    .label("primary_contacts"),
                ).where(
                    StudentParentLink.tenant_id == parent.tenant_id,
                    StudentParentLink.parent_membership_id == parent.id,
                )
            )
        ).one()
        return {key: int(value or 0) for key, value in row._mapping.items()}

    @staticmethod
    async def superadmin_dashboard(db: AsyncSession) -> DashboardMetricsResponse:
        async def fetch_dashboard() -> DashboardMetricsResponse:
            counts = await MetricsRepository.superadmin_counts(db)
            growth_rows = await MetricsRepository.tenant_growth(db)
            plan_counts = await MetricsRepository.subscription_plan_distribution(db)
            unverified_tenants = max(counts["total_tenants"] - counts["verified_tenants"], 0)
            return DashboardMetricsResponse(
                stats={
                    "total_tenants": counts["total_tenants"],
                    "active_tenants": counts["active_tenants"],
                    "pending_tenants": counts["pending_tenants"],
                    "suspended_tenants": counts["suspended_tenants"],
                },
                charts={
                    "tenant_growth": [
                        ChartPoint(
                            label=row.period.strftime("%Y-%m") if row.period else "",
                            value=int(row.value),
                        )
                        for row in growth_rows
                    ],
                    "tenant_status_distribution": [
                        ChartPoint(label="active", value=counts["active_tenants"]),
                        ChartPoint(label="pending", value=counts["pending_tenants"]),
                        ChartPoint(label="suspended", value=counts["suspended_tenants"]),
                    ],
                    "tenant_verification_breakdown": [
                        ChartPoint(label="verified", value=counts["verified_tenants"]),
                        ChartPoint(label="unverified", value=unverified_tenants),
                    ],
                    "subscription_plan_distribution": [
                        ChartPoint(label=plan.value, value=plan_counts.get(plan, 0))
                        for plan in SubscriptionPlan
                    ],
                },
            )

        return await MetricsService._cached_dashboard(
            key=superadmin_dashboard_cache_key(), fetcher=fetch_dashboard
        )

    @staticmethod
    async def tenant_admin_dashboard(
        db: AsyncSession, tenant_id: uuid.UUID
    ) -> DashboardMetricsResponse:
        async def fetch_dashboard() -> DashboardMetricsResponse:
            counts = await MetricsRepository.tenant_admin_counts(db, tenant_id)
            current_session = await MetricsRepository.current_academic_session(db, tenant_id)
            current_term = await MetricsRepository.current_academic_term(db, tenant_id)
            category_rows = await MetricsRepository.notice_category_counts(db, tenant_id)
            class_rows = await MetricsRepository.class_population(db, tenant_id)
            grade_rows = await MetricsRepository.result_grade_counts(db, tenant_id)
            result_status_rows = await MetricsRepository.result_status_counts(db, tenant_id)
            subject_performance_rows = await MetricsRepository.subject_performance(db, tenant_id)
            report_card_status = await MetricsService._report_card_status_chart(db, tenant_id)
            performance_trend = await MetricsService._performance_trend(db, tenant_id)
            class_performance = await MetricsService._class_performance(db, tenant_id)
            teacher_submission_progress = await MetricsService._teacher_submission_progress(
                db, tenant_id
            )
            result_completion_by_subject = await MetricsService._result_completion_by_subject(
                db, tenant_id
            )
            result_status_counts = MetricsService._status_count_map(result_status_rows)
            result_rows_total = sum(result_status_counts.values())
            result_rows_submitted = result_status_counts.get(
                AcademicResultStatus.SUBMITTED.value, 0
            )
            incomplete_profiles = max(counts["total_students"] - counts["complete_profiles"], 0)
            return DashboardMetricsResponse(
                stats={
                    "total_students": counts["total_students"],
                    "total_teachers": counts["total_teachers"],
                    "total_parents": counts["total_parents"],
                    "total_classes": counts["total_classes"],
                    "total_subjects": counts["total_subjects"],
                    "student_profiles_complete": counts["complete_profiles"],
                    "student_profiles_incomplete": incomplete_profiles,
                    "pending_teacher_accounts": counts["pending_teachers"],
                    "pending_parent_accounts": counts["pending_parents"],
                    "active_academic_session": current_session.name if current_session else None,
                    "active_academic_term": current_term.name.value if current_term else None,
                    "report_cards_generated": counts["report_cards_generated"],
                    "report_cards_published": counts["report_cards_published"],
                    "result_rows_total": result_rows_total,
                    "result_rows_submitted": result_rows_submitted,
                    "result_rows_draft": result_status_counts.get(
                        AcademicResultStatus.DRAFT.value, 0
                    ),
                    "result_completion_percent": MetricsService._percent(
                        result_rows_submitted, result_rows_total
                    ),
                },
                charts={
                    "user_population_breakdown": [
                        ChartPoint(label="students", value=counts["total_students"]),
                        ChartPoint(label="teachers", value=counts["total_teachers"]),
                        ChartPoint(label="parents", value=counts["total_parents"]),
                    ],
                    "student_profile_completion_rate": [
                        ChartPoint(label="complete", value=counts["complete_profiles"]),
                        ChartPoint(label="incomplete", value=incomplete_profiles),
                    ],
                    "account_status_overview": [
                        ChartPoint(label="active_teachers", value=counts["active_teachers"]),
                        ChartPoint(label="pending_teachers", value=counts["pending_teachers"]),
                        ChartPoint(label="active_parents", value=counts["active_parents"]),
                        ChartPoint(label="pending_parents", value=counts["pending_parents"]),
                    ],
                    "notices_by_category": [
                        ChartPoint(label=MetricsService._enum_label(row.label), value=row.value)
                        for row in category_rows
                    ],
                    "class_population": [
                        ChartPoint(label=f"{row.name} {row.arm or ''}".strip(), value=row.value)
                        for row in class_rows
                    ],
                    "grade_distribution": [
                        ChartPoint(
                            label=MetricsService._label(row.label, "Ungraded"), value=row.value
                        )
                        for row in grade_rows
                    ],
                    "result_status_distribution": [
                        ChartPoint(label=MetricsService._enum_label(row.label), value=row.value)
                        for row in result_status_rows
                    ],
                    "subject_performance": [
                        ChartPoint(label=row.name or "Subject", value=row.average)
                        for row in subject_performance_rows
                    ],
                    "report_card_status": report_card_status,
                    "performance_trend": performance_trend,
                    "class_performance": class_performance,
                    "teacher_submission_progress": teacher_submission_progress,
                    "result_completion_by_subject": result_completion_by_subject,
                },
            )

        return await MetricsService._cached_dashboard(
            key=tenant_admin_dashboard_cache_key(tenant_id), fetcher=fetch_dashboard
        )

    @staticmethod
    async def teacher_dashboard(
        db: AsyncSession, teacher_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> DashboardMetricsResponse:
        async def fetch_dashboard() -> DashboardMetricsResponse:
            class_rows = await MetricsRepository.teacher_class_sizes(
                db, tenant_id=tenant_id, teacher_id=teacher_id
            )
            assignment_count = await MetricsRepository.active_teacher_assignment_count(
                db, tenant_id=tenant_id, teacher_id=teacher_id
            )
            submitted_results = await MetricsRepository.submitted_result_count_for_teacher(
                db, tenant_id=tenant_id, teacher_id=teacher_id
            )
            teacher_grade_rows = await MetricsRepository.teacher_grade_counts(
                db, tenant_id=tenant_id, teacher_id=teacher_id
            )
            own_notice_ids = await MetricsRepository.teacher_notice_ids(
                db, tenant_id=tenant_id, teacher_id=teacher_id
            )
            read_count = await MetricsRepository.notice_read_count(
                db,
                tenant_id=tenant_id,
                notice_ids=own_notice_ids,
                statuses=[NotificationStatus.READ, NotificationStatus.ACKNOWLEDGED],
            )
            ack_count = await MetricsRepository.notice_read_count(
                db,
                tenant_id=tenant_id,
                notice_ids=own_notice_ids,
                statuses=[NotificationStatus.ACKNOWLEDGED],
            )
            category_rows = await MetricsRepository.teacher_notice_category_counts(
                db, tenant_id=tenant_id, teacher_id=teacher_id
            )
            result_status_distribution = await MetricsService._teacher_result_status_counts(
                db, tenant_id=tenant_id, teacher_id=teacher_id
            )
            performance_trend = await MetricsService._teacher_performance_trend(
                db, tenant_id=tenant_id, teacher_id=teacher_id
            )
            status_counts = {
                item.label: int(item.value or 0) for item in result_status_distribution
            }
            result_rows_total = sum(status_counts.values())
            result_rows_submitted = status_counts.get(AcademicResultStatus.SUBMITTED.value, 0)
            result_rows_draft = status_counts.get(AcademicResultStatus.DRAFT.value, 0)
            return DashboardMetricsResponse(
                stats={
                    "total_classes": len(class_rows),
                    "assigned_subjects": assignment_count,
                    "total_notices": len(own_notice_ids),
                    "results_submitted": submitted_results,
                    "results_published": submitted_results,
                    "result_rows_total": result_rows_total,
                    "result_rows_submitted": result_rows_submitted,
                    "result_rows_draft": result_rows_draft,
                    "pending_score_rows": max(result_rows_total - result_rows_submitted, 0),
                    "result_completion_percent": MetricsService._percent(
                        result_rows_submitted, result_rows_total
                    ),
                },
                charts={
                    "class_sizes": [
                        ChartPoint(label=f"{row.name} {row.arm or ''}".strip(), value=row.value)
                        for row in class_rows
                    ],
                    "notice_read_vs_acknowledged": [
                        ChartPoint(label="read", value=read_count),
                        ChartPoint(label="acknowledged", value=ack_count),
                    ],
                    "notice_category_breakdown": [
                        ChartPoint(label=MetricsService._enum_label(row.label), value=row.value)
                        for row in category_rows
                    ],
                    "grade_distribution": [
                        ChartPoint(
                            label=MetricsService._label(row.label, "Ungraded"), value=row.value
                        )
                        for row in teacher_grade_rows
                    ],
                    "result_status_distribution": result_status_distribution,
                    "performance_trend": performance_trend,
                    "pending_scores_by_class": [],
                },
            )

        return await MetricsService._cached_dashboard(
            key=teacher_dashboard_cache_key(tenant_id, teacher_id), fetcher=fetch_dashboard
        )

    @staticmethod
    async def _personal_notice_metrics(
        feed_total: int,
        read_count: int,
        category_counts: dict[str, int],
        extra_stats: dict[str, int | float | str | None] | None = None,
    ) -> DashboardMetricsResponse:
        stats = {
            "feed_total": feed_total,
            "read_count": read_count,
            "unread_count": max(feed_total - read_count, 0),
        }
        if extra_stats:
            stats.update(extra_stats)
        return DashboardMetricsResponse(
            stats=stats,
            charts={
                "notice_read_vs_unread": [
                    ChartPoint(label="read", value=read_count),
                    ChartPoint(label="unread", value=max(feed_total - read_count, 0)),
                ],
                "notice_category_breakdown": [
                    ChartPoint(label=label, value=value) for label, value in category_counts.items()
                ],
            },
        )

    @staticmethod
    async def parent_dashboard(db: AsyncSession, parent: Parent) -> DashboardMetricsResponse:
        async def fetch_dashboard() -> DashboardMetricsResponse:
            (
                feed_total,
                read_count,
                category_rows,
            ) = await MetricsRepository.notification_summary_for_actor(
                db,
                tenant_id=parent.tenant_id,
                actor_type=CommunicationActorType.PARENT,
                actor_id=parent.id,
            )
            category_counts = {
                MetricsService._enum_label(row.label): row.value for row in category_rows
            }
            link_counts = await MetricsService._parent_link_counts(db, parent)
            return await MetricsService._personal_notice_metrics(
                feed_total=feed_total,
                read_count=read_count,
                category_counts=category_counts,
                extra_stats=link_counts,
            )

        return await MetricsService._cached_dashboard(
            key=parent_dashboard_cache_key(parent.tenant_id, parent.id),
            fetcher=fetch_dashboard,
        )

    @staticmethod
    async def student_dashboard(db: AsyncSession, student: Student) -> DashboardMetricsResponse:
        async def fetch_dashboard() -> DashboardMetricsResponse:
            (
                feed_total,
                read_count,
                category_rows,
            ) = await MetricsRepository.notification_summary_for_actor(
                db,
                tenant_id=student.tenant_id,
                actor_type=CommunicationActorType.STUDENT,
                actor_id=student.id,
            )
            category_counts = {
                MetricsService._enum_label(row.label): row.value for row in category_rows
            }
            academic_stats, academic_charts = await MetricsService._student_result_metrics(
                db, tenant_id=student.tenant_id, student_id=student.id
            )
            return DashboardMetricsResponse(
                stats={
                    "feed_total": feed_total,
                    "read_count": read_count,
                    "unread_count": max(feed_total - read_count, 0),
                    **academic_stats,
                },
                charts={
                    **academic_charts,
                    "notice_read_vs_unread": [
                        ChartPoint(label="read", value=read_count),
                        ChartPoint(label="unread", value=max(feed_total - read_count, 0)),
                    ],
                    "notice_category_breakdown": [
                        ChartPoint(label=label, value=value)
                        for label, value in category_counts.items()
                    ],
                },
            )

        return await MetricsService._cached_dashboard(
            key=student_dashboard_cache_key(student.tenant_id, student.id),
            fetcher=fetch_dashboard,
        )
