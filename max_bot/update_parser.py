import logging
from typing import Any

from max_bot.client import MaxApi
from max_bot.context import MaxCallbackQuery, MaxChat, MaxMessage, MaxUpdate

logger = logging.getLogger(__name__)


def _parse_user(data: dict | None) -> MaxChat:
    if not data:
        return MaxChat(id=0, first_name=None, last_name=None)
    user_id = data.get("id") or data.get("user_id") or 0
    first_name = data.get("name") or data.get("first_name")
    last_name = data.get("last_name")
    return MaxChat(id=int(user_id), first_name=first_name, last_name=last_name)


def _parse_message(data: dict | None, api: MaxApi) -> MaxMessage | None:
    if not data:
        return None
    body = data.get("body") or {}
    message_id = data.get("id") or data.get("message_id") or body.get("mid") or body.get("message_id") or 0
    text = body.get("text")
    location = None
    attachments = body.get("attachments") or []
    for attachment in attachments:
        att_type = attachment.get("type")
        if att_type not in {"geo_location", "location"}:
            continue
        payload = attachment.get("payload") or {}
        lat = payload.get("lat") or payload.get("latitude")
        lon = payload.get("lon") or payload.get("longitude")
        if lat is not None and lon is not None:
            location = {"latitude": lat, "longitude": lon}
            break
    sender = _parse_user(data.get("sender"))
    recipient = _parse_user(data.get("recipient")) if data.get("recipient") else None
    return MaxMessage(id=int(message_id), text=text, location=location, sender=sender, recipient=recipient, bot=api)


def _extract_callback_payload(update: dict[str, Any]) -> str | None:
    for key in ("payload", "data", "callback_data"):
        if key in update:
            return update.get(key)
    callback = update.get("callback") or {}
    if "payload" in callback:
        return callback.get("payload")
    message = update.get("message") or {}
    if "payload" in message:
        return message.get("payload")
    body = message.get("body") or {}
    return body.get("payload")


def parse_update(raw_update: dict[str, Any], api: MaxApi) -> MaxUpdate | None:
    update_type = raw_update.get("update_type")
    message_data = raw_update.get("message")

    if update_type in {"message_created", "message_edited"}:
        message = _parse_message(message_data, api)
        if not message:
            return None
        return MaxUpdate(message=message)

    if update_type == "message_callback":
        message = _parse_message(message_data, api)
        payload = _extract_callback_payload(raw_update)
        user_data = raw_update.get("user") or raw_update.get("sender")
        from_user = _parse_user(user_data) if user_data else (message.sender if message else MaxChat(id=0))
        if not payload:
            logger.warning("Missing callback payload: %s", raw_update)
            return None
        if not message:
            return None
        callback = MaxCallbackQuery(data=str(payload), message=message, from_user=from_user, bot=api)
        return MaxUpdate(callback_query=callback)

    return None
