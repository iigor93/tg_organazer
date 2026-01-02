import logging

from telegram import Update
from telegram.ext import ContextTypes

from database.db_controller import db_controller
from entities import TgUser

logger = logging.getLogger(__name__)


async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("handle_contact")

    contact = update.message.contact
    if contact and not contact.user_id:
        await update.message.reply_text("Похоже этот номер не зарегистрирован в телеграмм!")
    elif contact:
        user_id = contact.user_id
        if user_id == update.effective_user.id:
            await update.message.reply_text("Нельзя добавлять себя")
            return
        first_name = contact.first_name
        last_name = contact.last_name
        # phone_number = contact.phone_number
        new_user = TgUser(
            id=user_id,
            first_name=first_name,
            last_name=last_name,
        )
        created_user = await db_controller.save_update_user(tg_user=new_user, from_contact=True, current_user=update.effective_user.id)
        if not created_user:
            text = f"Пользователь {first_name} уже добавлен в ваши контакты!"
        elif created_user.is_active:
            text = f"Пользователь {first_name} добавлен в ваши контакты!"
        else:
            text = f"Пользователь {first_name} добавлен в ваши контакты!\nНо его еще нет в боте."

        await db_controller.get_user(tg_id=update.effective_user.id)

        await update.message.reply_text(text=text)
    else:
        await update.message.reply_text("Не удалось получить данные пользователя, попробуйте еще раз")
