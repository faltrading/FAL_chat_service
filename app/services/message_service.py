import uuid
from datetime import datetime, timezone

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    InsufficientPermissionsError,
    MessageNotFoundError,
    NotAMemberError,
    StorageLimitError,
)
from app.models.group_member import GroupMember
from app.models.message import Message
from app.models.message_read_status import MessageReadStatus
from app.schemas.auth import CurrentUser
from app.services.realtime import realtime_service


def _message_to_dict(msg: Message) -> dict:
    return {
        "id": msg.id,
        "group_id": msg.group_id,
        "sender_id": msg.sender_id,
        "sender_username": msg.sender_username,
        "content": msg.content if not msg.is_deleted else "[Messaggio eliminato]",
        "message_type": msg.message_type,
        "reply_to_id": msg.reply_to_id,
        "metadata": msg.extra_data or {},
        "is_edited": msg.is_edited,
        "edited_at": msg.edited_at,
        "is_deleted": msg.is_deleted,
        "is_pinned": msg.is_pinned,
        "pinned_at": msg.pinned_at,
        "pinned_by": msg.pinned_by,
        "created_at": msg.created_at,
        "updated_at": msg.updated_at,
    }


async def create_system_message(db: AsyncSession, group_id: uuid.UUID, content: str) -> Message:
    msg = Message(
        group_id=group_id,
        sender_id=None,
        sender_username=None,
        content=content,
        message_type="system",
    )
    db.add(msg)
    await db.flush()

    await realtime_service.broadcast_system_message(group_id, _message_to_dict(msg))
    return msg


async def send_message(
    db: AsyncSession,
    group_id: uuid.UUID,
    user: CurrentUser,
    content: str,
    message_type: str = "text",
    reply_to_id: uuid.UUID | None = None,
    metadata: dict | None = None,
) -> Message:
    membership = await db.execute(
        select(GroupMember).where(
            GroupMember.group_id == group_id,
            GroupMember.user_id == user.user_id,
        )
    )
    if membership.scalar_one_or_none() is None:
        raise NotAMemberError()

    if message_type == "admin_announcement" and not user.is_admin:
        raise InsufficientPermissionsError()

    if reply_to_id is not None:
        reply_result = await db.execute(
            select(Message).where(Message.id == reply_to_id, Message.group_id == group_id)
        )
        if reply_result.scalar_one_or_none() is None:
            raise MessageNotFoundError()

    try:
        msg = Message(
            group_id=group_id,
            sender_id=user.user_id,
            sender_username=user.username,
            content=content,
            message_type=message_type,
            reply_to_id=reply_to_id,
            extra_data=metadata or {},
        )
        db.add(msg)
        await db.commit()
        await db.refresh(msg)

        await realtime_service.broadcast_new_message(group_id, _message_to_dict(msg))
        return msg
    except Exception as e:
        await db.rollback()
        error_str = str(e).lower()
        if "disk" in error_str or "storage" in error_str or "space" in error_str:
            raise StorageLimitError()
        raise


async def edit_message(
    db: AsyncSession,
    message_id: uuid.UUID,
    user: CurrentUser,
    new_content: str,
) -> Message:
    result = await db.execute(select(Message).where(Message.id == message_id))
    msg = result.scalar_one_or_none()
    if msg is None:
        raise MessageNotFoundError()

    if msg.is_deleted:
        raise MessageNotFoundError()

    if msg.message_type == "system":
        raise InsufficientPermissionsError()

    if msg.sender_id != user.user_id and not user.is_admin:
        raise InsufficientPermissionsError()

    try:
        msg.content = new_content
        msg.is_edited = True
        msg.edited_at = datetime.now(timezone.utc)
        msg.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(msg)

        await realtime_service.broadcast_message_edited(msg.group_id, _message_to_dict(msg))
        return msg
    except Exception as e:
        await db.rollback()
        error_str = str(e).lower()
        if "disk" in error_str or "storage" in error_str or "space" in error_str:
            raise StorageLimitError()
        raise


async def delete_message(
    db: AsyncSession,
    message_id: uuid.UUID,
    user: CurrentUser,
) -> Message:
    result = await db.execute(select(Message).where(Message.id == message_id))
    msg = result.scalar_one_or_none()
    if msg is None:
        raise MessageNotFoundError()

    if msg.sender_id != user.user_id and not user.is_admin:
        raise InsufficientPermissionsError()

    msg.is_deleted = True
    msg.content = "[Messaggio eliminato]"
    msg.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(msg)

    await realtime_service.broadcast_message_deleted(
        msg.group_id,
        {"id": msg.id, "group_id": msg.group_id, "deleted_by": user.username},
    )

    if user.is_admin and msg.sender_id and msg.sender_id != user.user_id:
        await create_system_message(
            db,
            group_id=msg.group_id,
            content=f"Un messaggio è stato rimosso da {user.username}",
        )
        await db.commit()

    return msg


async def get_messages(
    db: AsyncSession,
    group_id: uuid.UUID,
    limit: int = 50,
    before: datetime | None = None,
) -> tuple[list[Message], bool]:
    query = select(Message).where(Message.group_id == group_id)

    if before is not None:
        query = query.where(Message.created_at < before)

    query = query.order_by(Message.created_at.desc()).limit(limit + 1)

    result = await db.execute(query)
    messages = list(result.scalars().all())

    has_more = len(messages) > limit
    if has_more:
        messages = messages[:limit]

    messages.reverse()
    return messages, has_more


async def get_message(db: AsyncSession, message_id: uuid.UUID) -> Message:
    result = await db.execute(select(Message).where(Message.id == message_id))
    msg = result.scalar_one_or_none()
    if msg is None:
        raise MessageNotFoundError()
    return msg


async def mark_messages_read(
    db: AsyncSession,
    user_id: uuid.UUID,
    message_ids: list[uuid.UUID],
) -> list[MessageReadStatus]:
    statuses = []
    for msg_id in message_ids:
        existing = await db.execute(
            select(MessageReadStatus).where(
                MessageReadStatus.message_id == msg_id,
                MessageReadStatus.user_id == user_id,
            )
        )
        if existing.scalar_one_or_none() is None:
            status = MessageReadStatus(
                message_id=msg_id,
                user_id=user_id,
            )
            db.add(status)
            statuses.append(status)

    if statuses:
        await db.commit()
        for s in statuses:
            await db.refresh(s)

    return statuses


async def get_unread_count(
    db: AsyncSession,
    group_id: uuid.UUID,
    user_id: uuid.UUID,
) -> int:
    subquery = select(MessageReadStatus.message_id).where(
        MessageReadStatus.user_id == user_id
    )
    result = await db.execute(
        select(func.count()).select_from(Message).where(
            Message.group_id == group_id,
            Message.is_deleted.is_(False),
            Message.id.notin_(subquery),
        )
    )
    return result.scalar() or 0


async def toggle_pin_message(
    db: AsyncSession,
    message_id: uuid.UUID,
    group_id: uuid.UUID,
    user: CurrentUser,
) -> Message:
    """Pin or unpin a message. Any group member can pin/unpin."""
    membership = await db.execute(
        select(GroupMember).where(
            GroupMember.group_id == group_id,
            GroupMember.user_id == user.user_id,
        )
    )
    if membership.scalar_one_or_none() is None:
        raise NotAMemberError()

    result = await db.execute(
        select(Message).where(Message.id == message_id, Message.group_id == group_id)
    )
    msg = result.scalar_one_or_none()
    if msg is None:
        raise MessageNotFoundError()
    if msg.is_deleted:
        raise MessageNotFoundError()

    new_pinned = not msg.is_pinned
    msg.is_pinned = new_pinned
    msg.pinned_at = datetime.now(timezone.utc) if new_pinned else None
    msg.pinned_by = user.username if new_pinned else None
    msg.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(msg)

    await realtime_service.broadcast_message_pinned(
        group_id,
        {
            "id": msg.id,
            "group_id": msg.group_id,
            "is_pinned": msg.is_pinned,
            "pinned_at": msg.pinned_at,
            "pinned_by": msg.pinned_by,
        },
    )
    return msg


async def get_pinned_messages(
    db: AsyncSession,
    group_id: uuid.UUID,
) -> list[Message]:
    result = await db.execute(
        select(Message).where(
            Message.group_id == group_id,
            Message.is_pinned.is_(True),
            Message.is_deleted.is_(False),
        ).order_by(Message.pinned_at.desc())
    )
    return list(result.scalars().all())
