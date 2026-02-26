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
from app.models.message import Message
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


async def create_group(
    db: AsyncSession,
    admin_user: CurrentUser,
    name: str,
    description: str,
    is_public: bool = False,
    invited_user_ids: list[uuid.UUID] | None = None,
) -> ChatGroup:
    try:
        group = ChatGroup(
            name=name,
            description=description,
            is_default=False,
            is_public=is_public,
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

        # For private groups, add invited users as members
        invited_usernames: list[str] = []
        if not is_public and invited_user_ids:
            for uid in invited_user_ids:
                if uid == admin_user.user_id:
                    continue
                # Lookup username from existing group_members or users table
                existing = await db.execute(
                    select(GroupMember).where(
                        GroupMember.group_id == group.id,
                        GroupMember.user_id == uid,
                    )
                )
                if existing.scalar_one_or_none() is not None:
                    continue

                # Try to get username from default group membership
                default_result = await db.execute(
                    select(GroupMember.username).join(ChatGroup).where(
                        ChatGroup.is_default.is_(True),
                        GroupMember.user_id == uid,
                    )
                )
                uname_row = default_result.scalar_one_or_none()
                uname = uname_row if uname_row else "Utente"

                new_member = GroupMember(
                    group_id=group.id,
                    user_id=uid,
                    username=uname,
                    role="member",
                )
                db.add(new_member)
                invited_usernames.append(uname)

            await db.flush()

        await create_system_message(
            db,
            group_id=group.id,
            content=f"Gruppo \"{name}\" creato da {admin_user.username}",
        )
        await db.commit()
        await db.refresh(group)

        # Send announcement to default public chat
        await _send_group_announcement(
            db, group, admin_user, is_public, invited_user_ids or [],
        )

        return group
    except Exception as e:
        await db.rollback()
        if "disk" in str(e).lower() or "storage" in str(e).lower():
            raise StorageLimitError()
        raise


async def _send_group_announcement(
    db: AsyncSession,
    group: ChatGroup,
    admin_user: CurrentUser,
    is_public: bool,
    invited_user_ids: list[uuid.UUID],
) -> None:
    """Send an announcement message to the default public group about a new group."""
    try:
        result = await db.execute(select(ChatGroup).where(ChatGroup.is_default.is_(True)))
        default_group = result.scalar_one_or_none()
        if default_group is None:
            return

        if is_public:
            content = f"🎉 Nuova chat pubblica disponibile: \"{group.name}\""
        else:
            content = f"🔒 Nuova chat privata creata: \"{group.name}\""

        metadata = {
            "group_invite": True,
            "target_group_id": str(group.id),
            "target_group_name": group.name,
            "target_group_description": group.description or "",
            "is_public": is_public,
            "invited_user_ids": [str(uid) for uid in invited_user_ids],
            "invite_code": group.invite_code,
        }

        msg = Message(
            group_id=default_group.id,
            sender_id=admin_user.user_id,
            sender_username=admin_user.username,
            content=content,
            message_type="announcement",
            extra_data=metadata,
        )
        db.add(msg)
        await db.commit()
        await db.refresh(msg)

        from app.api.websocket_routes import _broadcast_to_group_ws
        msg_data = {
            "id": str(msg.id),
            "group_id": str(msg.group_id),
            "sender_id": str(msg.sender_id),
            "sender_username": msg.sender_username,
            "content": msg.content,
            "message_type": msg.message_type,
            "reply_to_id": None,
            "reply_to_content": None,
            "reply_to_username": None,
            "metadata": msg.extra_data,
            "is_edited": msg.is_edited,
            "edited_at": None,
            "is_deleted": msg.is_deleted,
            "created_at": msg.created_at.isoformat(),
            "updated_at": msg.updated_at.isoformat() if msg.updated_at else msg.created_at.isoformat(),
        }
        await _broadcast_to_group_ws(default_group.id, "new_message", msg_data)
    except Exception:
        pass  # Non-critical, don't break group creation


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


async def join_public_group(db: AsyncSession, group_id: uuid.UUID, user: CurrentUser) -> ChatGroup:
    """Join a public group directly by ID."""
    group = await get_group(db, group_id)

    if not group.is_public:
        raise ChatServiceError(
            detail="Questo gruppo non è pubblico",
            status_code=403,
        )

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
    except AlreadyMemberError:
        raise
    except Exception as e:
        await db.rollback()
        if "disk" in str(e).lower() or "storage" in str(e).lower():
            raise StorageLimitError()
        raise


from app.core.exceptions import ChatServiceError
