from calendar import monthrange
from datetime import date

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

MONTH_NAMES = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]


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


def generate_time_selector(hours: int = 12, minutes: int = 0) -> InlineKeyboardMarkup:
    hours = hours % 24
    minutes = (minutes // 10) * 10  # Округляем до шага 10 минут
    minutes = minutes % 60

    keyboard = [
        [
            InlineKeyboardButton("▲", callback_data=f"time_hour_up_{hours}_{minutes}"),
            InlineKeyboardButton("▲", callback_data=f"time_minute_up_{hours}_{minutes}"),
        ],
        [
            InlineKeyboardButton(f"{hours:02d}", callback_data="time_ignore"),
            InlineKeyboardButton(f"{minutes:02d}", callback_data="time_ignore"),
        ],
        [
            InlineKeyboardButton("▼️", callback_data=f"time_hour_down_{hours}_{minutes}"),
            InlineKeyboardButton("▼️", callback_data=f"time_minute_down_{hours}_{minutes}"),
        ],
        # [InlineKeyboardButton("✅ OK", callback_data=f"time_confirm_{hours}_{minutes}")],
        [InlineKeyboardButton("✅ OK", callback_data="create_event_begin_2025_01_01")],
    ]

    return InlineKeyboardMarkup(keyboard)
