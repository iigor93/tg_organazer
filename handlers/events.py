import datetime
import logging
from datetime import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from config import MONTH_NAMES
from database.db_controller import db_controller
from entities import Event, Recurrent

logger = logging.getLogger(__name__)


def generate_time_selector(hours: int = 12, minutes: int = 0, time_type: str = "") -> InlineKeyboardMarkup:
    hours = hours % 24
    minutes = (minutes // 10) * 10  # Округляем до шага 10 минут
    minutes = minutes % 60

    keyboard = [
        [
            InlineKeyboardButton("▲", callback_data=f"time_hour_up_{time_type}_{hours}_{minutes}"),
            InlineKeyboardButton("▲", callback_data=f"time_minute_up_{time_type}_{hours}_{minutes}"),
        ],
        [
            InlineKeyboardButton(f"{hours:02d}", callback_data="time_ignore"),
            InlineKeyboardButton(f"{minutes:02d}", callback_data="time_ignore"),
        ],
        [
            InlineKeyboardButton("▼️", callback_data=f"time_hour_down_{time_type}_{hours}_{minutes}"),
            InlineKeyboardButton("▼️", callback_data=f"time_minute_down_{time_type}_{hours}_{minutes}"),
        ],
        # [InlineKeyboardButton("✅ OK", callback_data=f"time_confirm_{time_type}_{hours}_{minutes}")],
        [InlineKeyboardButton("✅ OK", callback_data="create_event_begin_")],
    ]

    return InlineKeyboardMarkup(keyboard)


async def handle_participants_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("handle_participants_callback")

    query = update.callback_query
    await query.answer()

    event: Event | None = context.user_data.get("event")

    tg_id_income = int(query.data.split("_")[1])

    if tg_id_income in event.participants:
        event.participants.remove(tg_id_income)
    else:
        event.participants.append(tg_id_income)

    context.user_data["event"] = event

    participants = {1: "Вася", 2: "Петя", 3: "Маша"}  # todo брать из юзера
    list_btn = []
    for tg_id, name in participants.items():
        if tg_id in event.participants:
            name = f"{name} ✅"
        else:
            name = name
        list_btn.append([InlineKeyboardButton(name, callback_data=f"participants_{tg_id}")])

    list_btn.append([InlineKeyboardButton("✅ OK", callback_data="create_event_begin_")])

    reply_markup = InlineKeyboardMarkup(list_btn)
    await query.edit_message_text(text="Добавь пользователей к событию", reply_markup=reply_markup)


async def handle_time_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("handle_time_callback")

    query = update.callback_query
    await query.answer()

    event: Event | None = context.user_data.get("event")

    data = query.data
    hours = 12
    minutes = 0

    if data.startswith("time_hour_up_"):
        _, _, _, _, hours_str, minutes_str = data.split("_")
        hours = (int(hours_str) + 1) % 24
        minutes = int(minutes_str)

    elif data.startswith("time_hour_down_"):
        _, _, _, _, hours_str, minutes_str = data.split("_")
        hours = (int(hours_str) - 1) % 24
        minutes = int(minutes_str)

    elif data.startswith("time_minute_up_"):
        _, _, _, _, hours_str, minutes_str = data.split("_")
        hours = int(hours_str)
        minutes = (int(minutes_str) + 10) % 60

    elif data.startswith("time_minute_down_"):
        _, _, _, _, hours_str, minutes_str = data.split("_")
        hours = int(hours_str)
        minutes = (int(minutes_str) - 10) % 60

    selected_time = time(hours, minutes)
    time_type = ""
    if event:
        if "start" in data:
            event.start_time = selected_time
            time_type = "start"
        elif "stop" in data:
            event.stop_time = selected_time
            time_type = "stop"

        context.user_data["event"] = event

    logger.info(f"*** time picker: {event}")

    # Обновляем клавиатуру с новым временем
    reply_markup = generate_time_selector(hours=hours, minutes=minutes, time_type=time_type)

    await query.edit_message_reply_markup(reply_markup=reply_markup)


def get_event_constructor(event: Event, year: int | None = None, month: int | None = None, day: int | None = None):
    start_time = "Начало *"
    stop_time = "Окончание"
    description = "Описание *"
    recurrent = "Повтор"
    participants = "Участники"
    show_create_btn = False

    if event:
        if not year:
            year, month, day = event.get_date()

        start_time = event.start_time.strftime("%H:%M") if event.start_time else start_time
        stop_time = event.stop_time.strftime("%H:%M") if event.stop_time else stop_time
        description = event.description if event.description else description
        description = description[:20] + "..." if len(str(description)) > 20 else description
        recurrent = f"{recurrent}: {event.recurrent.get_name()}"
        len_participants = len(event.participants) if event.participants else None
        if len_participants:
            participants += f" ({len_participants})"

        if event.start_time and event.description:
            show_create_btn = True

    formatted_date = f"{day} {(MONTH_NAMES[int(month) - 1]).title()} {year} года"
    text = f"Создать событие на *{formatted_date}* \n\n\\* \\- поля обязательные для заполнения"

    start_btn = InlineKeyboardButton(text=start_time, callback_data=f"create_event_start_{year}_{month}_{day}")
    stop_btn = InlineKeyboardButton(text=stop_time, callback_data=f"create_event_stop_{year}_{month}_{day}")
    description_btn = InlineKeyboardButton(text=description, callback_data=f"create_event_description_{year}_{month}_{day}")
    recurrent_btn = InlineKeyboardButton(text=recurrent, callback_data=f"create_event_recurrent_{year}_{month}_{day}")
    participants_btn = InlineKeyboardButton(text=participants, callback_data=f"create_event_participants_{year}_{month}_{day}")
    buttons = [[start_btn, stop_btn], [description_btn], [recurrent_btn], [participants_btn]]

    # if user.participants:  # todo тут будем проверять есть ли у юзера вообще связные люди
    #     buttons.append([participants_btn])

    if show_create_btn:
        create_btn = InlineKeyboardButton(text="💾 Сохранить событие", callback_data="create_event_save_to_db")
        buttons.append([create_btn])

    reply_markup = InlineKeyboardMarkup(buttons)

    return text, reply_markup


async def handle_create_event_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("handle_create_event_callback")
    query = update.callback_query
    await query.answer()
    data = query.data

    event: Event | None = context.user_data.get("event")
    if not event:
        event = Event(event_date=datetime.datetime.now().date(), tg_id=update.effective_user.id)
        context.user_data["event"] = event

    year, month, day = event.get_date()

    logger.info(f"* EVENT: {event}")

    if data.startswith("create_event_begin_"):
        try:
            _, _, _, year, month, day = data.split("_")
            event = Event(event_date=datetime.datetime.strptime(f"{year}-{month}-{day}", "%Y-%m-%d"), tg_id=update.effective_user.id)
            context.user_data["event"] = event
        except:  # noqa
            ...

        text, reply_markup = get_event_constructor(event=event, year=year, month=month, day=day)
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="MarkdownV2")

    elif data.startswith("create_event_start_"):
        hours = 12
        minutes = 0
        if event and event.start_time:
            hours = event.start_time.hour
            minutes = event.start_time.minute
        elif event and not event.start_time:
            event.start_time = datetime.datetime.strptime("12:00", "%H:%M").time()
            context.user_data["event"] = event

        reply_markup = generate_time_selector(hours=int(hours), minutes=int(minutes), time_type="start")

        await query.edit_message_text(text="Укажите время начала события", reply_markup=reply_markup)

    elif data.startswith("create_event_stop_"):
        text = "Укажите время окончания события"
        hours = 12
        minutes = 0
        if event and event.stop_time:
            hours = event.stop_time.hour
            minutes = event.stop_time.minute
        elif event and not event.stop_time:
            event.stop_time = datetime.datetime.strptime("12:00", "%H:%M").time()
            context.user_data["event"] = event

        if event.start_time:
            hours = event.start_time.hour
            minutes = event.start_time.minute
            hours = int(hours)
            minutes = int(minutes)

            event.stop_time = datetime.datetime.strptime(f"{hours:02d}:{minutes:02d}", "%H:%M").time()
            context.user_data["event"] = event

            text += f"\n\n (уже задано время начала события {hours:02d}:{minutes:02d})"

        reply_markup = generate_time_selector(hours=int(hours), minutes=int(minutes), time_type="stop")
        await query.edit_message_text(text=text, reply_markup=reply_markup)

    elif data.startswith("create_event_description_"):
        context.user_data["await_event_description"] = True
        await query.message.reply_text(text="Опиши, что будет в событии:")

    elif data.startswith("create_event_save_recurrent_"):
        _, _, _, _, recurrent = data.split("_")
        event.recurrent = Recurrent(recurrent)
        context.user_data["event"] = event

        text, reply_markup = get_event_constructor(event=event, year=year, month=month, day=day)
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="MarkdownV2")

    elif data.startswith("create_event_recurrent_"):
        list_btn = []
        for item in Recurrent.get_all_names():
            list_btn.append([InlineKeyboardButton(item[0], callback_data=f"create_event_save_recurrent_{item[1]}")])

        reply_markup = InlineKeyboardMarkup(list_btn)
        await query.edit_message_text(text="Как часто повторять событие:", reply_markup=reply_markup)

    elif data.startswith("create_event_participants_"):
        participants = {1: "Вася", 2: "Петя", 3: "Маша"}  # todo брать из юзера
        list_btn = []
        for tg_id, name in participants.items():
            if tg_id in event.participants:
                name = f"{name} ✅"
            list_btn.append([InlineKeyboardButton(name, callback_data=f"participants_{tg_id}")])

        list_btn.append([InlineKeyboardButton("✅ OK", callback_data="create_event_begin_")])

        reply_markup = InlineKeyboardMarkup(list_btn)
        await query.edit_message_text(text="Добавь пользователей к событию", reply_markup=reply_markup)
    elif data.startswith("create_event_save_to_db"):
        await db_controller.save_event(event=event)

        participants = ",".join(str(item) for item in event.participants) if event.participants else "..."
        text = (
            "<b>Событие успешно сохранено!</b>"
            f"\n\nДата: <b>{event.get_format_date()}</b>"
            f"\nВремя начала: <b>{event.start_time.strftime('%H:%M') if event.start_time else '...'}</b>"
            f"\nВремя окончания: <b>{event.stop_time.strftime('%H:%M') if event.stop_time else '...'}</b>"
            f"\nОписание: <b>{event.description if event.description else '...'}</b>"
            f"\nПовтор: <b>{event.recurrent.get_name() if event.recurrent else '...'}</b>"
            f"\nУчастники: <b>{participants}</b>"
        )
        context.user_data.pop("event")
        await query.edit_message_text(text=text, parse_mode="HTML")


async def show_upcoming_events(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("show_upcoming_events")
    user_id = update.effective_user.id
    events = await db_controller.get_nearest_events(user_id=user_id)

    if events:
        list_events = ["Ближайшие события:"]
        for _event in events:
            list_events.append(f"<b>{list(_event.keys())[0].strftime('%Y-%m-%d %H:%M')}</b> - {list(_event.values())[0]}")
        text = "\n".join(list_events)
    else:
        text = "Ближайшие события не найдены"

    await update.message.reply_text(text, parse_mode="HTML")


async def handle_delete_event_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("handle_delete_event_callback")
    query = update.callback_query
    await query.answer()

    await db_controller.delete_all_events_by_user(user_id=update.effective_user.id)
    await query.message.reply_text("Все события удалены 🗑️")
