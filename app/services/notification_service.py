"""
Lightweight fire-and-forget push notification trigger.

Sends an HTTP POST to the Supabase Edge Function that delivers Web Push
notifications.  Failures are logged but never propagate to the caller so
that business-critical paths (sending messages, creating calls) are not
disrupted by notification issues.
"""

import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_EDGE_FUNCTION_PATH = "/functions/v1/send-push-notification"
_TIMEOUT = 10.0  # seconds


def _edge_url() -> str | None:
    base = getattr(settings, "SUPABASE_PROJECT_URL", None)
    if not base:
        logger.warning("SUPABASE_PROJECT_URL not set — skipping push notification")
        return None
    return base.rstrip("/") + _EDGE_FUNCTION_PATH


async def send_notification(payload: dict[str, Any]) -> None:
    """POST *payload* to the push-notification Edge Function.

    This is intentionally fire-and-forget: every exception is caught and
    logged so that the caller's transaction is never affected.
    """
    url = _edge_url()
    if not url:
        return

    key = getattr(settings, "SUPABASE_SERVICE_ROLE_KEY", None)
    if not key:
        logger.warning("SUPABASE_SERVICE_ROLE_KEY not set — skipping push notification")
        return

    logger.info("Sending push notification to %s — type=%s", url, payload.get("type"))

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
            )
            if resp.status_code >= 400:
                logger.warning(
                    "Push notification edge function returned %s: %s",
                    resp.status_code,
                    resp.text[:200],
                )
            else:
                logger.info("Push notification sent successfully: %s", resp.text[:200])
    except httpx.TimeoutException:
        logger.warning("Push notification request timed out")
    except Exception:
        logger.exception("Push notification request failed")


async def notify_chat_message(
    *,
    group_id: str,
    group_name: str,
    sender_id: str,
    sender_username: str,
    message_preview: str,
) -> None:
    """Trigger push notification for a new chat message."""
    await send_notification({
        "type": "chat",
        "group_id": group_id,
        "group_name": group_name,
        "sender_id": sender_id,
        "sender_username": sender_username,
        "message_preview": message_preview,
    })


async def notify_call_created(
    *,
    call_id: str,
    room_name: str,
    creator_id: str,
    creator_username: str,
) -> None:
    """Trigger push notification for a new call room."""
    await send_notification({
        "type": "call",
        "call_id": call_id,
        "room_name": room_name,
        "creator_id": creator_id,
        "creator_username": creator_username,
    })
