import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import KeyboardButton, Message, ReplyKeyboardMarkup, Update
from telegram.ext import ContextTypes
from timezonefinder import TimezoneFinder

from database.db_controller import db_controller
from entities import TgUser

logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("start")
    context.chat_data.pop("team_participants", None)
    context.chat_data.pop("team_selected", None)
    context.chat_data.pop("event", None)
    context.chat_data.pop("participants_status", None)
    context.chat_data.pop("time_picker_message_id", None)
    context.chat_data.pop("time_picker_chat_id", None)
    context.chat_data.pop("await_time_input", None)
    context.chat_data.pop("time_input_prompt_message_id", None)
    context.chat_data.pop("time_input_prompt_chat_id", None)

    user = update.effective_chat
    tg_user = TgUser.model_validate(user)
    db_user = await db_controller.save_update_user(tg_user=tg_user)

    logger.info(f"*** DB user: {db_user}")

    keyboard = [[KeyboardButton("⏭ Пропустить")]]

    if update.effective_chat.type == "private":
        keyboard.insert(0, [KeyboardButton("📍 Поделиться геолокацией", request_location=True)])

    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

    await update.message.reply_text(
        f"Привет, {user.first_name}!\n"
        "Я бот календарь.\n"
        "Для получения событий по твоему часовому поясу, тебе нужно поделиться геолокацией?",
        reply_markup=reply_markup,
    )


async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("handle_help")
    context.chat_data.pop("team_participants", None)
    context.chat_data.pop("team_selected", None)
    context.chat_data.pop("event", None)
    context.chat_data.pop("participants_status", None)
    context.chat_data.pop("time_picker_message_id", None)
    context.chat_data.pop("time_picker_chat_id", None)
    context.chat_data.pop("await_time_input", None)
    context.chat_data.pop("time_input_prompt_message_id", None)
    context.chat_data.pop("time_input_prompt_chat_id", None)
    text = (
        "👋 Привет! Я помогу планировать дела и напоминать о событиях.\n\n"
        "📌 Основные команды:\n"
        "• /start — запуск бота\n"
        "• /team — управление участниками (удаление лишних)\n"
        "• /help — это сообщение\n\n"
        "🗓️ Календарь и события:\n"
        "1) Открой «Календарь» и выбери дату.\n"
        "2) Нажми «Создать событие».\n"
        "3) Укажи время начала/окончания и описание.\n"
        "4) При необходимости выбери повторения.\n"
        "5) Добавь участников и нажми «Сохранить событие».\n\n"
        "👥 Участники:\n"
        "• Чтобы добавить участника, отправь его контакт в чат.\n"
        "• Если человек еще не запускал бота — он появится с пометкой «не в боте».\n"
        "• Управление списком участников — команда /team.\n\n"
        "⏰ Ближайшие события:\n"
        "Нажми «Ближайшие события», чтобы увидеть список на несколько дней вперед.\n\n"
        "🗑️ Удаление событий:\n"
        "В календаре выбери дату и нажми «Удалить событие».\n\n"
        "Если что-то не работает — просто напиши @FamPlanner, помогу разобраться 😊"
    )
    await update.message.reply_text(text=text)


async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("handle_location")

    location = update.message.location

    user = update.effective_chat
    tg_user = TgUser.model_validate(user)
    db_user = await db_controller.save_update_user(tg_user=tg_user)
    logger.info(f"*** DB user: {db_user}")

    logger.info(
        f"Пользователь {user.id} ({user.first_name}) поделился геолокацией: " f"широта={location.latitude}, долгота={location.longitude}"
    )
    tf = TimezoneFinder()

    tz_name = tf.timezone_at(lat=location.latitude, lng=location.longitude)
    logger.info(f"tz name; {tz_name}")
    try:
        now = datetime.now(ZoneInfo(tz_name))
        offset = now.utcoffset()

        tg_user.time_zone = tz_name
        await db_controller.save_update_user(tg_user=tg_user)
        logger.info(f"OFFSET: {offset}, {int(offset.total_seconds()/3600)}, {type(offset)}")
    except:  # noqa
        logger.exception("OFFSET ERR: ")
        pass

    await show_main_menu(update.message, add_text="Спасибо за геолокацию!")


async def handle_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("handle_skip")

    user = update.effective_user
    logger.info(f"Пользователь {user.id} ({user.first_name}) пропустил геолокацию")

    await show_main_menu(update.message, add_text="Ок, продолжим без геолокации.")


async def show_main_menu(message: Message, add_text: str | None = None) -> None:
    logger.info("show_main_menu")

    keyboard = [["📅 Показать календарь"], ["🗓 Ближайшие события"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    text = f"{add_text}\n\nВыберите действие:" if add_text else "Выбери действие:"

    await message.reply_text(text=text, reply_markup=reply_markup)
