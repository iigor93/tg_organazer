import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import logger
from handlers.cal import handle_calendar_callback, show_calendar
from handlers.events import (
    get_event_constructor,
    handle_create_event_callback,
    handle_delete_event_callback,
    handle_participants_callback,
    handle_time_callback,
    show_upcoming_events,
)
from handlers.start import handle_location, handle_skip, start

load_dotenv(".env")


TOKEN = os.getenv("TG_BOT_TOKEN")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("handle_text")
    logger.info(update)

    if context.user_data.get("await_event_description"):
        event = context.user_data.get("event")
        event.title = update.message.text
        context.user_data["event"] = event

        # await update.message.reply_text(
        #     text=f"Добавлено описание к событию *{event.get_format_date()}*:\n\n{event.title}",
        #     parse_mode="MarkdownV2"
        # )
        title_add = f"Добавлено описание к событию *{event.get_format_date()}*:\n\n{event.title}"
        text, reply_markup = get_event_constructor(event=event)
        text = title_add + "\n" + text
        await update.message.reply_text(text=text, reply_markup=reply_markup, parse_mode="MarkdownV2")
        # получаем кнопки
        context.user_data.pop("await_event_description")
        return
    await update.message.reply_text("Используйте кнопки для навигации.")


async def all_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("ALL callbacks")
    logger.info(f"*** {update}")
    query = update.callback_query
    await query.answer()


def main() -> None:
    application = ApplicationBuilder().token(TOKEN).build()

    # start, Получение геолокации и Пропуск геолокации
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.LOCATION, handle_location))
    application.add_handler(MessageHandler(filters.Regex("^⏭ Пропустить$"), handle_skip))

    # Календарь
    application.add_handler(MessageHandler(filters.Regex("^📅 Показать календарь$"), show_calendar))
    application.add_handler(CallbackQueryHandler(handle_calendar_callback, pattern="^cal_"))

    # Создание\удаление события
    application.add_handler(CallbackQueryHandler(handle_time_callback, pattern="^time_"))
    application.add_handler(CallbackQueryHandler(handle_create_event_callback, pattern="^create_event_"))
    application.add_handler(CallbackQueryHandler(handle_delete_event_callback, pattern="^delete_event_"))
    application.add_handler(CallbackQueryHandler(handle_participants_callback, pattern="^participants_"))
    application.add_handler(MessageHandler(filters.Regex("^🗓 Ближайшие события$"), show_upcoming_events))

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    application.add_handler(CallbackQueryHandler(all_callbacks))

    logger.info("Бот запущен...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
