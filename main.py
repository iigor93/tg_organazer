import logging
import os
from datetime import date, time

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from datetime_selector import generate_calendar, generate_time_selector
from models import Event, User

load_dotenv(".env")


TOKEN = os.getenv("TG_BOT_TOKEN")


user_state = {}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user

    user_state.get(user.id)
    if not user_state:
        user_state[user.id] = User(telegram_id=user.id)

    keyboard = [[KeyboardButton("📍 Поделиться геолокацией", request_location=True)], [KeyboardButton("⏭ Пропустить")]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

    await update.message.reply_text(
        f"Привет, {user.first_name}!\n"
        "Я бот календарь.\n"
        "Для получения событий по твоему часовому поясу, тебе нужно поделиться геолокацией?",
        reply_markup=reply_markup,
    )


async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    location = update.message.location
    user = update.effective_user

    local_user: User = user_state.get(user.id)
    local_user.geo_location = f"широта={location.latitude}, долгота={location.longitude}"
    logger.info(
        f"Пользователь {user.id} ({user.first_name}) поделился геолокацией: " f"широта={location.latitude}, долгота={location.longitude}"
    )

    await update.message.reply_text("Спасибо за геолокацию!")

    await show_main_menu(update.message)


async def handle_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    logger.info(f"Пользователь {user.id} ({user.first_name}) пропустил геолокацию")

    await update.message.reply_text("Ок, продолжим без геолокации.")
    await show_main_menu(update.message)


async def show_main_menu(message) -> None:
    keyboard = [["📅 Показать календарь"], ["🗓 Ближайшие события"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await message.reply_text("Выберите действие:", reply_markup=reply_markup)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text

    if text == "📅 Показать календарь":
        await show_calendar(update, context)
    elif text == "🗓 Ближайшие события":
        await show_upcoming_events(update, context)
    else:
        await update.message.reply_text("Используйте кнопки для навигации.")


async def show_upcoming_events(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id

    local_user = user_state[user_id]
    _events = local_user.get_events()
    # await update.message.reply_text("Функция 'Ближайшие события' в разработке 🚧")
    await update.message.reply_text(_events)


async def show_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    today = date.today()
    reply_markup = generate_calendar(today.year, today.month)

    await update.message.reply_text(
        "📅 Выберите дату события:",
        reply_markup=reply_markup,
        parse_mode="MarkdownV2",
    )


async def handle_time_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка нажатий на кнопки выбора времени"""
    query = update.callback_query
    await query.answer()

    data = query.data
    print("DATA TIME: ", data)

    if data.startswith("time_hour_up_"):
        _, _, _, hours_str, minutes_str = data.split("_")
        hours = (int(hours_str) + 1) % 24
        minutes = int(minutes_str)

    elif data.startswith("time_hour_down_"):
        _, _, _, hours_str, minutes_str = data.split("_")
        hours = (int(hours_str) - 1) % 24
        minutes = int(minutes_str)

    elif data.startswith("time_minute_up_"):
        _, _, _, hours_str, minutes_str = data.split("_")
        hours = int(hours_str)
        minutes = (int(minutes_str) + 10) % 60

    elif data.startswith("time_minute_down_"):
        _, _, _, hours_str, minutes_str = data.split("_")
        hours = int(hours_str)
        minutes = (int(minutes_str) - 10) % 60

    elif data.startswith("time_confirm_"):
        _, _, hours_str, minutes_str = data.split("_")
        hours = int(hours_str)
        minutes = int(minutes_str)

        selected_time = time(hours, minutes)
        await query.message.reply_text(f"⏰ Вы выбрали время: {selected_time.strftime('%H:%M')}")
        return

    elif data == "time_ignore":
        return

    # Обновляем клавиатуру с новым временем
    reply_markup = generate_time_selector(hours, minutes)
    await query.edit_message_reply_markup(reply_markup=reply_markup)


async def handle_calendar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    data = query.data
    user_id = query.from_user.id
    local_user = user_state[user_id]

    if data.startswith("calendar_nav_"):
        _, _, year_str, month_str = data.split("_")
        year = int(year_str)
        month = int(month_str)

        # Генерируем новый календарь
        reply_markup = generate_calendar(year, month)
        await query.edit_message_text("📅 Выберите дату:", reply_markup=reply_markup)

    elif data.startswith("calendar_select_"):
        _, _, year_str, month_str, day_str = data.split("_")
        year = int(year_str)
        month = int(month_str)
        day = day_str

        month_names = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]
        formatted_date = f"{day} {month_names[month - 1]} {year} года"

        await query.message.reply_text(f"✅ Вы выбрали дату: {formatted_date}")

        _events = local_user.get_events()

        reply_btn_create = InlineKeyboardButton("Создать событие", callback_data=f"create_event_{year}_{month}_{day}")
        reply_btn_delete = InlineKeyboardButton("Удалить событие", callback_data=f"delete_event_{year}_{month}_{day}")
        reply_markup = InlineKeyboardMarkup([[reply_btn_create, reply_btn_delete]])
        await query.message.reply_text(text=_events, reply_markup=reply_markup)

    elif data.startswith("create_event_"):
        _, _, year_str, month_str, day_str = data.split("_")
        local_user.events.append(Event(title="Событие", event_datetime=f"{day_str}.{month_str}.{year_str}", recurrent="no"))

        reply_markup = generate_time_selector()

        await query.message.reply_text(text="Укажите время начала события", reply_markup=reply_markup)

    elif data == "ignore":
        pass


def main() -> None:
    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))

    # Получение геолокации
    application.add_handler(MessageHandler(filters.LOCATION, handle_location))
    # Пропуск геолокации
    application.add_handler(MessageHandler(filters.Regex("^⏭ Пропустить$"), handle_skip))

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(CallbackQueryHandler(handle_time_callback, pattern="^time_"))
    application.add_handler(CallbackQueryHandler(handle_calendar_callback))

    logger.info("Бот запущен...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S%z", level=logging.INFO)
    logger = logging.getLogger(__name__)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    main()
