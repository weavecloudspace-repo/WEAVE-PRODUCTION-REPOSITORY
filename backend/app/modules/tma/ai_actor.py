"""Trusted WEAVE staff identities adapted for the existing CBT AI services.

CBT machine/actor authentication stays unchanged at the CBT HTTP boundary.
"""

from __future__ import annotations

import uuid

from app.modules.cbt.auth.schemas import AuthenticatedCBTActor
from app.modules.teachers.models import TeacherMembership
from app.modules.tenant_admins.models import TenantAdmin
from app.modules.tma.authorization import TMAAuthor


def to_existing_ai_actor(actor: TMAAuthor) -> AuthenticatedCBTActor:
    if isinstance(actor, TeacherMembership):
        return AuthenticatedCBTActor(
            authorization_id=uuid.uuid4(),
            tenant_id=actor.tenant_id,
            actor_id=actor.teacher_account_id,
            membership_id=actor.id,
            role="teacher",
        )
    if isinstance(actor, TenantAdmin):
        return AuthenticatedCBTActor(
            authorization_id=uuid.uuid4(),
            tenant_id=actor.tenant_id,
            actor_id=actor.id,
            membership_id=None,
            role="admin",
        )
    raise TypeError("Only authenticated staff can use AI.")
