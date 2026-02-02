import asyncio
import datetime
import logging

from dotenv import load_dotenv

from config import MAX_POLL_TIMEOUT
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
MENU_BACK_TEXT = "\u21a9\u041d\u0430\u0437\u0430\u0434"


def build_menu_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(MENU_CALENDAR_TEXT, callback_data="menu_calendar")],
            [InlineKeyboardButton(MENU_UPCOMING_TEXT, callback_data="menu_upcoming")],
            [InlineKeyboardButton(MENU_TEAM_TEXT, callback_data="menu_team")],
            [InlineKeyboardButton(MENU_MY_ID_TEXT, callback_data="menu_my_id")],
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
    if text.startswith("/start") or normalized == "??????":
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
        await update.message.reply_text("????:", reply_markup=build_menu_markup())
    elif normalized == MENU_CALENDAR_TEXT.lower():
        await show_calendar(update, context)
    elif normalized == "???????? ?????????":
        await show_calendar(update, context)
    elif normalized == MENU_UPCOMING_TEXT.lower():
        await show_upcoming_events(update, context)
    elif normalized == MENU_TEAM_TEXT.lower():
        await handle_team_command(update, context)
    elif normalized == MENU_MY_ID_TEXT.lower() or normalized in {"мой id", "my id", "show my id"}:
        await update.message.reply_text(f"Ваш ID: {update.effective_chat.id}")
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



async def poll_updates() -> None:
    api = await build_max_api()
    marker: str | None = None
    try:
        while True:
            try:
                response = await api.get_updates(
                    marker=marker,
                    timeout=MAX_POLL_TIMEOUT,
                    types=["message_created", "message_edited", "message_callback", "bot_started"],
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
                parsed = parse_update(raw_update, api)
                if not parsed:
                    continue
                chat = parsed.effective_chat
                if not chat:
                    continue
                context = MaxContext(bot=api, chat_data=chat_state.get(chat.id))
                try:
                    await dispatch_update(parsed, context)
                except Exception:  # noqa: BLE001
                    logger.exception("Failed to handle update: %s", raw_update)
    finally:
        await api.close()


def main() -> None:
    asyncio.run(poll_updates())


if __name__ == "__main__":
    logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    main()
