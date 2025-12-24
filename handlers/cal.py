import logging
from calendar import monthrange
from datetime import date

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from config import MONTH_NAMES

logger = logging.getLogger(__name__)


def generate_calendar(year: int | None = None, month: int | None = None) -> InlineKeyboardMarkup:
    today = date.today()

    year = year or today.year
    month = month or today.month

    first_weekday, num_days = monthrange(year, month)

    month_names = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
    header = f"{month_names[month - 1]} {year}"

    keyboard = []

    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1

    keyboard.append(
        [
            InlineKeyboardButton("◀", callback_data=f"cal_nav_{prev_year}_{prev_month}"),
            InlineKeyboardButton(header, callback_data="cal_ignore"),
            InlineKeyboardButton("▶", callback_data=f"cal_nav_{next_year}_{next_month}"),
        ]
    )

    keyboard.append([InlineKeyboardButton(day, callback_data="cal_ignore") for day in ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]])

    week = []

    for _ in range(first_weekday):
        week.append(InlineKeyboardButton(" ", callback_data="cal_ignore"))

    for day in range(1, num_days + 1):
        # show_day = f"{day}²" if day == today.day else day  # todo тут будем добавлять кол-во задач на сегодня
        show_day = day
        week.append(InlineKeyboardButton(str(show_day), callback_data=f"cal_select_{year}_{month}_{day}"))

        if len(week) == 7:
            keyboard.append(week)
            week = []

    if week:
        for _ in range(7 - len(week)):
            week.append(InlineKeyboardButton(" ", callback_data="cal_ignore"))
        keyboard.append(week)

    keyboard.append(
        [
            InlineKeyboardButton(
                f"Сегодня {today.day}.{today.month}.{today.year}", callback_data=f"cal_select_{today.year}_{today.month}_{today.day}"
            )
        ]
    )

    return InlineKeyboardMarkup(keyboard)


async def show_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("show_calendar")

    today = date.today()
    reply_markup = generate_calendar(today.year, today.month)

    await update.message.reply_text(
        "📅 Выберите дату события:",
        reply_markup=reply_markup,
        parse_mode="MarkdownV2",
    )


async def handle_calendar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("handle_calendar_callback")
    query = update.callback_query
    await query.answer()

    data = query.data
    # user_id = query.from_user.id
    # local_user = user_state[user_id]

    if data.startswith("cal_nav_"):
        _, _, year_str, month_str = data.split("_")
        year = int(year_str)
        month = int(month_str)

        # Генерируем новый календарь
        reply_markup = generate_calendar(year, month)
        await query.edit_message_text("📅 Выберите дату:", reply_markup=reply_markup)

    elif data.startswith("cal_select_"):
        _, _, year_str, month_str, day_str = data.split("_")
        year = int(year_str)
        month = int(month_str)
        day = day_str

        formatted_date = f"{day} {(MONTH_NAMES[month - 1]).title()} {year} года"
        # _events = f"✅ Вы выбрали дату: {formatted_date}\n\n{local_user.get_events()}"
        _events = f"✅ Вы выбрали дату: *{formatted_date}*"

        reply_btn_create = InlineKeyboardButton("Создать событие", callback_data=f"create_event_begin_{year}_{month}_{day}")
        reply_btn_delete = InlineKeyboardButton("Удалить событие", callback_data=f"delete_event_{year}_{month}_{day}")
        reply_markup = InlineKeyboardMarkup([[reply_btn_create, reply_btn_delete]])
        await query.edit_message_text(text=_events, reply_markup=reply_markup, parse_mode="MarkdownV2")

    elif data == "cal_ignore":
        pass
