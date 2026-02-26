from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.session import get_db
from app.schemas.auth import CurrentUser
from app.schemas.groups import GroupResponse
from app.services import group_service

router = APIRouter(prefix="/api/v1/chat/groups", tags=["invites"])


class JoinByCodeRequest(BaseModel):
    invite_code: str


@router.post("/join", response_model=GroupResponse)
async def join_via_invite(
    body: JoinByCodeRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    group = await group_service.join_group_by_invite(db, body.invite_code, current_user)
    members = await group_service.get_group_members(db, group.id)
    return GroupResponse(
        id=group.id,
        name=group.name,
        description=group.description,
        is_default=group.is_default,
        is_public=group.is_public,
        invite_code=None,
        created_by=group.created_by,
        member_count=len(members),
        created_at=group.created_at,
        updated_at=group.updated_at,
    )
