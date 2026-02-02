import asyncio
import logging
from typing import Any

import httpx

from config import MAX_API_BASE, MAX_BOT_TOKEN

logger = logging.getLogger(__name__)


class MaxApi:
    def __init__(self, token: str | None = None, base_url: str | None = None) -> None:
        if not token:
            raise ValueError("MAX_BOT_TOKEN is required")
        self._token = token
        self._base_url = base_url or MAX_API_BASE
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=40.0)

    async def close(self) -> None:
        await self._client.aclose()

    async def request(self, method: str, path: str, params: dict | None = None, payload: dict | None = None) -> dict:
        headers = {"Authorization": self._token}
        response = await self._client.request(method, path, params=params, json=payload, headers=headers)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            logger.exception(
                "MAX API error %s %s: %s | params=%s payload=%s",
                method,
                path,
                response.text,
                params,
                payload,
            )
            raise
        return response.json() if response.text else {}

    async def get_updates(
        self,
        marker: str | None = None,
        limit: int = 100,
        timeout: int = 30,
        types: list[str] | None = None,
    ) -> dict:
        params: dict[str, Any] = {
            "limit": limit,
            "timeout": timeout,
        }
        if marker:
            params["marker"] = marker
        if types:
            params["types"] = ",".join(types)
        return await self.request("GET", "/updates", params=params)

    async def send_message(
        self,
        text: str,
        user_id: int | None = None,
        chat_id: int | None = None,
        attachments: list[dict] | None = None,
        fmt: str | None = None,
        notify: bool | None = True,
        disable_link_preview: bool | None = None,
        include_menu: bool = True,
    ) -> dict:
        params: dict[str, Any] = {}
        if user_id is not None:
            params["user_id"] = user_id
        if chat_id is not None:
            params["chat_id"] = chat_id
        if disable_link_preview is not None:
            params["disable_link_preview"] = disable_link_preview

        if include_menu:
            menu_text = "\u041c\u0435\u043d\u044e"
            menu_payload = "menu_open"
            menu_button = {"type": "callback", "text": menu_text, "payload": menu_payload}
            if attachments is None:
                attachments = [{"type": "inline_keyboard", "payload": {"buttons": [[menu_button]]}}]
            else:
                inline_keyboard = None
                for att in attachments:
                    if att.get("type") == "inline_keyboard":
                        inline_keyboard = att
                        break
                if inline_keyboard is None:
                    attachments.append({"type": "inline_keyboard", "payload": {"buttons": [[menu_button]]}})
                else:
                    payload = inline_keyboard.setdefault("payload", {})
                    buttons = payload.setdefault("buttons", [])
                    has_menu = any(
                        btn.get("text") == menu_text and btn.get("payload") == menu_payload for row in buttons for btn in row
                    )
                    if not has_menu:
                        buttons.append([menu_button])

        payload: dict[str, Any] = {"text": text}
        if attachments is not None:
            payload["attachments"] = attachments
        if fmt:
            payload["format"] = fmt
        if notify is not None:
            payload["notify"] = notify

        return await self.request("POST", "/messages", params=params, payload=payload)

    async def edit_message(
        self,
        message_id: str | int,
        text: str | None = None,
        attachments: list[dict] | None = None,
        fmt: str | None = None,
        notify: bool | None = True,
    ) -> dict:
        params = {"message_id": message_id}
        payload: dict[str, Any] = {}
        if text is not None:
            payload["text"] = text
        if attachments is not None:
            payload["attachments"] = attachments
        if fmt:
            payload["format"] = fmt
        if notify is not None:
            payload["notify"] = notify

        return await self.request("PUT", "/messages", params=params, payload=payload)


async def build_max_api() -> MaxApi:
    await asyncio.sleep(0)
    return MaxApi(token=MAX_BOT_TOKEN, base_url=MAX_API_BASE)
