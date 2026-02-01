from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from max_bot.client import MaxApi
from max_bot.compat import InlineKeyboardMarkup, ReplyKeyboardMarkup

logger = logging.getLogger(__name__)


@dataclass
class MaxChat:
    id: str | int
    first_name: str | None = None
    last_name: str | None = None
    is_bot: bool | None = None
    type: str = "private"

    @property
    def full_name(self) -> str:
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        return self.first_name or self.last_name or str(self.id)


@dataclass
class MaxMessage:
    id: str | int
    text: str | None
    location: dict | None
    sender: MaxChat
    recipient: MaxChat | None
    bot: MaxApi

    @property
    def message_id(self) -> str | int:
        return self.id

    @property
    def chat_id(self) -> int:
        if self.recipient and self.recipient.is_bot is False:
            return self.recipient.id
        if self.sender and self.sender.is_bot is False:
            return self.sender.id
        return self.recipient.id if self.recipient else self.sender.id

    async def reply_text(
        self, text: str, reply_markup: InlineKeyboardMarkup | ReplyKeyboardMarkup | None = None, parse_mode: str | None = None
    ) -> "MaxMessage | None":
        attachments = None
        if reply_markup:
            attachments = reply_markup.to_attachments()
        fmt = None
        if parse_mode == "HTML":
            fmt = "html"
        if self.recipient and self.recipient.is_bot is False:
            target_user_id = self.recipient.id
        elif self.sender and self.sender.is_bot is False:
            target_user_id = self.sender.id
        else:
            target_user_id = self.recipient.id if self.recipient else self.sender.id
        response = await self.bot.send_message(text=text, user_id=target_user_id, attachments=attachments, fmt=fmt)
        message_data = response.get("message") if isinstance(response, dict) else None
        if not message_data:
            return None
        body = message_data.get("body") or {}
        message_id = message_data.get("id") or message_data.get("message_id") or body.get("mid") or body.get("message_id") or 0
        return MaxMessage(
            id=message_id,
            text=text,
            location=None,
            sender=self.sender,
            recipient=self.recipient,
            bot=self.bot,
        )


@dataclass
class MaxCallbackQuery:
    data: str
    message: MaxMessage
    from_user: MaxChat
    bot: MaxApi

    async def answer(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    async def edit_message_text(self, text: str, reply_markup: InlineKeyboardMarkup | None = None, parse_mode: str | None = None) -> None:
        attachments = reply_markup.to_attachments() if reply_markup else []
        fmt = None
        if parse_mode == "HTML":
            fmt = "html"
        await self.bot.edit_message(message_id=self.message.id, text=text, attachments=attachments, fmt=fmt)

    async def edit_message_reply_markup(self, reply_markup: InlineKeyboardMarkup | None = None) -> None:
        attachments = reply_markup.to_attachments() if reply_markup else []
        await self.bot.edit_message(message_id=self.message.id, attachments=attachments)


@dataclass
class MaxUpdate:
    message: MaxMessage | None = None
    callback_query: MaxCallbackQuery | None = None

    @property
    def effective_chat(self) -> MaxChat | None:
        if self.callback_query:
            return self.callback_query.from_user
        if self.message:
            return self.message.sender
        return None

    @property
    def effective_user(self) -> MaxChat | None:
        return self.effective_chat


@dataclass
class MaxContext:
    bot: MaxApi
    chat_data: dict[str, Any] = field(default_factory=dict)
