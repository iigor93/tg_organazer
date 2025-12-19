import logging
import os
from calendar import monthrange
from datetime import date

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)

load_dotenv(".env")
TOKEN = os.getenv("TG_BOT_TOKEN")


# Хранение текущего месяца для каждого пользователя
user_calendar_state = {}


# ========== КОМАНДА /START ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start"""
    user = update.effective_user

    # Создаем клавиатуру с кнопками
    keyboard = [[KeyboardButton("📍 Поделиться геолокацией", request_location=True)], [KeyboardButton("⏭ Пропустить")]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

    await update.message.reply_text(
        f"👋 Привет, {user.first_name}!\n" "Я бот с календарем. Хочешь поделиться своей геолокацией?", reply_markup=reply_markup
    )


# ========== ОБРАБОТКА ГЕОЛОКАЦИИ ==========
async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка полученной геолокации"""
    location = update.message.location
    user = update.effective_user

    # Выводим координаты в консоль
    logger.info(
        f"Пользователь {user.id} ({user.first_name}) поделился геолокацией: " f"широта={location.latitude}, долгота={location.longitude}"
    )

    await update.message.reply_text("✅ Спасибо за геолокацию!")

    # Показываем меню с календарем и событиями
    await show_main_menu(update.message)


async def handle_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка пропуска геолокации"""
    user = update.effective_user
    logger.info(f"Пользователь {user.id} ({user.first_name}) пропустил геолокацию")

    await update.message.reply_text("✅ Ок, продолжим без геолокации.")

    # Показываем меню с календарем и событиями
    await show_main_menu(update.message)


# ========== ГЛАВНОЕ МЕНЮ ==========
async def show_main_menu(message) -> None:
    """Показ главного меню с кнопками"""
    keyboard = [["📅 Показать календарь"], ["🗓 Ближайшие события"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await message.reply_text("Выберите действие:", reply_markup=reply_markup)


# ========== ОБРАБОТКА ТЕКСТОВЫХ КОМАНД ==========
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка текстовых сообщений"""
    text = update.message.text

    if text == "📅 Показать календарь":
        await show_calendar(update, context)
    elif text == "🗓 Ближайшие события":
        await show_upcoming_events(update, context)
    else:
        await update.message.reply_text("Используйте кнопки для навигации.")


async def show_upcoming_events(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показ ближайших событий (заглушка)"""
    await update.message.reply_text("Функция 'Ближайшие события' в разработке 🚧")


# ========== КАЛЕНДАРЬ ==========
def generate_calendar(year=None, month=None):
    """Генерация inline-клавиатуры календаря для указанного месяца и года"""
    today = date.today()
    if year is None:
        year = today.year
    if month is None:
        month = today.month

    # Определяем первый день месяца и количество дней
    first_weekday, num_days = monthrange(year, month)

    # Заголовок с месяцем и годом
    month_names = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
    header = f"{month_names[month - 1]} {year}"

    # Создаем inline-клавиатуру
    keyboard = []

    # Кнопки навигации
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1

    nav_buttons = [
        InlineKeyboardButton("◀", callback_data=f"calendar_nav_{prev_year}_{prev_month}"),
        InlineKeyboardButton(header, callback_data="ignore"),
        InlineKeyboardButton("▶", callback_data=f"calendar_nav_{next_year}_{next_month}"),
    ]
    keyboard.append(nav_buttons)

    # Дни недели
    weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    keyboard.append([InlineKeyboardButton(day, callback_data="ignore") for day in weekdays])

    # Дни месяца
    week = []

    # Пустые кнопки для дней предыдущего месяца
    for _ in range(first_weekday):
        week.append(InlineKeyboardButton(" ", callback_data="ignore"))

    # Кнопки для дней текущего месяца
    for day in range(1, num_days + 1):
        show_day = f"{day}²" if day == today.day else day
        week.append(InlineKeyboardButton(str(show_day), callback_data=f"calendar_select_{year}_{month}_{day}"))

        # Если неделя заполнена, добавляем в клавиатуру и начинаем новую
        if len(week) == 7:
            keyboard.append(week)
            week = []

    # Пустые кнопки для оставшихся ячеек
    if week:
        for _ in range(7 - len(week)):
            week.append(InlineKeyboardButton(" ", callback_data="ignore"))
        keyboard.append(week)

    # Кнопка "Сегодня"
    keyboard.append(
        [
            InlineKeyboardButton(
                f"Сегодня {today.day}.{today.month}.{today.year}", callback_data=f"calendar_select_{today.year}_{today.month}_{today.day}"
            )
        ]
    )

    return InlineKeyboardMarkup(keyboard)


async def show_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать календарь текущего месяца"""
    today = date.today()
    reply_markup = generate_calendar(today.year, today.month)

    # Сохраняем состояние календаря для пользователя
    user_id = update.effective_user.id
    user_calendar_state[user_id] = {"year": today.year, "month": today.month}
    await update.message.reply_text(
        "📅 Выберите *дату*:",
        reply_markup=reply_markup,
        parse_mode="MarkdownV2",
    )


# ========== ОБРАБОТКА INLINE-КНОПОК КАЛЕНДАРЯ ==========
async def handle_calendar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка нажатий на inline-кнопки календаря"""
    query = update.callback_query
    await query.answer()  # Подтверждаем нажатие

    data = query.data
    user_id = query.from_user.id

    if data.startswith("calendar_nav_"):
        # Навигация по месяцам
        _, _, year_str, month_str = data.split("_")
        year = int(year_str)
        month = int(month_str)

        # Обновляем состояние
        user_calendar_state[user_id] = {"year": year, "month": month}

        # Генерируем новый календарь
        reply_markup = generate_calendar(year, month)
        await query.edit_message_text("📅 Выберите дату:", reply_markup=reply_markup)

    elif data.startswith("calendar_select_"):
        # Выбор даты
        _, _, year_str, month_str, day_str = data.split("_")
        year = int(year_str)
        month = int(month_str)
        day = day_str

        # Форматируем дату
        month_names = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]
        formatted_date = f"{day} {month_names[month - 1]} {year} года"

        # Отправляем сообщение о выбранной дате
        await query.message.reply_text(f"✅ Вы выбрали дату: {formatted_date}")

    elif data == "ignore":
        # Игнорируем нажатия на пустые кнопки или заголовки
        pass


def main() -> None:
    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))

    # Получение геолокации
    application.add_handler(MessageHandler(filters.LOCATION, handle_location))
    # Пропуск геолокации
    application.add_handler(MessageHandler(filters.Regex("^⏭ Пропустить$"), handle_skip))

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(CallbackQueryHandler(handle_calendar_callback))

    print("Бот запущен...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
