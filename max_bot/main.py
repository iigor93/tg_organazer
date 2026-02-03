import asyncio
import datetime
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
from dotenv import load_dotenv

from config import MAX_POLL_TIMEOUT, MAX_WEBHOOK_PORT, TOKEN, WEBHOOK_MAX_SECRET, WEBHOOK_MAX_URL
from max_bot.client import build_max_api
from max_bot.compat import InlineKeyboardButton, InlineKeyboardMarkup
from max_bot.context import MaxContext, MaxUpdate
from max_bot.state import chat_state
from max_bot.update_parser import parse_update
from max_bot.handlers.cal import handle_calendar_callback, show_calendar
from max_bot.handlers.contacts import handle_contact, handle_team_callback, handle_team_command
from max_bot.handlers.events import (
    _get_back_button_state,
    generate_time_selector,
    get_event_constructor,
    handle_create_event_callback,
    handle_delete_event_callback,
    handle_edit_event_callback,
    handle_emoji_callback,
    handle_event_participants_callback,
    handle_participants_callback,
    handle_reschedule_event_callback,
    handle_time_callback,
    show_upcoming_events,
)
from max_bot.handlers.start import (
    MAIN_MENU_CALENDAR_TEXT,
    MAIN_MENU_UPCOMING_TEXT,
    SKIP_LOCATION_TEXT,
    handle_help,
    handle_location,
    handle_skip,
    start,
)

load_dotenv(".env")

logger = logging.getLogger(__name__)
MENU_TEXT = "\u041c\u0435\u043d\u044e"
MENU_CALENDAR_TEXT = "\u041a\u0430\u043b\u0435\u043d\u0434\u0430\u0440\u044c"
MENU_UPCOMING_TEXT = "\u0411\u043b\u0438\u0436\u0430\u0439\u0448\u0438\u0435 \u0441\u043e\u0431\u044b\u0442\u0438\u044f"
MENU_TEAM_TEXT = "\u0423\u0447\u0430\u0441\u0442\u043d\u0438\u043a\u0438"
MENU_MY_ID_TEXT = "\u041c\u043e\u0439 ID"
MENU_HELP_TEXT = "\u041f\u043e\u043c\u043e\u0449\u044c"
MENU_LINK_TG_TEXT = "\u0421\u0432\u044f\u0437\u0430\u0442\u044c \u0441 Telegram"
MENU_BACK_TEXT = "\u21a9\u041d\u0430\u0437\u0430\u0434"
MAX_WEBHOOK_UPDATE_TYPES = ["message_created", "message_edited", "message_callback", "bot_started"]
_WEBHOOK_LOOP: asyncio.AbstractEventLoop | None = None
_WEBHOOK_THREAD: threading.Thread | None = None
_WEBHOOK_QUEUE: asyncio.Queue | None = None
_WEBHOOK_WORKER_TASK: asyncio.Task | None = None


def build_menu_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(MENU_CALENDAR_TEXT, callback_data="menu_calendar")],
            [InlineKeyboardButton(MENU_UPCOMING_TEXT, callback_data="menu_upcoming")],
            [InlineKeyboardButton(MENU_TEAM_TEXT, callback_data="menu_team")],
            [InlineKeyboardButton(MENU_MY_ID_TEXT, callback_data="menu_my_id")],
            [InlineKeyboardButton(MENU_LINK_TG_TEXT, callback_data="menu_link_tg")],
            [InlineKeyboardButton(MENU_HELP_TEXT, callback_data="menu_help")],
            [InlineKeyboardButton(MENU_BACK_TEXT, callback_data="menu_back")],
        ]
    )


def _sanitize_attachments(attachments: list[dict] | None) -> list[dict] | None:
    if not attachments:
        return None
    cleaned: list[dict] = []
    for att in attachments:
        if not isinstance(att, dict):
            continue
        att_copy = {k: v for k, v in att.items() if k != "callback_id"}
        payload = att_copy.get("payload")
        if isinstance(payload, dict) and "buttons" in payload:
            att_copy["payload"] = {"buttons": payload.get("buttons", [])}
        cleaned.append(att_copy)
    return cleaned or None


async def _send_tg_link_request(tg_id: int, max_id: int) -> None:
    if not TOKEN:
        raise RuntimeError("TG_BOT_TOKEN is not set")
    payload = {
        "chat_id": tg_id,
        "text": (
            "\u041f\u0440\u0438\u0448\u0435\u043b \u0437\u0430\u043f\u0440\u043e\u0441 \u043d\u0430 \u0441\u0432\u044f\u0437\u044c "
            "\u0441 MAX \u0431\u043e\u0442\u043e\u043c.\n"
            "\u041f\u043e\u0434\u0442\u0432\u0435\u0440\u0434\u0438\u0442\u0435 \u043e\u0431\u044a\u0435\u0434\u0438\u043d\u0435\u043d\u0438\u0435."
        ),
        "reply_markup": {
            "inline_keyboard": [
                [
                    {
                        "text": "\u041f\u043e\u0434\u0442\u0432\u0435\u0440\u0434\u0438\u0442\u044c",
                        "callback_data": f"link_tg_confirm_{tg_id}_{max_id}",
                    }
                ],
                [
                    {
                        "text": "\u041e\u0442\u043a\u043b\u043e\u043d\u0438\u0442\u044c",
                        "callback_data": f"link_tg_decline_{tg_id}_{max_id}",
                    }
                ],
            ]
        },
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json=payload)
        response.raise_for_status()


async def handle_text(update: MaxUpdate, context: MaxContext) -> None:
    logger.info("handle_text")

    await_time_input = context.chat_data.get("await_time_input")
    if await_time_input:
        event = context.chat_data.get("event")
        if not event:
            context.chat_data.pop("await_time_input", None)
            await update.message.reply_text("Event not found. Please try again.")
            return

        raw_value = (update.message.text or "").strip()
        if not raw_value.isdigit():
            await update.message.reply_text("Please enter a number.")
            return

        value = int(raw_value)
        field = await_time_input.get("field")
        time_type = await_time_input.get("time_type")

        if field == "hour" and not (0 <= value <= 23):
            await update.message.reply_text("Hour must be between 0 and 23.")
            return

        if field == "minute" and not (0 <= value <= 59):
            await update.message.reply_text("Minutes must be between 0 and 59.")
            return

        base_time = event.start_time if time_type == "start" else event.stop_time
        if base_time is None:
            if time_type == "stop" and event.start_time:
                base_time = event.start_time
            else:
                base_time = datetime.time(12, 0)

        hours = base_time.hour
        minutes = base_time.minute
        if field == "hour":
            hours = value
        elif field == "minute":
            minutes = value

        selected_time = datetime.time(hours, minutes)
        if time_type == "start":
            event.start_time = selected_time
        else:
            event.stop_time = selected_time

        context.chat_data["event"] = event
        context.chat_data.pop("await_time_input", None)
        context.chat_data.pop("time_input_prompt_message_id", None)
        context.chat_data.pop("time_input_prompt_chat_id", None)

        reply_markup = generate_time_selector(hours=hours, minutes=minutes, time_type=time_type)
        message_id = context.chat_data.get("time_picker_message_id")
        if message_id:
            await context.bot.edit_message(message_id=message_id, attachments=reply_markup.to_attachments())
        else:
            await update.message.reply_text("Updated.", reply_markup=reply_markup)
        return

    await_event_description = context.chat_data.get("await_event_description")
    if await_event_description:
        event = context.chat_data.get("event")
        event.description = update.message.text
        context.chat_data["event"] = event
        has_participants = bool(event.all_user_participants)

        year, month, day = event.get_date()
        show_back_btn, back_callback_data = _get_back_button_state(context, event, year, month, day)
        text, reply_markup = get_event_constructor(
            event=event,
            year=year,
            month=month,
            day=day,
            has_participants=has_participants,
            show_details=bool(context.chat_data.get("edit_event_id")),
            show_back_btn=show_back_btn,
            back_callback_data=back_callback_data,
        )

        target_message_id = None
        if isinstance(await_event_description, dict):
            target_message_id = await_event_description.get("message_id")

        if target_message_id:
            await context.bot.edit_message(
                message_id=target_message_id,
                text=text,
                attachments=reply_markup.to_attachments(),
                fmt="html",
            )
        else:
            await update.message.reply_text(text=text, reply_markup=reply_markup, parse_mode="HTML")

        if isinstance(await_event_description, dict):
            prompt_message_id = await_event_description.get("prompt_message_id")
            if prompt_message_id:
                try:
                    await context.bot.edit_message(message_id=prompt_message_id, text=" ", attachments=[])
                except Exception:  # noqa: BLE001
                    logger.exception("Failed to clear description prompt message")

        if update.message and update.message.sender and update.message.sender.is_bot:
            try:
                await context.bot.edit_message(message_id=update.message.message_id, text=" ", attachments=[])
            except Exception:  # noqa: BLE001
                logger.exception("Failed to clear description input message")

        context.chat_data.pop("await_event_description", None)
        return

    await_tg_link = context.chat_data.get("await_tg_link")
    if await_tg_link:
        raw_value = (update.message.text or "").strip()
        if not raw_value.isdigit():
            await update.message.reply_text("\u041e\u0442\u043f\u0440\u0430\u0432\u044c\u0442\u0435 \u0447\u0438\u0441\u043b\u043e\u0432\u043e\u0439 Telegram ID.")
            return
        tg_id = int(raw_value)
        max_id = update.effective_chat.id
        try:
            await _send_tg_link_request(tg_id=tg_id, max_id=max_id)
            await update.message.reply_text(
                "\u0417\u0430\u043f\u0440\u043e\u0441 \u043e\u0442\u043f\u0440\u0430\u0432\u043b\u0435\u043d \u0432 Telegram. \u041f\u043e\u0434\u0442\u0432\u0435\u0440\u0434\u0438\u0442\u0435 \u0432 Telegram \u0431\u043e\u0442\u0435."
            )
            context.chat_data.pop("await_tg_link", None)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to send Telegram link request")
            await update.message.reply_text("\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043e\u0442\u043f\u0440\u0430\u0432\u0438\u0442\u044c \u0437\u0430\u043f\u0440\u043e\u0441 \u0432 Telegram.")
        return

    await update.message.reply_text("Unknown command.")


async def dispatch_update(update: MaxUpdate, context: MaxContext) -> None:
    if update.callback_query:
        data = update.callback_query.data
        if data == "menu_open":
            menu_message = update.callback_query.message
            if menu_message:
                context.chat_data["menu_back"] = {
                    "message_id": menu_message.id,
                    "text": menu_message.text or "",
                    "attachments": _sanitize_attachments(menu_message.attachments),
                }
            await update.callback_query.edit_message_text("Меню:", reply_markup=build_menu_markup())
        elif data == "menu_back":
            state = context.chat_data.pop("menu_back", None)
            menu_message = update.callback_query.message
            if state and menu_message and state.get("message_id") == menu_message.id:
                await context.bot.edit_message(
                    message_id=menu_message.id,
                    text=state.get("text") or "",
                    attachments=state.get("attachments"),
                )
            else:
                await update.callback_query.answer()
        elif data == "menu_calendar":
            await show_calendar(update, context)
        elif data == "menu_upcoming":
            await show_upcoming_events(update, context)
        elif data == "menu_team":
            await handle_team_command(update, context)
        elif data == "menu_my_id":
            await update.callback_query.message.reply_text(f"Ваш ID: {update.effective_chat.id}")
        elif data == "menu_link_tg":
            context.chat_data["await_tg_link"] = True
            await update.callback_query.message.reply_text(
                "Для синхронизации событий с Telegram ботом FamPlanner_bot пришлите свой telegram ID.",
                include_menu=False,
            )
        elif data == "menu_help":
            await handle_help(update, context)
        elif data.startswith("cal_"):
            await handle_calendar_callback(update, context)
        elif data.startswith("time_"):
            await handle_time_callback(update, context)
        elif data.startswith("create_event_"):
            await handle_create_event_callback(update, context)
        elif data.startswith("edit_event_"):
            await handle_edit_event_callback(update, context)
        elif data.startswith("delete_event_"):
            await handle_delete_event_callback(update, context)
        elif data.startswith("participants_"):
            await handle_participants_callback(update, context)
        elif data.startswith("team_"):
            await handle_team_callback(update, context)
        elif data.startswith("create_participant_event_"):
            await handle_event_participants_callback(update, context)
        elif data.startswith("reschedule_event_"):
            await handle_reschedule_event_callback(update, context)
        elif data.startswith("emoji_"):
            await handle_emoji_callback(update, context)
        else:
            await update.callback_query.answer()
        return

    if not update.message:
        return

    if update.message.location:
        await handle_location(update, context)
        return
    if update.message.contact:
        await handle_contact(update, context)
        return

    text = (update.message.text or "").strip()
    normalized = text.strip().lower()
    if text.startswith("/start") or normalized == "начать":
        await start(update, context)
    elif text.startswith("/help"):
        await handle_help(update, context)
    elif text.startswith("/team"):
        await handle_team_command(update, context)
    elif text.startswith("/calendar") or text.startswith("/show_calendar"):
        await show_calendar(update, context)
    elif text.startswith("/show_my_id") or text.startswith("/my_id"):
        await update.message.reply_text(f"Ваш ID: {update.effective_chat.id}")
    elif normalized == MENU_TEXT.lower():
        await update.message.reply_text("Меню:", reply_markup=build_menu_markup())
    elif normalized == MENU_CALENDAR_TEXT.lower():
        await show_calendar(update, context)
    elif normalized == "показать календарь":
        await show_calendar(update, context)
    elif normalized == MENU_UPCOMING_TEXT.lower():
        await show_upcoming_events(update, context)
    elif normalized == MENU_TEAM_TEXT.lower():
        await handle_team_command(update, context)
    elif normalized == MENU_MY_ID_TEXT.lower() or normalized in {"my id", "show my id"}:
        await update.message.reply_text(f"Ваш ID: {update.effective_chat.id}")
    elif normalized == MENU_LINK_TG_TEXT.lower():
        context.chat_data["await_tg_link"] = True
        await update.message.reply_text(
            "Для синхронизации событий с Telegram ботом FamPlanner_bot пришлите свой telegram ID."
        )
    elif normalized == MENU_HELP_TEXT.lower():
        await handle_help(update, context)
    elif text == MAIN_MENU_CALENDAR_TEXT:
        await show_calendar(update, context)
    elif text == MAIN_MENU_UPCOMING_TEXT:
        await show_upcoming_events(update, context)
    elif text == SKIP_LOCATION_TEXT:
        await handle_skip(update, context)
    else:
        await handle_text(update, context)


def _extract_webhook_updates(payload: object) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("updates", "items", "result"):
            items = payload.get(key)
            if isinstance(items, list):
                return [item for item in items if isinstance(item, dict)]
        return [payload]
    return []


def _run_webhook_loop(loop: asyncio.AbstractEventLoop) -> None:
    asyncio.set_event_loop(loop)
    loop.run_forever()


async def _webhook_worker() -> None:
    while True:
        payload = await _WEBHOOK_QUEUE.get()  # type: ignore[union-attr]
        if payload is None:
            _WEBHOOK_QUEUE.task_done()  # type: ignore[union-attr]
            break
        try:
            await _handle_webhook_payload(payload)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to process webhook payload")
        finally:
            _WEBHOOK_QUEUE.task_done()  # type: ignore[union-attr]


async def _start_webhook_worker() -> None:
    global _WEBHOOK_QUEUE, _WEBHOOK_WORKER_TASK
    if _WEBHOOK_QUEUE is None:
        _WEBHOOK_QUEUE = asyncio.Queue()
    if _WEBHOOK_WORKER_TASK is None or _WEBHOOK_WORKER_TASK.done():
        _WEBHOOK_WORKER_TASK = asyncio.create_task(_webhook_worker())


async def _stop_webhook_worker() -> None:
    if _WEBHOOK_QUEUE is not None:
        await _WEBHOOK_QUEUE.put(None)
        await _WEBHOOK_QUEUE.join()
    if _WEBHOOK_WORKER_TASK is not None:
        await _WEBHOOK_WORKER_TASK


async def _enqueue_webhook_payload(payload: object) -> None:
    if _WEBHOOK_QUEUE is None:
        await _start_webhook_worker()
    await _WEBHOOK_QUEUE.put(payload)  # type: ignore[union-attr]


def _start_webhook_loop() -> None:
    global _WEBHOOK_LOOP, _WEBHOOK_THREAD
    if _WEBHOOK_LOOP and _WEBHOOK_LOOP.is_running():
        return
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=_run_webhook_loop, args=(loop,), daemon=True)
    thread.start()
    _WEBHOOK_LOOP = loop
    _WEBHOOK_THREAD = thread
    asyncio.run_coroutine_threadsafe(_start_webhook_worker(), loop).result(timeout=5)


def _stop_webhook_loop() -> None:
    global _WEBHOOK_LOOP, _WEBHOOK_THREAD
    loop = _WEBHOOK_LOOP
    thread = _WEBHOOK_THREAD
    if not loop or not thread:
        return
    try:
        asyncio.run_coroutine_threadsafe(_stop_webhook_worker(), loop).result(timeout=5)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to stop webhook worker")
    if loop.is_running():
        loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5)
    loop.close()
    _WEBHOOK_LOOP = None
    _WEBHOOK_THREAD = None


async def _process_raw_update(raw_update: dict, api: "MaxApi") -> None:
    parsed = parse_update(raw_update, api)
    if not parsed:
        return
    chat = parsed.effective_chat
    if not chat:
        return
    context = MaxContext(bot=api, chat_data=chat_state.get(chat.id))
    try:
        await dispatch_update(parsed, context)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to handle update: %s", raw_update)


async def _handle_webhook_payload(payload: object) -> None:
    api = await build_max_api()
    try:
        for raw_update in _extract_webhook_updates(payload):
            await _process_raw_update(raw_update, api)
    finally:
        await api.close()


async def _ensure_webhook_subscription() -> None:
    if not WEBHOOK_MAX_URL:
        raise RuntimeError("WEBHOOK_MAX_URL is not set")
    api = await build_max_api()
    try:
        response = await api.create_subscription(
            url=WEBHOOK_MAX_URL,
            update_types=MAX_WEBHOOK_UPDATE_TYPES,
            secret=WEBHOOK_MAX_SECRET,
        )
        if isinstance(response, dict) and response.get("success") is False:
            message = response.get("message") or "Unknown error"
            raise RuntimeError(f"MAX webhook subscription failed: {message}")
    finally:
        await api.close()


async def _drop_webhook_subscription() -> None:
    if not WEBHOOK_MAX_URL:
        return
    api = await build_max_api()
    try:
        response = await api.delete_subscription(url=WEBHOOK_MAX_URL)
        if isinstance(response, dict) and response.get("success") is False:
            message = response.get("message") or "Unknown error"
            logger.warning("MAX webhook unsubscribe failed: %s", message)
    finally:
        await api.close()


class MaxWebhookHandler(BaseHTTPRequestHandler):
    server_version = "MaxWebhook/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        logger.info("MAX webhook: %s", fmt % args)

    def _is_authorized(self) -> bool:
        if not WEBHOOK_MAX_SECRET:
            return True
        token = self.headers.get("X-Max-Bot-Api-Secret")
        return bool(token and token == WEBHOOK_MAX_SECRET)

    def _send_text(self, status: int, body: str) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        self._send_text(200, "OK")

    def do_POST(self) -> None:  # noqa: N802
        if not self._is_authorized():
            self._send_text(403, "Forbidden")
            return
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length > 0 else b""
        if not body:
            self._send_text(400, "Empty payload")
            return
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            self._send_text(400, "Invalid JSON")
            return
        try:
            if _WEBHOOK_LOOP is None or not _WEBHOOK_LOOP.is_running():
                self._send_text(503, "Webhook loop not running")
                return
            future = asyncio.run_coroutine_threadsafe(_enqueue_webhook_payload(payload), _WEBHOOK_LOOP)
            future.result(timeout=2)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to process webhook payload")
            self._send_text(500, "Internal error")
            return
        self._send_text(200, "OK")


def run_webhook() -> None:
    asyncio.run(_ensure_webhook_subscription())
    _start_webhook_loop()
    server = ThreadingHTTPServer(("0.0.0.0", MAX_WEBHOOK_PORT), MaxWebhookHandler)
    server.daemon_threads = True
    logger.info("MAX bot webhook listen=0.0.0.0:%s url=%s", MAX_WEBHOOK_PORT, WEBHOOK_MAX_URL)
    try:
        server.serve_forever()
    finally:
        asyncio.run(_drop_webhook_subscription())
        _stop_webhook_loop()
        server.server_close()


async def poll_updates() -> None:
    api = await build_max_api()
    marker: str | None = None
    try:
        while True:
            try:
                response = await api.get_updates(
                    marker=marker,
                    timeout=MAX_POLL_TIMEOUT,
                    types=MAX_WEBHOOK_UPDATE_TYPES,
                )
            except Exception:  # noqa: BLE001
                logger.exception("MAX poll error")
                await asyncio.sleep(2)
                continue

            updates = []
            if isinstance(response, list):
                updates = response
            else:
                updates = response.get("updates") or response.get("items") or response.get("result") or []
                marker = response.get("marker") or response.get("next_marker") or marker

            for raw_update in updates:
                await _process_raw_update(raw_update, api)
    finally:
        await api.close()


def main() -> None:
    if WEBHOOK_MAX_URL:
        logger.info("Через webhook %s", WEBHOOK_MAX_URL)
        run_webhook()
    else:
        logger.info("Через Long polling")
        asyncio.run(poll_updates())


if __name__ == "__main__":
    logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    main()
