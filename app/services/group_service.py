import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    AlreadyMemberError,
    CannotDeleteDefaultGroupError,
    GroupNotFoundError,
    InsufficientPermissionsError,
    InvalidInviteCodeError,
    NotAMemberError,
    StorageLimitError,
)
from app.models.chat_group import ChatGroup
from app.models.group_member import GroupMember
from app.schemas.auth import CurrentUser
from app.services.message_service import create_system_message
from app.services.realtime import realtime_service


def generate_invite_code() -> str:
    return secrets.token_urlsafe(32)


async def get_or_create_default_group(db: AsyncSession, admin_user_id: uuid.UUID) -> ChatGroup:
    result = await db.execute(select(ChatGroup).where(ChatGroup.is_default.is_(True)))
    group = result.scalar_one_or_none()

    if group is None:
        group = ChatGroup(
            name=settings.DEFAULT_GROUP_NAME,
            description=settings.DEFAULT_GROUP_DESCRIPTION,
            is_default=True,
            is_public=True,
            created_by=admin_user_id,
        )
        db.add(group)
        await db.flush()

        admin_member = GroupMember(
            group_id=group.id,
            user_id=admin_user_id,
            username=settings.ADMIN_USERNAME,
            role="admin",
        )
        db.add(admin_member)
        await db.commit()
        await db.refresh(group)

    return group


async def ensure_user_in_default_group(db: AsyncSession, user: CurrentUser) -> bool:
    result = await db.execute(select(ChatGroup).where(ChatGroup.is_default.is_(True)))
    default_group = result.scalar_one_or_none()

    if default_group is None:
        return False

    member_result = await db.execute(
        select(GroupMember).where(
            GroupMember.group_id == default_group.id,
            GroupMember.user_id == user.user_id,
        )
    )
    existing = member_result.scalar_one_or_none()

    if existing is not None:
        return False

    try:
        new_member = GroupMember(
            group_id=default_group.id,
            user_id=user.user_id,
            username=user.username,
            role="admin" if user.is_admin else "member",
        )
        db.add(new_member)
        await db.flush()

        await create_system_message(
            db,
            group_id=default_group.id,
            content=f"{user.username} si è unito al gruppo",
        )
        await db.commit()

        await realtime_service.broadcast_user_joined(
            default_group.id,
            {"user_id": user.user_id, "username": user.username, "group_id": default_group.id},
        )
        return True
    except Exception as e:
        await db.rollback()
        if "disk" in str(e).lower() or "storage" in str(e).lower():
            raise StorageLimitError()
        raise


async def create_group(db: AsyncSession, admin_user: CurrentUser, name: str, description: str) -> ChatGroup:
    try:
        group = ChatGroup(
            name=name,
            description=description,
            is_default=False,
            is_public=False,
            invite_code=generate_invite_code(),
            created_by=admin_user.user_id,
        )
        db.add(group)
        await db.flush()

        admin_member = GroupMember(
            group_id=group.id,
            user_id=admin_user.user_id,
            username=admin_user.username,
            role="admin",
        )
        db.add(admin_member)
        await db.flush()

        await create_system_message(
            db,
            group_id=group.id,
            content=f"Gruppo \"{name}\" creato da {admin_user.username}",
        )
        await db.commit()
        await db.refresh(group)
        return group
    except Exception as e:
        await db.rollback()
        if "disk" in str(e).lower() or "storage" in str(e).lower():
            raise StorageLimitError()
        raise


async def get_group(db: AsyncSession, group_id: uuid.UUID) -> ChatGroup:
    result = await db.execute(select(ChatGroup).where(ChatGroup.id == group_id))
    group = result.scalar_one_or_none()
    if group is None:
        raise GroupNotFoundError()
    return group


async def list_groups_for_user(db: AsyncSession, user: CurrentUser) -> list[dict]:
    if user.is_admin:
        result = await db.execute(select(ChatGroup).order_by(ChatGroup.created_at))
        groups = result.scalars().all()
    else:
        member_group_ids = select(GroupMember.group_id).where(GroupMember.user_id == user.user_id)
        result = await db.execute(
            select(ChatGroup).where(
                (ChatGroup.is_default.is_(True)) | (ChatGroup.id.in_(member_group_ids))
            ).order_by(ChatGroup.created_at)
        )
        groups = result.scalars().all()

    groups_with_count = []
    for g in groups:
        count_result = await db.execute(
            select(func.count()).select_from(GroupMember).where(GroupMember.group_id == g.id)
        )
        member_count = count_result.scalar()
        groups_with_count.append({
            "id": g.id,
            "name": g.name,
            "description": g.description,
            "is_default": g.is_default,
            "is_public": g.is_public,
            "invite_code": g.invite_code if user.is_admin else None,
            "created_by": g.created_by,
            "member_count": member_count,
            "created_at": g.created_at,
            "updated_at": g.updated_at,
        })

    return groups_with_count


async def update_group(db: AsyncSession, group_id: uuid.UUID, admin_user: CurrentUser, name: str | None, description: str | None) -> ChatGroup:
    group = await get_group(db, group_id)
    changes = []

    if name is not None and name != group.name:
        old_name = group.name
        group.name = name
        changes.append(f"nome da \"{old_name}\" a \"{name}\"")

    if description is not None and description != group.description:
        group.description = description
        changes.append("descrizione aggiornata")

    if changes:
        group.updated_at = datetime.now(timezone.utc)
        await db.flush()
        change_text = ", ".join(changes)
        await create_system_message(
            db,
            group_id=group.id,
            content=f"{admin_user.username} ha modificato il gruppo: {change_text}",
        )
        await db.commit()
        await db.refresh(group)

    return group


async def delete_group(db: AsyncSession, group_id: uuid.UUID) -> None:
    group = await get_group(db, group_id)
    if group.is_default:
        raise CannotDeleteDefaultGroupError()
    await db.delete(group)
    await db.commit()


async def regenerate_invite_code(db: AsyncSession, group_id: uuid.UUID) -> str:
    group = await get_group(db, group_id)
    if group.is_default:
        raise CannotDeleteDefaultGroupError()
    group.invite_code = generate_invite_code()
    group.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(group)
    return group.invite_code


async def join_group_by_invite(db: AsyncSession, invite_code: str, user: CurrentUser) -> ChatGroup:
    result = await db.execute(select(ChatGroup).where(ChatGroup.invite_code == invite_code))
    group = result.scalar_one_or_none()
    if group is None:
        raise InvalidInviteCodeError()

    member_result = await db.execute(
        select(GroupMember).where(
            GroupMember.group_id == group.id,
            GroupMember.user_id == user.user_id,
        )
    )
    if member_result.scalar_one_or_none() is not None:
        raise AlreadyMemberError()

    try:
        new_member = GroupMember(
            group_id=group.id,
            user_id=user.user_id,
            username=user.username,
            role="member",
        )
        db.add(new_member)
        await db.flush()

        await create_system_message(
            db,
            group_id=group.id,
            content=f"{user.username} si è unito al gruppo",
        )
        await db.commit()

        await realtime_service.broadcast_user_joined(
            group.id,
            {"user_id": user.user_id, "username": user.username, "group_id": group.id},
        )
        return group
    except Exception as e:
        await db.rollback()
        if "disk" in str(e).lower() or "storage" in str(e).lower():
            raise StorageLimitError()
        raise


async def add_member_by_admin(
    db: AsyncSession,
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    username: str,
    admin_user: CurrentUser,
) -> GroupMember:
    group = await get_group(db, group_id)

    member_result = await db.execute(
        select(GroupMember).where(
            GroupMember.group_id == group_id,
            GroupMember.user_id == user_id,
        )
    )
    if member_result.scalar_one_or_none() is not None:
        raise AlreadyMemberError()

    try:
        new_member = GroupMember(
            group_id=group_id,
            user_id=user_id,
            username=username,
            role="member",
        )
        db.add(new_member)
        await db.flush()

        await create_system_message(
            db,
            group_id=group_id,
            content=f"{username} è stato aggiunto al gruppo da {admin_user.username}",
        )
        await db.commit()
        await db.refresh(new_member)

        await realtime_service.broadcast_user_joined(
            group_id,
            {"user_id": str(user_id), "username": username, "group_id": str(group_id)},
        )
        return new_member
    except AlreadyMemberError:
        raise
    except Exception as e:
        await db.rollback()
        if "disk" in str(e).lower() or "storage" in str(e).lower():
            raise StorageLimitError()
        raise


async def get_group_members(db: AsyncSession, group_id: uuid.UUID) -> list[GroupMember]:
    result = await db.execute(
        select(GroupMember).where(GroupMember.group_id == group_id).order_by(GroupMember.joined_at)
    )
    return list(result.scalars().all())


async def remove_member(db: AsyncSession, group_id: uuid.UUID, user_id: uuid.UUID, admin_user: CurrentUser) -> None:
    group = await get_group(db, group_id)

    member_result = await db.execute(
        select(GroupMember).where(
            GroupMember.group_id == group_id,
            GroupMember.user_id == user_id,
        )
    )
    member = member_result.scalar_one_or_none()
    if member is None:
        raise NotAMemberError()

    username = member.username
    await db.delete(member)
    await db.flush()

    await create_system_message(
        db,
        group_id=group_id,
        content=f"{username} è stato rimosso dal gruppo da {admin_user.username}",
    )
    await db.commit()

    await realtime_service.broadcast_user_left(
        group_id,
        {"user_id": user_id, "username": username, "group_id": group_id, "removed_by": admin_user.username},
    )


async def check_membership(db: AsyncSession, group_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    result = await db.execute(
        select(GroupMember).where(
            GroupMember.group_id == group_id,
            GroupMember.user_id == user_id,
        )
    )
    return result.scalar_one_or_none() is not None


async def leave_group(db: AsyncSession, group_id: uuid.UUID, user: CurrentUser) -> None:
    group = await get_group(db, group_id)
    if group.is_default:
        raise ChatServiceError(
            detail="Non puoi lasciare il gruppo pubblico predefinito",
            status_code=400,
        )

    member_result = await db.execute(
        select(GroupMember).where(
            GroupMember.group_id == group_id,
            GroupMember.user_id == user.user_id,
        )
    )
    member = member_result.scalar_one_or_none()
    if member is None:
        raise NotAMemberError()

    await db.delete(member)
    await db.flush()

    await create_system_message(
        db,
        group_id=group_id,
        content=f"{user.username} ha lasciato il gruppo",
    )
    await db.commit()

    await realtime_service.broadcast_user_left(
        group_id,
        {"user_id": user.user_id, "username": user.username, "group_id": group_id},
    )


from app.core.exceptions import ChatServiceError
