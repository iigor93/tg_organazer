import logging
import re
from urllib.parse import urlparse

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from database.db_controller import db_controller
from entities import TgUser
from i18n import resolve_user_locale, tr

logger = logging.getLogger(__name__)


def _normalize_participants(participants: dict[int, str] | dict[str, str] | None) -> dict[int, str]:
    normalized: dict[int, str] = {}
    for raw_tg_id, name in (participants or {}).items():
        try:
            tg_id = int(raw_tg_id)
        except (TypeError, ValueError):
            continue
        normalized[tg_id] = name
    return normalized


def _normalize_selected(selected: list[int] | list[str] | set[int] | set[str] | None) -> set[int]:
    normalized: set[int] = set()
    for raw_tg_id in (selected or []):
        try:
            normalized.add(int(raw_tg_id))
        except (TypeError, ValueError):
            continue
    return normalized


def _build_team_keyboard(participants: dict[int, str], selected: set[int], locale: str | None = None) -> InlineKeyboardMarkup:
    buttons = []
    for tg_id, name in participants.items():
        postfix = " ❌" if tg_id in selected else ""
        buttons.append([InlineKeyboardButton(f"{name}{postfix}", callback_data=f"team_toggle_{tg_id}")])

    buttons.append([InlineKeyboardButton(tr("Удалить выбранных", locale), callback_data="team_delete")])
    buttons.append([InlineKeyboardButton(tr("Закрыть", locale), callback_data="team_close")])

    return InlineKeyboardMarkup(buttons)


def _extract_tg_identifier(raw_value: str) -> tuple[int | None, str | None]:
    value = (raw_value or "").strip()
    if not value:
        return None, None

    if re.fullmatch(r"-?\d+", value):
        return int(value), None

    if value.startswith("@"):
        username = value[1:].strip()
        return None, username or None

    if value.startswith("tg://user?id="):
        tg_id = value.removeprefix("tg://user?id=").strip()
        if re.fullmatch(r"-?\d+", tg_id):
            return int(tg_id), None
        return None, None

    parsed = urlparse(value if "://" in value else f"https://{value}")
    if parsed.netloc.lower() in {"t.me", "www.t.me", "telegram.me", "www.telegram.me"}:
        path = parsed.path.strip("/")
        if not path:
            return None, None
        username = path.split("/", 1)[0].strip()
        if username.startswith("@"):
            username = username[1:]
        if not username or username in {"joinchat", "c", "s", "share"}:
            return None, None
        return None, username

    return None, None


def _display_name(user: TgUser | None, fallback_id: int | None = None, fallback_username: str | None = None) -> str:
    if user:
        if user.first_name:
            return user.first_name
        if user.username:
            username = user.username.lstrip("@")
            return f"@{username}" if username else user.username
        if user.tg_id is not None:
            return str(user.tg_id)
    if fallback_username:
        normalized = fallback_username.lstrip("@")
        return f"@{normalized}" if normalized else fallback_username
    if fallback_id is not None:
        return str(fallback_id)
    return tr("пользователь")


async def handle_team_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("handle_team_command")
    context.chat_data.pop("team_participants", None)
    context.chat_data.pop("team_selected", None)
    context.chat_data.pop("event", None)
    context.chat_data.pop("participants_status", None)
    context.chat_data.pop("time_picker_message_id", None)
    context.chat_data.pop("time_picker_chat_id", None)
    context.chat_data.pop("await_time_input", None)
    context.chat_data.pop("time_input_prompt_message_id", None)
    context.chat_data.pop("time_input_prompt_chat_id", None)
    user_id = update.effective_chat.id
    locale = await resolve_user_locale(user_id, platform="tg")

    participants = _normalize_participants(await db_controller.get_participants(tg_id=user_id, include_inactive=True))
    if not participants:
        await update.message.reply_text(tr("У вас нет привязанных участников.", locale))
        return

    context.chat_data["team_participants"] = participants
    context.chat_data["team_selected"] = []

    reply_markup = _build_team_keyboard(participants, set(), locale=locale)
    await update.message.reply_text(
        tr("Список привязанных участников. Выберите лишних и нажмите удалить.", locale),
        reply_markup=reply_markup,
    )


async def handle_team_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("handle_team_callback")
    query = update.callback_query
    await query.answer()

    user_id = update.effective_chat.id
    locale = await resolve_user_locale(user_id, platform="tg")
    data = query.data

    participants = _normalize_participants(
        context.chat_data.get("team_participants") or await db_controller.get_participants(tg_id=user_id, include_inactive=True) or {}
    )
    selected = _normalize_selected(context.chat_data.get("team_selected"))

    if data.startswith("team_toggle_"):
        _, _, tg_id_str = data.split("_")
        tg_id = int(tg_id_str)
        if tg_id in selected:
            selected.remove(tg_id)
        else:
            selected.add(tg_id)

        context.chat_data["team_selected"] = list(selected)
        reply_markup = _build_team_keyboard(participants, selected, locale=locale)
        await query.edit_message_reply_markup(reply_markup=reply_markup)
        return

    if data == "team_delete":
        if not selected:
            await query.edit_message_text(
                tr("Выберите участников для удаления.", locale),
                reply_markup=_build_team_keyboard(participants, selected, locale=locale),
            )
            return

        deleted = await db_controller.delete_participants(current_tg_id=user_id, related_tg_ids=list(selected))
        participants = _normalize_participants(await db_controller.get_participants(tg_id=user_id, include_inactive=True) or {})
        context.chat_data["team_participants"] = participants
        context.chat_data["team_selected"] = []

        if not participants:
            await query.edit_message_text(tr("Все участники удалены.", locale))
            return

        reply_markup = _build_team_keyboard(participants, set(), locale=locale)
        await query.edit_message_text(
            tr("Удалено: {count}. Выберите следующих участников.", locale).format(count=deleted),
            reply_markup=reply_markup,
        )
        return

    if data == "team_close":
        context.chat_data.pop("team_participants", None)
        context.chat_data.pop("team_selected", None)
        await query.edit_message_text(tr("Управление участниками закрыто.", locale))
        return


async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("handle_contact")

    contact = update.message.contact
    if contact and not contact.user_id:
        await update.message.reply_text("Похоже этот номер не зарегистрирован в Telegram!")
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
        created_user = await db_controller.save_update_user(tg_user=new_user, from_contact=True, current_user=update.effective_chat.id)
        if not created_user:
            text = f"Пользователь {first_name} уже добавлен в ваши контакты!"
        elif created_user.is_active:
            text = f"Пользователь {first_name} добавлен в ваши контакты!"
        else:
            text = (
                f"Пользователь {first_name} добавлен в ваши контакты!\n"
                "Отправьте ему приглашение в FamPlanner_bot. Вы сможете добавлять его, как участника события, после того как он нажмет START. "
                "Перешлите ему следующее сообщение:"
            )
            invite_text = (
                "Привет!\nДавай вместе создавать события и строить планы!\n"
                "Запусти бота и нажми START.\nВот ссылка: https://t.me/FamPlanner_bot"
            )

        await db_controller.get_user(tg_id=update.effective_chat.id)

        await update.message.reply_text(text=text)
        if "invite_text" in locals():
            await update.message.reply_text(text=invite_text)

        event = context.chat_data.get("event")
        if event:
            participants = _normalize_participants(
                await db_controller.get_participants(tg_id=update.effective_chat.id, include_inactive=True) or {}
            )
            event.all_user_participants = participants
            context.chat_data["event"] = event

            reply_markup = InlineKeyboardMarkup(
                [[InlineKeyboardButton("Продолжить создание события", callback_data="create_event_begin_")]]
            )
            await update.message.reply_text(
                "Участник добавлен в контакты. Можно продолжить создание события.",
                reply_markup=reply_markup,
            )
    else:
        await update.message.reply_text("Не удалось получить данные пользователя, попробуйте еще раз")


async def handle_contact_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    locale = await resolve_user_locale(getattr(update.effective_chat, "id", None), platform="tg")
    tg_id, username = _extract_tg_identifier(update.message.text or "")
    if tg_id is None and not username:
        await update.message.reply_text(
            tr("Отправьте @username, ссылку t.me/... или числовой Telegram ID.", locale)
        )
        return True

    if tg_id is not None:
        if tg_id == update.effective_chat.id:
            await update.message.reply_text(tr("Нельзя добавлять себя", locale))
            return True
        new_user = TgUser(id=tg_id)
        created_user = await db_controller.save_update_user(
            tg_user=new_user,
            from_contact=True,
            current_user=update.effective_chat.id,
        )
    else:
        found_user = await db_controller.get_user_by_username(username=username, platform="tg")
        if not found_user:
            await update.message.reply_text(
                tr("Не удалось найти этого пользователя. Отправьте его числовой Telegram ID.", locale)
            )
            return True
        if found_user.tg_id == update.effective_chat.id:
            await update.message.reply_text(tr("Нельзя добавлять себя", locale))
            return True
        created_user = await db_controller.save_update_user(
            tg_user=found_user,
            from_contact=True,
            current_user=update.effective_chat.id,
        )

    name = _display_name(created_user, fallback_id=tg_id, fallback_username=username)
    if not created_user:
        text = tr("Пользователь {name} уже добавлен в ваши контакты!", locale).format(name=name)
    elif created_user.is_active:
        text = tr("Пользователь {name} добавлен в ваши контакты!", locale).format(name=name)
    else:
        text = (
            tr("Пользователь {name} добавлен в ваши контакты!", locale).format(name=name) + "\n"
            + tr(
                "Отправьте ему приглашение в FamPlanner_bot. Вы сможете добавлять его, как участника события, после того как он нажмет START. Перешлите ему следующее сообщение:",
                locale,
            )
        )
        invite_text = (
            tr(
                "Привет!\nДавай вместе создавать события и строить планы!\n"
                "Запусти бота и нажми START.\nВот ссылка: https://t.me/FamPlanner_bot",
                locale,
            )
        )

    await db_controller.get_user(tg_id=update.effective_chat.id)
    await update.message.reply_text(text=text)
    if "invite_text" in locals():
        await update.message.reply_text(text=invite_text)

    event = context.chat_data.get("event")
    if event:
        participants = _normalize_participants(
            await db_controller.get_participants(tg_id=update.effective_chat.id, include_inactive=True) or {}
        )
        event.all_user_participants = participants
        context.chat_data["event"] = event

        reply_markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton(tr("Продолжить создание события", locale), callback_data="create_event_begin_")]]
        )
        await update.message.reply_text(
            tr("Участник добавлен в контакты. Можно продолжить создание события.", locale),
            reply_markup=reply_markup,
        )
    return True
