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
from handlers.events import handle_create_event_callback, handle_delete_event_callback, handle_time_callback, show_upcoming_events
from handlers.start import handle_location, handle_skip, start
from models import User

load_dotenv(".env")


TOKEN = os.getenv("TG_BOT_TOKEN")


user_state = {717923644: User(telegram_id=717923644)}
awaiting_event_description = {}

#
# async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
#     logger.info("handle_text")
#
#     text = update.message.text
#
#     await_description = awaiting_event_description.get(update.effective_user.id)
#
#     if await_description:
#         awaiting_event_description.pop(update.effective_user.id)
#         day = 23
#         month = 12
#         year = 2025
#         formatted_date = f"{day} {MONTH_NAMES[int(month) - 1]} {year} года"
#         text = f"Создать событие на {formatted_date}"
#
#         start_btn = InlineKeyboardButton("Начало", callback_data=f"create_event_start_{year}_{month}_{day}")
#         stop_btn = InlineKeyboardButton("Окончание", callback_data=f"create_event_stop_{year}_{month}_{day}")
#         description_btn = InlineKeyboardButton("Описание", callback_data=f"create_event_description_{year}_{month}_{day}")
#         recurrent_btn = InlineKeyboardButton("Повтор", callback_data=f"create_event_recurrent_{year}_{month}_{day}")
#         participants_btn = InlineKeyboardButton("Участники", callback_data=f"create_event_participants_{year}_{month}_{day}")
#
#         reply_markup = InlineKeyboardMarkup([[start_btn, stop_btn], [description_btn], [recurrent_btn], [participants_btn]])
#
#         await update.message.reply_text(
#             text,
#             reply_markup=reply_markup,
#             parse_mode="MarkdownV2",
#         )
#
#     elif text == "📅 Показать календарь":
#         await show_calendar(update, context)
#     elif text == "🗓 Ближайшие события":
#         await show_upcoming_events(update, context)
#     else:
#         await update.message.reply_text("Используйте кнопки для навигации.")


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
    application.add_handler(MessageHandler(filters.Regex("^🗓 Ближайшие события$"), show_upcoming_events))

    # application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    application.add_handler(CallbackQueryHandler(all_callbacks))

    logger.info("Бот запущен...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
