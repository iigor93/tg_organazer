import logging
import os
from datetime import date, time

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, Message, ReplyKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    PollAnswerHandler,
    PollHandler,
    filters,
)

from datetime_selector import MONTH_NAMES, generate_calendar, generate_time_selector
from models import User

load_dotenv(".env")


TOKEN = os.getenv("TG_BOT_TOKEN")


user_state = {717923644: User(telegram_id=717923644)}
awaiting_event_description = {}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("start")

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
    logger.info("handle_location")

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
    logger.info("handle_skip")

    user = update.effective_user
    logger.info(f"Пользователь {user.id} ({user.first_name}) пропустил геолокацию")

    await update.message.reply_text("Ок, продолжим без геолокации.")
    await show_main_menu(update.message)


async def show_main_menu(message: Message) -> None:
    logger.info("show_main_menu")

    keyboard = [["📅 Показать календарь"], ["🗓 Ближайшие события"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await message.reply_text("Выберите действие:", reply_markup=reply_markup)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("handle_text")

    text = update.message.text

    await_description = awaiting_event_description.get(update.effective_user.id)

    if await_description:
        awaiting_event_description.pop(update.effective_user.id)
        day = 23
        month = 12
        year = 2025
        formatted_date = f"{day} {MONTH_NAMES[int(month) - 1]} {year} года"
        text = f"Создать событие на {formatted_date}"

        start_btn = InlineKeyboardButton("Начало", callback_data=f"create_event_start_{year}_{month}_{day}")
        stop_btn = InlineKeyboardButton("Окончание", callback_data=f"create_event_stop_{year}_{month}_{day}")
        description_btn = InlineKeyboardButton("Описание", callback_data=f"create_event_description_{year}_{month}_{day}")
        recurrent_btn = InlineKeyboardButton("Повтор", callback_data=f"create_event_recurrent_{year}_{month}_{day}")
        participants_btn = InlineKeyboardButton("Участники", callback_data=f"create_event_participants_{year}_{month}_{day}")

        reply_markup = InlineKeyboardMarkup([[start_btn, stop_btn], [description_btn], [recurrent_btn], [participants_btn]])

        await update.message.reply_text(
            text,
            reply_markup=reply_markup,
            parse_mode="MarkdownV2",
        )

    elif text == "📅 Показать календарь":
        await show_calendar(update, context)
    elif text == "🗓 Ближайшие события":
        await show_upcoming_events(update, context)
    else:
        await update.message.reply_text("Используйте кнопки для навигации.")


async def show_upcoming_events(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("show_upcoming_events")

    user_id = update.effective_user.id

    local_user = user_state[user_id]
    _events = local_user.get_events()
    # await update.message.reply_text("Функция 'Ближайшие события' в разработке 🚧")
    await update.message.reply_text(_events)


async def show_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("show_calendar")

    today = date.today()
    reply_markup = generate_calendar(today.year, today.month)

    await update.message.reply_text(
        "📅 Выберите дату события:",
        reply_markup=reply_markup,
        parse_mode="MarkdownV2",
    )


async def handle_time_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("handle_time_callback")

    query = update.callback_query
    await query.answer()

    data = query.data

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
    logger.info("handle_calendar_callback")
    query = update.callback_query
    await query.answer()

    data = query.data
    user_id = query.from_user.id
    local_user = user_state[user_id]

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

        formatted_date = f"{day} {MONTH_NAMES[month - 1]} {year} года"
        _events = f"✅ Вы выбрали дату: {formatted_date}\n\n{local_user.get_events()}"

        reply_btn_create = InlineKeyboardButton("Создать событие", callback_data=f"create_event_begin_{year}_{month}_{day}")
        reply_btn_delete = InlineKeyboardButton("Удалить событие", callback_data=f"delete_event_{year}_{month}_{day}")
        reply_markup = InlineKeyboardMarkup([[reply_btn_create, reply_btn_delete]])
        await query.edit_message_text(text=_events, reply_markup=reply_markup)

    # elif data.startswith("cal_create_event_"):
    #     _, _, year_str, month_str, day_str = data.split("_")
    #     local_user.events.append(Event(title="Событие", event_datetime=f"{day_str}.{month_str}.{year_str}", recurrent="no"))
    #
    #     reply_markup = generate_time_selector()
    #
    #     await query.message.reply_text(text="Укажите время начала события", reply_markup=reply_markup)

    elif data == "cal_ignore":
        pass


async def handle_create_event_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("handle_create_event_callback")
    query = update.callback_query
    await query.answer()
    data = query.data
    _, _, _, year, month, day = data.split("_")

    if data.startswith("create_event_begin_"):
        formatted_date = f"{day} {MONTH_NAMES[int(month) - 1]} {year} года"
        text = f"Создать событие на {formatted_date}"

        start_btn = InlineKeyboardButton("Начало", callback_data=f"create_event_start_{year}_{month}_{day}")
        stop_btn = InlineKeyboardButton("Окончание", callback_data=f"create_event_stop_{year}_{month}_{day}")
        description_btn = InlineKeyboardButton("Описание", callback_data=f"create_event_description_{year}_{month}_{day}")
        recurrent_btn = InlineKeyboardButton("Повтор", callback_data=f"create_event_recurrent_{year}_{month}_{day}")
        participants_btn = InlineKeyboardButton("Участники", callback_data=f"create_event_participants_{year}_{month}_{day}")

        reply_markup = InlineKeyboardMarkup([[start_btn, stop_btn], [description_btn], [recurrent_btn], [participants_btn]])

        await query.edit_message_text(text=text, reply_markup=reply_markup)

    elif data.startswith("create_event_start_"):
        reply_markup = generate_time_selector()
        await query.edit_message_text(text="Укажите время начала события", reply_markup=reply_markup)

    elif data.startswith("create_event_stop_"):
        reply_markup = generate_time_selector()
        await query.edit_message_text(text="Укажите время окончания события", reply_markup=reply_markup)

    elif data.startswith("create_event_description_"):
        awaiting_event_description[update.effective_user.id] = True
        await query.edit_message_text(text="Опиши, что будет в событии")

    elif data.startswith("create_event_recurrent_"):
        never_btn = InlineKeyboardButton("Никогда", callback_data=f"create_event_begin_{year}_{month}_{day}")
        daily_btn = InlineKeyboardButton("Ежедневно", callback_data=f"create_event_begin_{year}_{month}_{day}")
        weekly_btn = InlineKeyboardButton("Каждую неделю", callback_data=f"create_event_begin_{year}_{month}_{day}")
        annual_btn = InlineKeyboardButton("Каждый год", callback_data=f"create_event_begin_{year}_{month}_{day}")

        reply_markup = InlineKeyboardMarkup([[never_btn], [daily_btn], [weekly_btn], [annual_btn]])
        await query.edit_message_text(text="Как часто повторять событие:", reply_markup=reply_markup)

    elif data.startswith("create_event_participants_"):
        questions = ["Вася", "Петя", "Маша"]
        # Send the poll and store the message object to reference its poll ID
        message = await context.bot.send_poll(
            chat_id=update.effective_chat.id,
            question="Добавить участников события",
            options=questions,
            is_anonymous=False,
            allows_multiple_answers=True,
        )
        logger.info(f"id опроса {message.poll.id}")
        context.user_data["poll_message_id"] = message.message_id

        # await query.edit_message_text(text="Укажите время окончания события", reply_markup=reply_markup)


async def receive_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info(f"receive_poll_answer\n{update}")
    answer = update.poll_answer
    user_id = answer.user.id
    selected_options = answer.option_ids

    logger.info(f"User {user_id} voted for options: {selected_options}")
    day = 23
    month = 12
    year = 2025
    formatted_date = f"{day} {MONTH_NAMES[int(month) - 1]} {year} года"
    text = f"Создать событие на {formatted_date}"

    start_btn = InlineKeyboardButton("Начало", callback_data=f"create_event_start_{year}_{month}_{day}")
    stop_btn = InlineKeyboardButton("Окончание", callback_data=f"create_event_stop_{year}_{month}_{day}")
    description_btn = InlineKeyboardButton("Описание", callback_data=f"create_event_description_{year}_{month}_{day}")
    recurrent_btn = InlineKeyboardButton("Повтор", callback_data=f"create_event_recurrent_{year}_{month}_{day}")
    participants_btn = InlineKeyboardButton("Участники", callback_data=f"create_event_participants_{year}_{month}_{day}")

    reply_markup = InlineKeyboardMarkup([[start_btn, stop_btn], [description_btn], [recurrent_btn], [participants_btn]])

    # poll_message_id = context.user_data.get('poll_message_id')
    # if poll_message_id:
    #     await context.bot.delete_message(chat_id=user_id, message_id=poll_message_id)
    #
    await context.bot.send_message(
        chat_id=user_id,
        text=text,
        reply_markup=reply_markup,
    )


async def receive_poll_close(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("receive_poll_close")
    poll = update.poll
    if poll.is_closed:
        logger.info(f"Poll '{poll.question}' closed. Total voters: {poll.total_voter_count}")
        day = 23
        month = 12
        year = 2025
        formatted_date = f"{day} {MONTH_NAMES[int(month) - 1]} {year} года"
        text = f"Создать событие на {formatted_date}"

        start_btn = InlineKeyboardButton("Начало", callback_data=f"create_event_start_{year}_{month}_{day}")
        stop_btn = InlineKeyboardButton("Окончание", callback_data=f"create_event_stop_{year}_{month}_{day}")
        description_btn = InlineKeyboardButton("Описание", callback_data=f"create_event_description_{year}_{month}_{day}")
        recurrent_btn = InlineKeyboardButton("Повтор", callback_data=f"create_event_recurrent_{year}_{month}_{day}")
        participants_btn = InlineKeyboardButton("Участники", callback_data=f"create_event_participants_{year}_{month}_{day}")

        reply_markup = InlineKeyboardMarkup([[start_btn, stop_btn], [description_btn], [recurrent_btn], [participants_btn]])

        await update.message.reply_text(
            text,
            reply_markup=reply_markup,
            parse_mode="MarkdownV2",
        )


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

    # Время и календарь
    application.add_handler(CallbackQueryHandler(handle_calendar_callback, pattern="^cal_"))
    application.add_handler(CallbackQueryHandler(handle_time_callback, pattern="^time_"))

    # Создание\удаление события
    application.add_handler(CallbackQueryHandler(handle_create_event_callback, pattern="^create_event_"))
    # application.add_handler(CallbackQueryHandler(handle_delete_event_callback, pattern="^delete_event_"))

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    application.add_handler(CallbackQueryHandler(all_callbacks))
    application.add_handler(PollAnswerHandler(receive_poll_answer))
    application.add_handler(PollHandler(receive_poll_close))

    logger.info("Бот запущен...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S%z", level=logging.INFO)
    logger = logging.getLogger(__name__)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    main()
