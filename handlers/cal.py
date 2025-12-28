import logging
from calendar import monthrange
from datetime import date

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from config import MONTH_NAMES
from database.db_controller import db_controller

logger = logging.getLogger(__name__)


def to_superscript(number: int) -> str:
    superscript_map = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")
    return str(number).translate(superscript_map)


async def generate_calendar(user_id: int, year: int | None = None, month: int | None = None) -> InlineKeyboardMarkup:
    today = date.today()

    year = year or today.year
    month = month or today.month

    event_dict = await db_controller.get_current_month_events_by_user(user_id=user_id, month=month, year=year)

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
        number_events = event_dict.get(day)
        show_day = f"{day}{to_superscript(number_events)}" if number_events else day
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
    user_id = update.effective_user.id

    today = date.today()
    reply_markup = await generate_calendar(year=today.year, month=today.month, user_id=user_id)

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
    user_id = query.from_user.id
    # local_user = user_state[user_id]

    if data.startswith("cal_nav_"):
        _, _, year_str, month_str = data.split("_")
        year = int(year_str)
        month = int(month_str)

        # Генерируем новый календарь
        reply_markup = await generate_calendar(year=year, month=month, user_id=user_id)
        await query.edit_message_text("📅 Выберите дату события:", reply_markup=reply_markup)

    elif data.startswith("cal_select_"):
        logger.info("Выбор события cal_select_")
        _, _, year_str, month_str, day_str = data.split("_")
        year = int(year_str)
        month = int(month_str)
        day = day_str

        events = await db_controller.get_current_day_events_by_user(user_id=user_id, month=month, year=year, day=int(day))

        reply_btn_create = InlineKeyboardButton("Создать событие", callback_data=f"create_event_begin_{year}_{month}_{day}")
        reply_btn_delete = InlineKeyboardButton("Удалить событие", callback_data=f"delete_event_{year}_{month}_{day}")
        _btn = [reply_btn_create]
        formatted_date = f"{day} {(MONTH_NAMES[month - 1]).title()} {year} года"

        if events:
            _btn.append(reply_btn_delete)
            _events = f"📅 События на <b>{formatted_date}</b>:\n{events}"
        else:
            _events = f"📅 Вы выбрали дату: <b>{formatted_date}</b>"

        reply_markup = InlineKeyboardMarkup([_btn])
        await query.edit_message_text(text=_events, reply_markup=reply_markup, parse_mode="HTML")

    elif data == "cal_ignore":
        pass
