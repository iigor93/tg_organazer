import datetime
import logging
from datetime import date, time

import telegram
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from config import MONTH_NAMES, TOKEN
from database.db_controller import db_controller
from entities import Event, Recurrent, TgUser

logger = logging.getLogger(__name__)


def generate_time_selector(hours: int = 12, minutes: int = 0, time_type: str = "") -> InlineKeyboardMarkup:
    hours = hours % 24
    _show_min = minutes
    minutes = (minutes // 10) * 10  # Округляем до шага 10 минут
    minutes = minutes % 60

    keyboard = [
        [
            InlineKeyboardButton("▲", callback_data=f"time_hour_up_{time_type}_{hours}_{minutes}"),
            InlineKeyboardButton("▲", callback_data=f"time_minute_up_{time_type}_{hours}_{minutes}"),
        ],
        [
            InlineKeyboardButton(f"{hours:02d}", callback_data=f"time_hour_set_{time_type}"),
            InlineKeyboardButton(f"{_show_min:02d}", callback_data=f"time_minute_set_{time_type}"),
        ],
        [
            InlineKeyboardButton("▼️", callback_data=f"time_hour_down_{time_type}_{hours}_{minutes}"),
            InlineKeyboardButton("▼️", callback_data=f"time_minute_down_{time_type}_{hours}_{minutes}"),
        ],
        [InlineKeyboardButton("✅ OK", callback_data="create_event_begin_")],
    ]

    return InlineKeyboardMarkup(keyboard)


async def handle_participants_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("handle_participants_callback")

    query = update.callback_query
    await query.answer()
    event: Event | None = context.chat_data.get("event")

    tg_id_income = int(query.data.split("_")[1])
    is_active = context.chat_data.get("participants_status", {}).get(tg_id_income, True)
    if not is_active:
        return

    if tg_id_income in event.participants:
        event.participants.remove(tg_id_income)
    else:
        event.participants.append(tg_id_income)

    context.chat_data["event"] = event

    list_btn = []
    for tg_id, name in event.all_user_participants.items():
        is_active = context.chat_data.get("participants_status", {}).get(tg_id, True)
        if not is_active:
            name = f"{name} (не в боте)"
        elif tg_id in event.participants:
            name = f"{name} ✅"
        list_btn.append([InlineKeyboardButton(name, callback_data=f"participants_{tg_id}")])

    list_btn.append([InlineKeyboardButton("✅ OK", callback_data="create_event_begin_")])

    reply_markup = InlineKeyboardMarkup(list_btn)
    await query.edit_message_text(text="Добавь пользователей к событию", reply_markup=reply_markup)


async def handle_time_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("handle_time_callback")

    query = update.callback_query
    await query.answer()

    if query.message:
        context.chat_data["time_picker_message_id"] = query.message.message_id
        context.chat_data["time_picker_chat_id"] = query.message.chat_id

    event: Event | None = context.chat_data.get("event")

    data = query.data
    hours = 12
    minutes = 0

    if data.startswith("time_hour_set_"):
        _, _, _, time_type = data.split("_")
        message = await query.message.reply_text("Введите часы (0-23):")
        context.chat_data["await_time_input"] = {
            "field": "hour",
            "time_type": time_type,
            "prompt_message_id": message.message_id,
            "prompt_chat_id": message.chat_id,
        }
        context.chat_data["time_input_prompt_message_id"] = message.message_id
        context.chat_data["time_input_prompt_chat_id"] = message.chat_id
        return

    if data.startswith("time_minute_set_"):
        _, _, _, time_type = data.split("_")
        message = await query.message.reply_text("Введите минуты (0-59):")
        context.chat_data["await_time_input"] = {
            "field": "minute",
            "time_type": time_type,
            "prompt_message_id": message.message_id,
            "prompt_chat_id": message.chat_id,
        }
        context.chat_data["time_input_prompt_message_id"] = message.message_id
        context.chat_data["time_input_prompt_chat_id"] = message.chat_id
        return

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

        context.chat_data["event"] = event

    logger.info(f"*** time picker: {event}")

    # Обновляем клавиатуру с новым временем
    reply_markup = generate_time_selector(hours=hours, minutes=minutes, time_type=time_type)

    await query.edit_message_reply_markup(reply_markup=reply_markup)


def get_event_constructor(
    event: Event, year: int | None = None, month: int | None = None, day: int | None = None, has_participants: bool = False
):
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
    text = f"✍️ Создать событие на *{formatted_date}* \n\n\\* \\- поля обязательные для заполнения"

    start_btn = InlineKeyboardButton(text=start_time, callback_data=f"create_event_start_{year}_{month}_{day}")
    stop_btn = InlineKeyboardButton(text=stop_time, callback_data=f"create_event_stop_{year}_{month}_{day}")
    description_btn = InlineKeyboardButton(text=description, callback_data=f"create_event_description_{year}_{month}_{day}")
    recurrent_btn = InlineKeyboardButton(text=recurrent, callback_data=f"create_event_recurrent_{year}_{month}_{day}")
    participants_btn = InlineKeyboardButton(text=participants, callback_data=f"create_event_participants_{year}_{month}_{day}")
    buttons = [[start_btn, stop_btn], [description_btn], [recurrent_btn]]

    if has_participants:
        buttons.append([participants_btn])

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

    user = update.effective_chat
    tg_user = TgUser.model_validate(user)
    db_user = await db_controller.save_update_user(tg_user=tg_user)
    logger.info(f"*** DB user: {db_user}")

    event: Event | None = context.chat_data.get("event")
    if not event:
        event = Event(event_date=datetime.datetime.now().date(), tg_id=update.effective_chat.id)
        context.chat_data["event"] = event

    year, month, day = event.get_date()

    logger.info(f"* EVENT: {event}")

    if data.startswith("create_event_begin_"):
        try:
            _, _, _, year, month, day = data.split("_")
            event = Event(event_date=datetime.datetime.strptime(f"{year}-{month}-{day}", "%Y-%m-%d"), tg_id=update.effective_chat.id)
            context.chat_data["event"] = event
        except:  # noqa
            ...

        participants = await db_controller.get_participants_with_status(tg_id=user.id, include_inactive=True)
        context.chat_data["participants_status"] = {tg_id: is_active for tg_id, (_, is_active) in participants.items()}
        context.chat_data["event"].all_user_participants = {tg_id: name for tg_id, (name, _) in participants.items()}

        has_participants = bool(event.all_user_participants)
        text, reply_markup = get_event_constructor(event=event, year=year, month=month, day=day, has_participants=has_participants)
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="MarkdownV2")

    elif data.startswith("create_event_start_"):
        hours = 12
        minutes = 0
        if event and event.start_time:
            hours = event.start_time.hour
            minutes = event.start_time.minute
        elif event and not event.start_time:
            event.start_time = datetime.datetime.strptime("12:00", "%H:%M").time()
            context.chat_data["event"] = event

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
            context.chat_data["event"] = event

        if event.start_time:
            hours = event.start_time.hour
            minutes = event.start_time.minute
            hours = int(hours)
            minutes = int(minutes)

            event.stop_time = datetime.datetime.strptime(f"{hours:02d}:{minutes:02d}", "%H:%M").time()
            context.chat_data["event"] = event

            text += f"\n\n (уже задано время начала события {hours:02d}:{minutes:02d})"

        reply_markup = generate_time_selector(hours=int(hours), minutes=int(minutes), time_type="stop")
        await query.edit_message_text(text=text, reply_markup=reply_markup)

    elif data.startswith("create_event_description_"):
        # context.chat_data["await_event_description"] = True
        # await query.message.reply_text(text="Опиши, что будет в событии:")
        message = await query.message.reply_text(text="Опиши, что будет в событии:")
        context.chat_data["await_event_description"] = {
            "prompt_message_id": message.message_id,
            "prompt_chat_id": message.chat_id,
        }

    elif data.startswith("create_event_save_recurrent_"):
        _, _, _, _, recurrent = data.split("_")
        event.recurrent = Recurrent(recurrent)
        context.chat_data["event"] = event

        has_participants = bool(event.all_user_participants)
        text, reply_markup = get_event_constructor(event=event, year=year, month=month, day=day, has_participants=has_participants)
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="MarkdownV2")

    elif data.startswith("create_event_recurrent_"):
        list_btn = []
        for item in Recurrent.get_all_names():
            list_btn.append([InlineKeyboardButton(item[0], callback_data=f"create_event_save_recurrent_{item[1]}")])

        reply_markup = InlineKeyboardMarkup(list_btn)
        await query.edit_message_text(text="Как часто повторять событие:", reply_markup=reply_markup)

    elif data.startswith("create_event_participants_"):
        list_btn = []
        for tg_id, name in event.all_user_participants.items():
            is_active = context.chat_data.get("participants_status", {}).get(tg_id, True)
            if not is_active:
                name = f"{name} (не в боте)"
            elif tg_id in event.participants:
                name = f"{name} ✅"
            list_btn.append([InlineKeyboardButton(name, callback_data=f"participants_{tg_id}")])

        list_btn.append([InlineKeyboardButton("✅ OK", callback_data="create_event_begin_")])

        reply_markup = InlineKeyboardMarkup(list_btn)
        await query.edit_message_text(text="Добавь пользователей к событию", reply_markup=reply_markup)
    elif data.startswith("create_event_save_to_db"):
        event_id = await db_controller.save_event(event=event, tz_name=db_user.time_zone)
        context.chat_data.pop("event")
        year, month, day = event.get_date()
        events = await db_controller.get_current_day_events_by_user(
            user_id=user.id, month=month, year=year, day=day, tz_name=db_user.time_zone
        )
        formatted_date = f"{day:02d}.{month:02d}.{year}"

        if events:
            text = f"Создано новое событие <b>{formatted_date}</b>:\n{events}"
        else:
            text = f"Нет событий <b>{formatted_date}</b>"

        from handlers.cal import generate_calendar  # local import to avoid circular dependency

        calendar_markup = await generate_calendar(year=year, month=month, user_id=user.id, tz_name=db_user.time_zone)
        action_row = [
            InlineKeyboardButton(
                f"✍️ Создать событие на {day:02d}.{month:02d}.{year}", callback_data=f"create_event_begin_{year}_{month}_{day}"
            )
        ]
        delete_row = []
        if events:
            delete_row.append(InlineKeyboardButton("🗑 Удалить событие", callback_data=f"delete_event_{year}_{month}_{day}"))
        reply_markup = InlineKeyboardMarkup(list(calendar_markup.inline_keyboard) + [action_row] + [delete_row])
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="HTML")

        if event.participants:
            bot = telegram.Bot(token=TOKEN)

            text = (
                f"{str(update.effective_chat.first_name).title()} добавил событие"
                f"\n{event.event_date.day}.{event.event_date.month:02d}.{event.event_date.year} "
                f"время {event.start_time.strftime('%H:%M')}-{event.stop_time.strftime('%H:%M') if event.stop_time else ''}"
                f"\n{event.description}"
            )

            for user in event.participants:
                new_event_id = await db_controller.resave_event_to_participant(event_id=event_id, user_id=user)
                creator_id = update.effective_user.id if update.effective_user else None
                cancel_data = f"create_participant_event_cancel_{new_event_id}"
                if creator_id:
                    cancel_data = f"{cancel_data}_{creator_id}"
                btn = [[InlineKeyboardButton("Не добавлять", callback_data=cancel_data)]]
                reply_markup = InlineKeyboardMarkup(btn)
                await bot.send_message(chat_id=user, text=text, reply_markup=reply_markup)


async def show_upcoming_events(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("show_upcoming_events")

    user = update.effective_chat
    tg_user = TgUser.model_validate(user)
    db_user = await db_controller.save_update_user(tg_user=tg_user)
    logger.info(f"*** DB user: {db_user}")

    events = await db_controller.get_nearest_events(user_id=user.id, tz_name=db_user.time_zone)

    if events:
        list_events = ["Ближайшие события:"]
        for _event in events:
            list_events.append(f"<b>{list(_event.keys())[0].strftime('%d-%m-%Y %H:%M')}</b> - {list(_event.values())[0]}")
        text = "\n".join(list_events)
    else:
        text = "Ближайшие события не найдены"

    await update.message.reply_text(text, parse_mode="HTML")


async def handle_delete_event_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("handle_delete_event_callback")
    query = update.callback_query
    await query.answer()

    user = update.effective_chat
    tg_user = TgUser.model_validate(user)
    db_user = await db_controller.save_update_user(tg_user=tg_user)
    logger.info(f"*** DB user: {db_user}")
    # user_id = update.effective_chat.id
    data = query.data

    if "_id_" in data:
        _, _, _, db_id, year_str, month_str, day_str = data.split("_")
        year = int(year_str)
        month = int(month_str)
        day = int(day_str)

        await db_controller.delete_event_by_id(event_id=db_id, tz_name=db_user.time_zone)

        events = await db_controller.get_current_day_events_by_user(
            user_id=user.id, month=month, year=year, day=day, tz_name=db_user.time_zone
        )
        formatted_date = f"{day:02d}.{month:02d}.{year}"

        header = "Удалено одно событие"
        no_events = "Нет событий"

        if events:
            text = f"{header}\n\n<b>{formatted_date}</b>\n{events}"
        else:
            text = f"{header}\n\n<b>{formatted_date}</b>\n{no_events}"

        from handlers.cal import generate_calendar  # local import to avoid circular dependency

        calendar_markup = await generate_calendar(year=year, month=month, user_id=user.id, tz_name=db_user.time_zone)
        action_row = [
            InlineKeyboardButton(
                f"✍️ Создать событие на {day:02d}.{month:02d}.{year}", callback_data=f"create_event_begin_{year}_{month}_{day}"
            )
        ]
        delete_row = []
        if events:
            delete_row.append(InlineKeyboardButton("🗑 Удалить событие", callback_data=f"delete_event_{year}_{month}_{day}"))
        reply_markup = InlineKeyboardMarkup(list(calendar_markup.inline_keyboard) + [action_row] + [delete_row])
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="HTML")
        return

    elif "_recurDay_" in data:
        _, _, _, db_id, year_str, month_str, day_str = data.split("_")
        year = int(year_str)
        month = int(month_str)
        day = int(day_str)
        await db_controller.create_cancel_event(event_id=int(db_id), cancel_date=date.fromisoformat(f"{year}-{month:02d}-{day:02d}"))

        events = await db_controller.get_current_day_events_by_user(
            user_id=user.id, month=month, year=year, day=day, tz_name=db_user.time_zone
        )
        formatted_date = f"{day:02d}.{month:02d}.{year}"

        header = "Удалено одно событие"
        no_events = "Нет событий"

        if events:
            text = f"{header}\n\n<b>{formatted_date}</b>\n{events}"
        else:
            text = f"{header}\n\n<b>{formatted_date}</b>\n{no_events}"

        from handlers.cal import generate_calendar  # local import to avoid circular dependency

        calendar_markup = await generate_calendar(year=year, month=month, user_id=user.id, tz_name=db_user.time_zone)
        action_row = [
            InlineKeyboardButton(
                f"✍️ Создать событие на {day:02d}.{month:02d}.{year}", callback_data=f"create_event_begin_{year}_{month}_{day}"
            )
        ]
        delete_row = []
        if events:
            delete_row.append(InlineKeyboardButton("🗑 Удалить событие", callback_data=f"delete_event_{year}_{month}_{day}"))
        reply_markup = InlineKeyboardMarkup(list(calendar_markup.inline_keyboard) + [action_row] + [delete_row])
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="HTML")

    elif "_recurrent_" in data:
        _, _, _, db_id, year, month, day = data.split("_")

        formatted_date = f"{day} {(MONTH_NAMES[int(month) - 1]).title()} {year} года"

        text = f"Событие повторяющееся. \nОтмените событие на дату {formatted_date} или удалите его полностью"
        reply_markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        f"🗑 Удалить на дату {day} {(MONTH_NAMES[int(month) - 1]).title()} {year} года",
                        callback_data=f"delete_event_recurDay_{db_id}_{year}_{month}_{day}",
                    )
                ],
                [InlineKeyboardButton("🗑 Удалить полностью", callback_data=f"delete_event_id_{db_id}_{year}_{month}_{day}")],
                [InlineKeyboardButton("Отмена", callback_data=f"cal_select_{year}_{month}_{day}")],
            ]
        )
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="HTML")

        ...
    else:  # конструктор событий для удаления
        _, _, year, month, day = data.split("_")
        year = int(year)
        month = int(month)
        day = int(day)

        events = await db_controller.get_current_day_events_by_user(
            user_id=user.id, month=month, year=year, day=day, deleted=True, tz_name=db_user.time_zone
        )

        formatted_date = f"{day} {(MONTH_NAMES[month - 1]).title()} {year} года"
        text = f"<b>{formatted_date}</b>\nВыберете события для удаления:"
        list_btn = []
        for _event in events:
            btn_text = _event[0]
            if not _event[2]:
                callback_data = f"delete_event_recurrent_{_event[1]}_{year}_{month}_{day}"
                btn_text += "*"
            else:
                callback_data = f"delete_event_id_{_event[1]}_{year}_{month}_{day}"
            list_btn.append([InlineKeyboardButton(btn_text, callback_data=callback_data)])

        list_btn.append([InlineKeyboardButton("Отмена", callback_data=f"cal_select_{year}_{month}_{day}")])

        reply_markup = InlineKeyboardMarkup(list_btn)
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="HTML")


async def handle_event_participants_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("handle_event_participants_callback")
    query = update.callback_query
    data = query.data

    user = update.effective_chat
    tg_user = TgUser.model_validate(user)
    db_user = await db_controller.save_update_user(tg_user=tg_user)
    logger.info(f"*** DB user: {db_user}")

    if "cancel" in data:
        parts = data.split("_")
        event_id = parts[4]
        creator_id = None
        if len(parts) > 5:
            try:
                creator_id = int(parts[5])
            except ValueError:
                creator_id = None

        _, event_info = await db_controller.delete_event_by_id(event_id=event_id, tz_name=db_user.time_zone)
        await query.edit_message_text(text="Событие не добавлено в календарь.")

        if creator_id and update.effective_user and creator_id != update.effective_user.id:
            user_name = update.effective_user.full_name or update.effective_user.first_name or "Участник"
            text = f"Участник {user_name} отказался от участия в событии: {event_info}"
            try:
                await context.bot.send_message(chat_id=creator_id, text=text)
            except Exception:  # noqa: BLE001
                logger.exception("Failed to notify event creator about отказ")
        return
