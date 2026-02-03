import datetime
import logging

from dotenv import load_dotenv
from telegram import BotCommand, Update
from telegram.error import BadRequest
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ggg
from config import SERVICE_ACCOUNTS, TOKEN, WEBHOOK_SECRET_TOKEN, WEBHOOK_URL
from database.session import engine
from handlers.cal import handle_calendar_callback, show_calendar
from handlers.contacts import handle_contact, handle_team_callback, handle_team_command
from handlers.events import (
    generate_time_selector,
    get_event_constructor,
    _get_back_button_state,
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
from handlers.link import handle_link_callback
from handlers.start import handle_help, handle_location, handle_skip, start

load_dotenv(".env")


logger = logging.getLogger(__name__)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    if isinstance(context.error, BadRequest):
        message = str(context.error)
        if "Message is not modified" in message:
            logger.info("Skip unchanged message update")
            return
        if "Query is too old" in message or "query id is invalid" in message:
            logger.info("Skip expired callback query")
            return
    logger.exception("Unhandled error", exc_info=context.error)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("handle_text")
    logger.info(update)

    await_time_input = context.chat_data.get("await_time_input")
    if await_time_input:
        event = context.chat_data.get("event")
        if not event:
            context.chat_data.pop("await_time_input", None)
            await update.message.reply_text("Событие не найдено. Откройте создание события заново.")
            return

        raw_value = (update.message.text or "").strip()
        if not raw_value.isdigit():
            await update.message.reply_text("Введите число.")
            return

        value = int(raw_value)
        field = await_time_input.get("field")
        time_type = await_time_input.get("time_type")

        if field == "hour" and not (0 <= value <= 23):
            await update.message.reply_text("Часы должны быть от 0 до 23.")
            return

        if field == "minute" and not (0 <= value <= 59):
            await update.message.reply_text("Минуты должны быть от 0 до 59.")
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
        prompt_message_id = await_time_input.get("prompt_message_id")
        prompt_chat_id = await_time_input.get("prompt_chat_id")
        if not prompt_message_id or not prompt_chat_id:
            prompt_message_id = context.chat_data.get("time_input_prompt_message_id")
            prompt_chat_id = context.chat_data.get("time_input_prompt_chat_id")
        context.chat_data.pop("await_time_input", None)
        context.chat_data.pop("time_input_prompt_message_id", None)
        context.chat_data.pop("time_input_prompt_chat_id", None)

        reply_markup = generate_time_selector(hours=hours, minutes=minutes, time_type=time_type)
        chat_id = context.chat_data.get("time_picker_chat_id")
        message_id = context.chat_data.get("time_picker_message_id")
        if chat_id and message_id:
            await context.bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=reply_markup,
            )
        else:
            await update.message.reply_text("Готово.", reply_markup=reply_markup)

        if update.message:
            try:
                await context.bot.delete_message(
                    chat_id=update.message.chat_id,
                    message_id=update.message.message_id,
                )
            except Exception:  # noqa: BLE001
                logger.exception("Failed to delete user time input message")

        if prompt_message_id and prompt_chat_id:
            try:
                await context.bot.delete_message(
                    chat_id=prompt_chat_id,
                    message_id=prompt_message_id,
                )
            except Exception:  # noqa: BLE001
                logger.exception("Failed to delete time input prompt message")

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
        target_chat_id = None
        prompt_message_id = None
        prompt_chat_id = None
        if isinstance(await_event_description, dict):
            target_message_id = await_event_description.get("message_id")
            target_chat_id = await_event_description.get("chat_id")
            prompt_message_id = await_event_description.get("prompt_message_id")
            prompt_chat_id = await_event_description.get("prompt_chat_id")
        if target_message_id and target_chat_id:
            await context.bot.edit_message_text(
                chat_id=target_chat_id,
                message_id=target_message_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
        else:
            await update.message.reply_text(text=text, reply_markup=reply_markup, parse_mode="HTML")

        # получаем кнопки
        context.chat_data.pop("await_event_description", None)

        if update.message:
            try:
                await context.bot.delete_message(
                    chat_id=update.message.chat_id,
                    message_id=update.message.message_id,
                )
            except Exception:  # noqa: BLE001
                logger.exception("Failed to delete user description message")

        if prompt_message_id and prompt_chat_id:
            try:
                await context.bot.delete_message(
                    chat_id=prompt_chat_id,
                    message_id=prompt_message_id,
                )
            except Exception:  # noqa: BLE001
                logger.exception("Failed to delete description prompt message")

        return
    await update.message.reply_text("Используйте кнопки для навигации.")


async def handle_my_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id if update.effective_user else None
    if user_id is None and update.message:
        user_id = update.message.chat_id
    if user_id is None:
        await update.message.reply_text("Не удалось определить ваш ID.")
        return
    await update.message.reply_text(f"{user_id}")


async def all_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("ALL callbacks")
    logger.info(f"*** {update}")
    query = update.callback_query
    await query.answer()


async def set_commands(app):
    await app.bot.set_my_commands(
        [
            BotCommand("start", "Запустить бота"),
            BotCommand("my_id", "Показать мой Telegram ID"),
            BotCommand("team", "Управление участниками"),
            BotCommand("help", "Help"),
        ]
    )
    if SERVICE_ACCOUNTS:
        try:
            for service_account in SERVICE_ACCOUNTS.split(";"):
                await app.bot.send_message(chat_id=service_account, text="App started")
        except:  # noqa
            logger.exception("err ")


async def shutdown(app):
    await engine.dispose()


def main() -> None:
    application = ApplicationBuilder().token(TOKEN).post_shutdown(shutdown).build()

    # start, Получение геолокации и Пропуск геолокации
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", handle_help))
    application.add_handler(CommandHandler("team", handle_team_command))
    application.add_handler(CommandHandler("my_id", handle_my_id))
    application.add_handler(MessageHandler(filters.LOCATION, handle_location))
    application.add_handler(MessageHandler(filters.Regex("^⏭ Пропустить$"), handle_skip))

    # Календарь
    application.add_handler(MessageHandler(filters.Regex("^📅 Показать календарь$"), show_calendar))
    application.add_handler(CallbackQueryHandler(handle_calendar_callback, pattern="^cal_"))

    # Создание\удаление события
    application.add_handler(CallbackQueryHandler(handle_time_callback, pattern="^time_"))
    application.add_handler(CallbackQueryHandler(handle_create_event_callback, pattern="^create_event_"))
    application.add_handler(CallbackQueryHandler(handle_edit_event_callback, pattern="^edit_event_"))
    application.add_handler(CallbackQueryHandler(handle_delete_event_callback, pattern="^delete_event_"))
    application.add_handler(CallbackQueryHandler(handle_participants_callback, pattern="^participants_"))
    application.add_handler(CallbackQueryHandler(handle_team_callback, pattern="^team_"))
    application.add_handler(CallbackQueryHandler(handle_event_participants_callback, pattern="^create_participant_event_"))
    application.add_handler(CallbackQueryHandler(handle_reschedule_event_callback, pattern="^reschedule_event_"))
    application.add_handler(CallbackQueryHandler(handle_emoji_callback, pattern="^emoji_"))
    application.add_handler(CallbackQueryHandler(handle_link_callback, pattern="^link_tg_"))
    application.add_handler(MessageHandler(filters.Regex("^🗓 Ближайшие события$"), show_upcoming_events))

    application.add_handler(MessageHandler(filters.CONTACT, handle_contact))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    application.add_handler(CallbackQueryHandler(all_callbacks))
    application.add_error_handler(error_handler)

    application.post_init = set_commands

    logger.info("Бот запущен...")

    if WEBHOOK_URL:
        logger.info(f"Через webhook {WEBHOOK_URL}")
        application.run_webhook(
            listen="0.0.0.0",  # noqa
            port=8001,
            secret_token=WEBHOOK_SECRET_TOKEN,
            webhook_url=WEBHOOK_URL,
            allowed_updates=Update.ALL_TYPES,
        )
    else:
        logger.info("Через Long polling")
        application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S%z", level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    main()
