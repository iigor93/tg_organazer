import logging

from telegram import KeyboardButton, Message, ReplyKeyboardMarkup, Update
from telegram.ext import ContextTypes

from database.db_controller import db_controller
from entities import TgUser

logger = logging.getLogger(__name__)

# from models import User


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("start")

    user = update.effective_user
    tg_user = TgUser.model_validate(user)
    await db_controller.save_update_user(tg_user=tg_user)

    # user_state.get(user.id)
    # if not user_state:
    #     user_state[user.id] = User(telegram_id=user.id)

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

    # local_user: User = user_state.get(user.id)
    # local_user.geo_location = f"широта={location.latitude}, долгота={location.longitude}"
    logger.info(
        f"Пользователь {user.id} ({user.first_name}) поделился геолокацией: " f"широта={location.latitude}, долгота={location.longitude}"
    )

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
