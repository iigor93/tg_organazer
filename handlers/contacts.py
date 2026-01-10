import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from database.db_controller import db_controller
from entities import TgUser

logger = logging.getLogger(__name__)


def _build_team_keyboard(participants: dict[int, str], selected: set[int]) -> InlineKeyboardMarkup:
    buttons = []
    for tg_id, name in participants.items():
        postfix = " ❌" if tg_id in selected else ""
        buttons.append([InlineKeyboardButton(f"{name}{postfix}", callback_data=f"team_toggle_{tg_id}")])

    buttons.append([InlineKeyboardButton("Удалить выбранных", callback_data="team_delete")])
    buttons.append([InlineKeyboardButton("Закрыть", callback_data="team_close")])

    return InlineKeyboardMarkup(buttons)


async def handle_team_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("handle_team_command")
    user_id = update.effective_chat.id

    participants = await db_controller.get_participants(tg_id=user_id, include_inactive=True)
    if not participants:
        await update.message.reply_text("У вас нет привязанных участников.")
        return

    context.chat_data["team_participants"] = participants
    context.chat_data["team_selected"] = []

    reply_markup = _build_team_keyboard(participants, set())
    await update.message.reply_text(
        "Список привязанных участников. Выберите лишних и нажмите удалить.",
        reply_markup=reply_markup,
    )


async def handle_team_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("handle_team_callback")
    query = update.callback_query
    await query.answer()

    user_id = update.effective_chat.id
    data = query.data

    participants = (
        context.chat_data.get("team_participants") or await db_controller.get_participants(tg_id=user_id, include_inactive=True) or {}
    )
    selected = set(context.chat_data.get("team_selected") or [])

    if data.startswith("team_toggle_"):
        _, _, tg_id_str = data.split("_")
        tg_id = int(tg_id_str)
        if tg_id in selected:
            selected.remove(tg_id)
        else:
            selected.add(tg_id)

        context.chat_data["team_selected"] = list(selected)
        reply_markup = _build_team_keyboard(participants, selected)
        await query.edit_message_reply_markup(reply_markup=reply_markup)
        return

    if data == "team_delete":
        if not selected:
            await query.edit_message_text(
                "Выберите участников для удаления.",
                reply_markup=_build_team_keyboard(participants, selected),
            )
            return

        deleted = await db_controller.delete_participants(current_tg_id=user_id, related_tg_ids=list(selected))
        participants = await db_controller.get_participants(tg_id=user_id, include_inactive=True) or {}
        context.chat_data["team_participants"] = participants
        context.chat_data["team_selected"] = []

        if not participants:
            await query.edit_message_text("Все участники удалены.")
            return

        reply_markup = _build_team_keyboard(participants, set())
        await query.edit_message_text(
            f"Удалено: {deleted}. Выберите следующих участников.",
            reply_markup=reply_markup,
        )
        return

    if data == "team_close":
        context.chat_data.pop("team_participants", None)
        context.chat_data.pop("team_selected", None)
        await query.edit_message_text("Управление участниками закрыто.")
        return


async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("handle_contact")

    contact = update.message.contact
    if contact and not contact.user_id:
        await update.message.reply_text("Похоже этот номер не зарегистрирован в телеграмм!")
    elif contact:
        user_id = contact.user_id
        if user_id == update.effective_chat.id:
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
