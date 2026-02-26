import json
import uuid
from datetime import datetime, timezone

from supabase import create_client

from app.core.config import settings

_supabase_client = None


def get_supabase_client():
    global _supabase_client
    if _supabase_client is None:
        _supabase_client = create_client(
            settings.SUPABASE_PROJECT_URL,
            settings.SUPABASE_SERVICE_ROLE_KEY,
        )
    return _supabase_client


def _serialize(obj):
    if isinstance(obj, uuid.UUID):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj


def _make_serializable(data: dict) -> dict:
    return {k: _serialize(v) for k, v in data.items()}


class RealtimeService:
    def __init__(self):
        self._channels: dict[str, object] = {}

    def _get_channel_name(self, group_id: uuid.UUID) -> str:
        return f"chat:group:{group_id}"

    async def broadcast_to_group(self, group_id: uuid.UUID, event_type: str, payload: dict):
        client = get_supabase_client()
        channel_name = self._get_channel_name(group_id)
        serialized = _make_serializable(payload)

        try:
            channel = client.channel(channel_name)
            channel.subscribe()
            channel.send_broadcast(
                event=event_type,
                data=serialized,
            )
            channel.unsubscribe()
        except Exception:
            pass

    async def broadcast_new_message(self, group_id: uuid.UUID, message_data: dict):
        await self.broadcast_to_group(group_id, "new_message", message_data)

    async def broadcast_message_edited(self, group_id: uuid.UUID, message_data: dict):
        await self.broadcast_to_group(group_id, "message_edited", message_data)

    async def broadcast_message_deleted(self, group_id: uuid.UUID, message_data: dict):
        await self.broadcast_to_group(group_id, "message_deleted", message_data)

    async def broadcast_user_joined(self, group_id: uuid.UUID, user_data: dict):
        await self.broadcast_to_group(group_id, "user_joined", user_data)

    async def broadcast_user_left(self, group_id: uuid.UUID, user_data: dict):
        await self.broadcast_to_group(group_id, "user_left", user_data)

    async def broadcast_system_message(self, group_id: uuid.UUID, message_data: dict):
        await self.broadcast_to_group(group_id, "system_message", message_data)

    async def broadcast_message_pinned(self, group_id: uuid.UUID, message_data: dict):
        await self.broadcast_to_group(group_id, "message_pinned", message_data)

    async def broadcast_typing(self, group_id: uuid.UUID, user_data: dict):
        await self.broadcast_to_group(group_id, "typing", user_data)


realtime_service = RealtimeService()
