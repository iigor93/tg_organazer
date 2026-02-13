import logging
from datetime import datetime

from telegram import ForceReply, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from database.db_controller import db_controller
from database.models.note_model import DbNote
from entities import TgUser
from i18n import format_localized_datetime, resolve_user_locale, tr

logger = logging.getLogger(__name__)

NOTE_MAX_LENGTH = 3500
NOTE_PREVIEW_LENGTH = 40
PROMPT_PREVIEW_LENGTH = 1200


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit - 1]}…"


def _normalize_note_text(text: str | None) -> str:
    return (text or "").strip()


def _build_notes_markup(notes: list[DbNote], locale: str | None = None) -> InlineKeyboardMarkup:
    rows = []
    for note in notes:
        compact = " ".join(note.note_text.split())
        preview = _truncate(compact, NOTE_PREVIEW_LENGTH)
        rows.append([InlineKeyboardButton(preview or tr("Без текста", locale), callback_data=f"note_open_{note.id}")])
    rows.append([InlineKeyboardButton(tr("🗒Создать заметку", locale), callback_data="note_create")])
    return InlineKeyboardMarkup(rows)


def _build_note_detail_text(note: DbNote, locale: str | None = None) -> str:
    stamp_dt = note.updated_at or note.created_at or datetime.utcnow()
    stamp = format_localized_datetime(stamp_dt, locale=locale, fmt="d MMMM y, HH:mm")
    return tr("🗒 Заметка\n\n{note_text}\n\n🕒 Обновлено: {updated_at}", locale).format(
        note_text=note.note_text,
        updated_at=stamp,
    )


def _build_note_detail_markup(note_id: int, locale: str | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(tr("Редактировать", locale), callback_data=f"note_edit_{note_id}")],
            [InlineKeyboardButton(tr("Удалить", locale), callback_data=f"note_delete_{note_id}")],
            [InlineKeyboardButton(tr("Назад", locale), callback_data="note_list")],
        ]
    )


def _parse_note_id(data: str, prefix: str) -> int | None:
    try:
        return int(data.removeprefix(prefix))
    except ValueError:
        return None


async def _safe_delete_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int | None, message_id: int | None) -> None:
    bot = getattr(context, "bot", None)
    if not bot or chat_id is None or message_id is None:
        return
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to delete note helper message")


async def build_notes_list_view(tg_id: int, locale: str | None = None) -> tuple[str, InlineKeyboardMarkup]:
    notes = await db_controller.get_notes(tg_id=tg_id)
    text = tr("Выберите заметку:", locale) if notes else tr("У вас пока нет заметок.", locale)
    return text, _build_notes_markup(notes, locale)


async def _show_notes_list_by_query(query, tg_id: int, locale: str | None = None) -> None:
    text, reply_markup = await build_notes_list_view(tg_id=tg_id, locale=locale)
    await query.edit_message_text(text=text, reply_markup=reply_markup)


def _reset_note_states(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.chat_data.pop("await_note_create", None)
    context.chat_data.pop("await_note_edit", None)


async def show_notes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("show_notes")
    _reset_note_states(context)
    context.chat_data.pop("await_event_description", None)
    context.chat_data.pop("await_time_input", None)

    if not update.effective_chat or not update.message:
        return

    user = update.effective_chat
    tg_user = TgUser.model_validate(user)
    db_user = await db_controller.save_update_user(tg_user=tg_user)
    locale = await resolve_user_locale(user.id, platform="tg", preferred_language_code=tg_user.language_code)
    logger.info(f"*** DB user: {db_user}")

    text, reply_markup = await build_notes_list_view(tg_id=user.id, locale=locale)
    await update.message.reply_text(text=text, reply_markup=reply_markup)


async def handle_note_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("handle_note_callback")
    query = update.callback_query
    await query.answer()

    if not update.effective_chat:
        return

    user = update.effective_chat
    tg_user = TgUser.model_validate(user)
    db_user = await db_controller.save_update_user(tg_user=tg_user)
    locale = await resolve_user_locale(user.id, platform="tg", preferred_language_code=tg_user.language_code)
    logger.info(f"*** DB user: {db_user}")
    data = query.data

    if data == "note_list":
        await _show_notes_list_by_query(query, tg_id=user.id, locale=locale)
        return

    if data == "note_create":
        _reset_note_states(context)
        message = await query.message.reply_text(tr("Введите текст новой заметки:", locale))
        context.chat_data["await_note_create"] = {
            "source_message_id": getattr(query.message, "message_id", None),
            "source_chat_id": getattr(query.message, "chat_id", None),
            "prompt_message_id": getattr(message, "message_id", None),
            "prompt_chat_id": getattr(message, "chat_id", None),
        }
        return

    if data.startswith("note_open_"):
        note_id = _parse_note_id(data, "note_open_")
        if note_id is None:
            await _show_notes_list_by_query(query, tg_id=user.id, locale=locale)
            return
        note = await db_controller.get_note_by_id(note_id=note_id, tg_id=user.id)
        if not note:
            await _show_notes_list_by_query(query, tg_id=user.id, locale=locale)
            return
        await query.edit_message_text(
            text=_build_note_detail_text(note, locale),
            reply_markup=_build_note_detail_markup(note.id, locale),
        )
        return

    if data.startswith("note_delete_"):
        note_id = _parse_note_id(data, "note_delete_")
        if note_id is not None:
            await db_controller.delete_note(note_id=note_id, tg_id=user.id)
        await _show_notes_list_by_query(query, tg_id=user.id, locale=locale)
        return

    if data.startswith("note_edit_"):
        note_id = _parse_note_id(data, "note_edit_")
        if note_id is None:
            await _show_notes_list_by_query(query, tg_id=user.id, locale=locale)
            return
        note = await db_controller.get_note_by_id(note_id=note_id, tg_id=user.id)
        if not note:
            await _show_notes_list_by_query(query, tg_id=user.id, locale=locale)
            return

        _reset_note_states(context)
        preview = _truncate(note.note_text.replace("\n", " ").strip(), 64)
        prompt_note = _truncate(note.note_text, PROMPT_PREVIEW_LENGTH)
        message = await query.message.reply_text(
            tr("Измените текст заметки и отправьте новое сообщение.\n\nТекущий текст:\n{note_text}", locale).format(
                note_text=prompt_note
            ),
            reply_markup=ForceReply(selective=True, input_field_placeholder=preview or tr("Текст заметки", locale)),
        )
        context.chat_data["await_note_edit"] = {
            "note_id": note.id,
            "source_message_id": getattr(query.message, "message_id", None),
            "source_chat_id": getattr(query.message, "chat_id", None),
            "prompt_message_id": getattr(message, "message_id", None),
            "prompt_chat_id": getattr(message, "chat_id", None),
        }
        return

    await _show_notes_list_by_query(query, tg_id=user.id, locale=locale)


async def handle_note_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE, locale: str | None = None) -> bool:
    if not update.message or not update.effective_chat:
        return False

    state_create = context.chat_data.get("await_note_create")
    state_edit = context.chat_data.get("await_note_edit")
    if state_create is None and state_edit is None:
        return False

    note_text = _normalize_note_text(update.message.text)
    if not note_text:
        await update.message.reply_text(tr("Текст заметки не может быть пустым.", locale))
        return True
    if len(note_text) > NOTE_MAX_LENGTH:
        await update.message.reply_text(
            tr("Слишком длинная заметка. Максимум {limit} символов.", locale).format(limit=NOTE_MAX_LENGTH)
        )
        return True

    if state_create is not None:
        await db_controller.create_note(tg_id=update.effective_chat.id, note_text=note_text)
        context.chat_data.pop("await_note_create", None)
        await _safe_delete_message(
            context,
            chat_id=getattr(update.message, "chat_id", None),
            message_id=getattr(update.message, "message_id", None),
        )
        await _safe_delete_message(
            context,
            chat_id=state_create.get("prompt_chat_id"),
            message_id=state_create.get("prompt_message_id"),
        )

        text, reply_markup = await build_notes_list_view(tg_id=update.effective_chat.id, locale=locale)
        source_chat_id = state_create.get("source_chat_id")
        source_message_id = state_create.get("source_message_id")
        bot = getattr(context, "bot", None)
        if bot and source_chat_id and source_message_id:
            await bot.edit_message_text(chat_id=source_chat_id, message_id=source_message_id, text=text, reply_markup=reply_markup)
        else:
            await update.message.reply_text(text=text, reply_markup=reply_markup)
        return True

    note_id = state_edit.get("note_id")
    if note_id is None:
        context.chat_data.pop("await_note_edit", None)
        await update.message.reply_text(tr("Заметка не найдена.", locale))
        return True

    note = await db_controller.update_note(note_id=note_id, tg_id=update.effective_chat.id, note_text=note_text)
    context.chat_data.pop("await_note_edit", None)
    await _safe_delete_message(
        context,
        chat_id=getattr(update.message, "chat_id", None),
        message_id=getattr(update.message, "message_id", None),
    )
    await _safe_delete_message(
        context,
        chat_id=state_edit.get("prompt_chat_id"),
        message_id=state_edit.get("prompt_message_id"),
    )

    if not note:
        await update.message.reply_text(tr("Заметка не найдена.", locale))
        return True

    text = _build_note_detail_text(note, locale)
    reply_markup = _build_note_detail_markup(note.id, locale)
    source_chat_id = state_edit.get("source_chat_id")
    source_message_id = state_edit.get("source_message_id")
    bot = getattr(context, "bot", None)
    if bot and source_chat_id and source_message_id:
        await bot.edit_message_text(chat_id=source_chat_id, message_id=source_message_id, text=text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text=text, reply_markup=reply_markup)
    return True
