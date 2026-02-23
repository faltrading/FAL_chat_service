import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user, require_admin
from app.db.session import get_db
from app.schemas.auth import CurrentUser
from app.schemas.groups import (
    GroupCreate,
    GroupListResponse,
    GroupMemberResponse,
    GroupResponse,
    GroupUpdate,
)
from app.services import group_service

router = APIRouter(prefix="/api/v1/groups", tags=["groups"])


@router.post("", response_model=GroupResponse, status_code=201)
async def create_group(
    body: GroupCreate,
    admin_user: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    group = await group_service.create_group(db, admin_user, body.name, body.description)
    members = await group_service.get_group_members(db, group.id)
    return GroupResponse(
        id=group.id,
        name=group.name,
        description=group.description,
        is_default=group.is_default,
        is_public=group.is_public,
        invite_code=group.invite_code,
        created_by=group.created_by,
        member_count=len(members),
        created_at=group.created_at,
        updated_at=group.updated_at,
    )


@router.get("", response_model=GroupListResponse)
async def list_groups(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await group_service.ensure_user_in_default_group(db, current_user)
    groups = await group_service.list_groups_for_user(db, current_user)
    return GroupListResponse(
        groups=[GroupResponse(**g) for g in groups],
        total=len(groups),
    )


@router.get("/{group_id}", response_model=GroupResponse)
async def get_group(
    group_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    group = await group_service.get_group(db, group_id)
    if not current_user.is_admin:
        is_member = await group_service.check_membership(db, group_id, current_user.user_id)
        if not is_member and not group.is_default:
            from app.core.exceptions import NotAMemberError
            raise NotAMemberError()

    members = await group_service.get_group_members(db, group_id)
    return GroupResponse(
        id=group.id,
        name=group.name,
        description=group.description,
        is_default=group.is_default,
        is_public=group.is_public,
        invite_code=group.invite_code if current_user.is_admin else None,
        created_by=group.created_by,
        member_count=len(members),
        created_at=group.created_at,
        updated_at=group.updated_at,
    )


@router.put("/{group_id}", response_model=GroupResponse)
async def update_group(
    group_id: uuid.UUID,
    body: GroupUpdate,
    admin_user: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    group = await group_service.update_group(db, group_id, admin_user, body.name, body.description)
    members = await group_service.get_group_members(db, group.id)
    return GroupResponse(
        id=group.id,
        name=group.name,
        description=group.description,
        is_default=group.is_default,
        is_public=group.is_public,
        invite_code=group.invite_code,
        created_by=group.created_by,
        member_count=len(members),
        created_at=group.created_at,
        updated_at=group.updated_at,
    )


@router.delete("/{group_id}", status_code=204)
async def delete_group(
    group_id: uuid.UUID,
    admin_user: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    await group_service.delete_group(db, group_id)


@router.post("/{group_id}/regenerate-invite")
async def regenerate_invite(
    group_id: uuid.UUID,
    admin_user: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    new_code = await group_service.regenerate_invite_code(db, group_id)
    return {"invite_code": new_code}


@router.get("/{group_id}/members", response_model=list[GroupMemberResponse])
async def list_members(
    group_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.is_admin:
        is_member = await group_service.check_membership(db, group_id, current_user.user_id)
        if not is_member:
            from app.core.exceptions import NotAMemberError
            raise NotAMemberError()

    members = await group_service.get_group_members(db, group_id)
    return [
        GroupMemberResponse(
            id=m.id,
            user_id=m.user_id,
            username=m.username,
            role=m.role,
            joined_at=m.joined_at,
        )
        for m in members
    ]


@router.delete("/{group_id}/members/{user_id}", status_code=204)
async def remove_member(
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    admin_user: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    await group_service.remove_member(db, group_id, user_id, admin_user)


@router.post("/{group_id}/leave", status_code=204)
async def leave_group(
    group_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await group_service.leave_group(db, group_id, current_user)
