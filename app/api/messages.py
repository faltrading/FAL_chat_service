import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotAMemberError
from app.core.security import get_current_user
from app.db.session import get_db
from app.models.message import Message
from app.schemas.auth import CurrentUser
from app.schemas.messages import (
    MessageCreate,
    MessageListResponse,
    MessageResponse,
    MessageUpdate,
    ReadStatusCreate,
    ReadStatusResponse,
)
from app.services import group_service, message_service

router = APIRouter(prefix="/api/v1/chat/groups/{group_id}/messages", tags=["messages"])


@router.post("", response_model=MessageResponse, status_code=201)
async def send_message(
    group_id: uuid.UUID,
    body: MessageCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await group_service.ensure_user_in_default_group(db, current_user)
    msg = await message_service.send_message(
        db,
        group_id=group_id,
        user=current_user,
        content=body.content,
        message_type=body.message_type,
        reply_to_id=body.reply_to_id,
        metadata=body.metadata,
    )
    return MessageResponse.model_validate(msg)


@router.get("", response_model=MessageListResponse)
async def list_messages(
    group_id: uuid.UUID,
    before: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await group_service.ensure_user_in_default_group(db, current_user)

    if not current_user.is_admin:
        is_member = await group_service.check_membership(db, group_id, current_user.user_id)
        if not is_member:
            raise NotAMemberError()

    messages, has_more = await message_service.get_messages(db, group_id, limit, before)
    next_cursor = messages[0].created_at.isoformat() if has_more and messages else None

    # Build map for reply resolution
    msg_map: dict[str, Message] = {str(m.id): m for m in messages}
    missing_ids = [
        m.reply_to_id for m in messages
        if m.reply_to_id and str(m.reply_to_id) not in msg_map
    ]
    if missing_ids:
        result = await db.execute(select(Message).where(Message.id.in_(missing_ids)))
        for rm in result.scalars():
            msg_map[str(rm.id)] = rm

    enriched = []
    for m in messages:
        resp = MessageResponse.model_validate(m)
        if m.reply_to_id:
            parent = msg_map.get(str(m.reply_to_id))
            if parent:
                resp.reply_to_content = parent.content if not parent.is_deleted else "[Messaggio eliminato]"
                resp.reply_to_username = parent.sender_username
        enriched.append(resp)

    return MessageListResponse(
        messages=enriched,
        has_more=has_more,
        next_cursor=next_cursor,
    )


@router.post("/read", response_model=list[ReadStatusResponse])
async def mark_read(
    group_id: uuid.UUID,
    body: ReadStatusCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    statuses = await message_service.mark_messages_read(db, current_user.user_id, body.message_ids)
    return [ReadStatusResponse.model_validate(s) for s in statuses]


@router.get("/unread/count")
async def unread_count(
    group_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    count = await message_service.get_unread_count(db, group_id, current_user.user_id)
    return {"unread_count": count}


@router.get("/{message_id}", response_model=MessageResponse)
async def get_message(
    group_id: uuid.UUID,
    message_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.is_admin:
        is_member = await group_service.check_membership(db, group_id, current_user.user_id)
        if not is_member:
            raise NotAMemberError()

    msg = await message_service.get_message(db, message_id)
    return MessageResponse.model_validate(msg)


@router.put("/{message_id}", response_model=MessageResponse)
async def edit_message(
    group_id: uuid.UUID,
    message_id: uuid.UUID,
    body: MessageUpdate,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    msg = await message_service.edit_message(db, message_id, current_user, body.content)
    return MessageResponse.model_validate(msg)


@router.delete("/{message_id}", status_code=204)
async def delete_message(
    group_id: uuid.UUID,
    message_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await message_service.delete_message(db, message_id, current_user)
