import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.core.security import decode_ws_token
from app.db.session import async_session_factory
from app.models.chat_group import ChatGroup
from app.services import group_service, message_service
from app.services.realtime import realtime_service

router = APIRouter(tags=["websocket"])

active_connections: dict[str, dict[str, WebSocket]] = {}


def _group_key(group_id: uuid.UUID) -> str:
    return str(group_id)


def _user_key(user_id: uuid.UUID) -> str:
    return str(user_id)


async def _broadcast_to_group_ws(group_id: uuid.UUID, event_type: str, data: dict, exclude_user: uuid.UUID | None = None):
    gk = _group_key(group_id)
    if gk not in active_connections:
        return

    payload = json.dumps({
        "type": event_type,
        "data": data,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }, default=str)

    disconnected = []
    for uk, ws in active_connections[gk].items():
        if exclude_user and uk == _user_key(exclude_user):
            continue
        try:
            await ws.send_text(payload)
        except Exception:
            disconnected.append(uk)

    for uk in disconnected:
        active_connections[gk].pop(uk, None)


async def close_all_connections():
    for gk in list(active_connections.keys()):
        for uk, ws in list(active_connections[gk].items()):
            try:
                await ws.close(code=1001, reason="Server shutdown")
            except Exception:
                pass
        active_connections[gk].clear()
    active_connections.clear()


@router.websocket("/api/v1/ws/chat/{group_id}")
async def websocket_chat(websocket: WebSocket, group_id: uuid.UUID):
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="Token mancante")
        return

    user = decode_ws_token(token)
    if user is None:
        await websocket.close(code=4001, reason="Token non valido")
        return

    async with async_session_factory() as db:
        is_member = await group_service.check_membership(db, group_id, user.user_id)
        if not is_member:
            result = await db.execute(
                select(ChatGroup).where(
                    ChatGroup.id == group_id,
                    ChatGroup.is_default.is_(True),
                )
            )
            if result.scalar_one_or_none():
                await group_service.ensure_user_in_default_group(db, user)
            else:
                await websocket.close(code=4003, reason="Non sei membro di questo gruppo")
                return

    await websocket.accept()

    gk = _group_key(group_id)
    uk = _user_key(user.user_id)

    if gk not in active_connections:
        active_connections[gk] = {}
    active_connections[gk][uk] = websocket

    await _broadcast_to_group_ws(
        group_id, "user_online",
        {"user_id": str(user.user_id), "username": user.username},
        exclude_user=user.user_id,
    )

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "data": {"message": "JSON non valido"},
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }))
                continue

            action = data.get("action")

            if action == "send_message":
                content = data.get("content", "").strip()
                if not content:
                    continue

                async with async_session_factory() as db:
                    try:
                        msg = await message_service.send_message(
                            db,
                            group_id=group_id,
                            user=user,
                            content=content,
                            message_type=data.get("message_type", "text"),
                            reply_to_id=uuid.UUID(data["reply_to_id"]) if data.get("reply_to_id") else None,
                            metadata=data.get("metadata", {}),
                        )
                        msg_data = {
                            "id": str(msg.id),
                            "group_id": str(msg.group_id),
                            "sender_id": str(msg.sender_id),
                            "sender_username": msg.sender_username,
                            "content": msg.content,
                            "message_type": msg.message_type,
                            "reply_to_id": str(msg.reply_to_id) if msg.reply_to_id else None,
                            "metadata": msg.extra_data,
                            "is_edited": msg.is_edited,
                            "edited_at": msg.edited_at.isoformat() if msg.edited_at else None,
                            "is_deleted": msg.is_deleted,
                            "created_at": msg.created_at.isoformat(),
                        }
                        await _broadcast_to_group_ws(group_id, "new_message", msg_data)
                    except Exception as e:
                        await websocket.send_text(json.dumps({
                            "type": "error",
                            "data": {"message": str(e)},
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }))

            elif action == "typing":
                await _broadcast_to_group_ws(
                    group_id, "typing",
                    {"user_id": str(user.user_id), "username": user.username},
                    exclude_user=user.user_id,
                )

            elif action == "edit_message":
                message_id = data.get("message_id")
                new_content = data.get("content", "").strip()
                if not message_id or not new_content:
                    continue

                async with async_session_factory() as db:
                    try:
                        msg = await message_service.edit_message(
                            db, uuid.UUID(message_id), user, new_content,
                        )
                        msg_data = {
                            "id": str(msg.id),
                            "group_id": str(msg.group_id),
                            "content": msg.content,
                            "is_edited": msg.is_edited,
                            "edited_at": msg.edited_at.isoformat() if msg.edited_at else None,
                        }
                        await _broadcast_to_group_ws(group_id, "message_edited", msg_data)
                    except Exception as e:
                        await websocket.send_text(json.dumps({
                            "type": "error",
                            "data": {"message": str(e)},
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }))

            elif action == "delete_message":
                message_id = data.get("message_id")
                if not message_id:
                    continue

                async with async_session_factory() as db:
                    try:
                        await message_service.delete_message(db, uuid.UUID(message_id), user)
                        await _broadcast_to_group_ws(
                            group_id, "message_deleted",
                            {"id": message_id, "deleted_by": user.username},
                        )
                    except Exception as e:
                        await websocket.send_text(json.dumps({
                            "type": "error",
                            "data": {"message": str(e)},
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }))

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if gk in active_connections:
            active_connections[gk].pop(uk, None)
            if not active_connections[gk]:
                del active_connections[gk]

        await _broadcast_to_group_ws(
            group_id, "user_offline",
            {"user_id": str(user.user_id), "username": user.username},
        )
