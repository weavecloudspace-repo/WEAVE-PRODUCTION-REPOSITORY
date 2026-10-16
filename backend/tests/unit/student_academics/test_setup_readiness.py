from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.modules.student_academics.curriculum_v2_schemas import SetupReadinessResponse
from app.modules.student_academics.setup_readiness import get_setup_readiness

SERVICE = "app.modules.student_academics.setup_readiness"


def result(*, mapping=None, rows=None, value=None):
    response = MagicMock()
    response.mappings.return_value.one.return_value = mapping
    response.scalars.return_value = rows or []
    response.scalar_one.return_value = value
    return response


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,can_open,calendar_count",
    [("draft", False, 1), ("draft", True, 1), ("open", False, 1), ("open", False, 0)],
)
async def test_readiness_uses_selected_term_configuration_and_canonical_blockers(
    status, can_open, calendar_count
):
    tenant_id, session_id, term_id = uuid4(), uuid4(), uuid4()
    session = SimpleNamespace(id=session_id, name="2026/27", status="open")
    term = SimpleNamespace(id=term_id, name="first_term", status=status, is_current=True)
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                result(
                    mapping={"levels": 2, "arms": 1, "classes": 3, "teachers": 1, "assessment": 1}
                ),
                result(value=1),  # A partly configured curriculum is incomplete.
                result(rows=[session]),
                result(rows=[term]),
                result(value=3),
                result(mapping={"calendar": calendar_count, "students": 0, "assignments": 0}),
            ]
        )
    )
    with (
        patch(
            f"{SERVICE}.TenantRepository.get_by_id",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    school_name="School",
                    institution_type="secondary",
                )
            ),
        ) as tenant,
        patch(
            f"{SERVICE}.specialization_workspace",
            new=AsyncMock(
                return_value={
                    "classes": [
                        {"specialization_required": True, "readiness": "missing"},
                    ]
                }
            ),
        ) as workspace,
        patch(
            f"{SERVICE}.StudentAcademicService.preview_grading_scale_readiness",
            new=AsyncMock(
                return_value=SimpleNamespace(is_ready=True, messages=[]),
            ),
        ),
        patch(
            f"{SERVICE}.StudentAcademicService.academic_term_dependency_preview",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    can_open=can_open,
                    blocker_messages=[] if can_open else ["Configure class specialization."],
                ),
            ),
        ) as preview,
    ):
        response = SetupReadinessResponse.model_validate(await get_setup_readiness(db, tenant_id))

    tenant.assert_awaited_once_with(db, tenant_id)
    workspace.assert_awaited_once_with(db, tenant_id, term_id)
    assert response.completion["school_basics"] is True
    assert response.completion["curriculum"] is False
    assert response.completion["departments"] is False
    assert response.completion["students"] is False
    assert response.completion["assignments"] is False
    assert response.completion["grading"] is True
    assert response.completion["readiness"] is (
        (calendar_count > 0) if status == "open" else can_open
    )
    if status == "draft":
        preview.assert_awaited_once_with(db, tenant_id, term_id)
        assert response.blockers == ([] if can_open else ["Configure class specialization."])
    else:
        preview.assert_not_awaited()
        assert response.blockers == (
            [] if calendar_count else ["The current open term has no active calendar."]
        )
    for call in db.execute.call_args_list:
        assert tenant_id in call.args[0].compile().params.values()
    evidence = db.execute.call_args_list[-1].args[0].compile()
    assert term_id in evidence.params.values()
    assert session_id in evidence.params.values()


@pytest.mark.asyncio
async def test_empty_school_readiness_against_database(db_session, tenant):
    # Exercise real aggregate SQL and the canonical grading service. Fixtures roll back.
    response = SetupReadinessResponse.model_validate(
        await get_setup_readiness(db_session, tenant.id)
    )
    assert response.academic_term_id is None
    for key in [
        "session",
        "term",
        "calendar",
        "levels",
        "classes",
        "curriculum",
        "teachers",
        "students",
        "grading",
        "readiness",
    ]:
        assert response.completion[key] is False
    assert response.completion["departments"] is None
    assert "school_logo" not in response.completion


@pytest.mark.asyncio
async def test_all_level_department_read_retains_tenant_scope():
    from app.modules.classes.department_repository import AcademicLevelDepartmentRepository

    tenant_id = uuid4()
    rows = MagicMock()
    rows.scalars.return_value.all.return_value = []
    db = SimpleNamespace(execute=AsyncMock(return_value=rows))
    await AcademicLevelDepartmentRepository.list_for_level(
        db, tenant_id, None, include_archived=True
    )
    query = db.execute.call_args.args[0].compile()
    assert tenant_id in query.params.values()
    assert "academic_level_id IS NULL" not in str(query)
