import asyncio
import datetime as dt
import html
import os
import random
import re
import shutil
import tempfile
import time
import urllib.parse
import zipfile
import difflib
from collections import deque
from typing import Optional
from zoneinfo import ZoneInfo

from aiogram.exceptions import TelegramBadRequest

from aiogram import F, Router
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramRetryAfter,
    TelegramForbiddenError,
)
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    CallbackQuery,
    ChatJoinRequest,
    ChatPermissions,
    FSInputFile,
    Message,
    MessageEntity,
    ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from telethon.errors import FloodWaitError
from telethon.tl.functions.messages import GetBotCallbackAnswerRequest
from telethon.tl.functions.messages import GetForumTopicsRequest
from telethon.utils import get_peer_id

from app.config import (
    BROADCAST_BATCH_EVERY,
    BROADCAST_BATCH_SLEEP,
    CACHE_CLEAN_INTERVAL,
    CONTACT_REPLY_MAXLEN,
    BACKUP_DIR,
    DB_PATH,
    IMPORT_GROUP_ID,
    LOG_PATH,
    OWNER_ID,
    SOURCE_CHANNEL_ID,
    VIP_REMINDER_INTERVAL,
    INLINE_KEYBOARD_EXPIRE_SECONDS,
    BACKUP_CHANNEL_ID,
)
from app.config import BACKUP_TZ
from app.restore  import auto_restore_latest_backup

from app.db import (
    add_admin,
    add_channel,
    add_serial,
    add_serial_part,
    add_join_request,
    add_user,
    del_admin,
    del_channel,
    get_admins,
    get_admin_permissions,
    get_channels,
    get_serial_by_code,
    get_serial_by_id,
    get_serial_by_title,
    get_serial_part,
    get_serial_parts,
    set_serial_part_vip,
    get_serial_session,
    get_serials,
    get_serials_page,
    count_serials,
    serial_part_source_exists,
    delete_empty_serials,
    search_serials_by_title,
    count_serials_by_title,
    del_serial,
    del_serial_part,
    init_db,
    set_serial_vip,
    add_vip_user,
    remove_vip_user,
    get_vip_users,
    get_vip_users_page,
    count_vip_users,
    get_vip_user,
    set_setting,
    get_setting,
    mark_vip_reminder,
    is_admin,
    serial_part_exists,
    save_serial_session,
    clear_serial_session,
    get_users,
    get_users_page,
    has_admin_permission,
    has_join_request,
    set_admin_permissions,
    record_serial_view,
    get_serial_day_stats,
    get_serial_recent_days,
    get_serial_notification_map,
    mark_serial_notification_sent,
    set_serial_notification_muted,
    get_serial_notification,
    get_serial_total_views_map,
    block_user,
    unblock_user,
    get_blocked_users,
    is_blocked_user,
    get_serial_rating,
    set_serial_rating,
    get_serial_rating_counts,
    get_serial_rating_like_counts_map,
    get_top_liked_serials,
    get_latest_serials,
    rename_serial,
    record_user_serial_view,
    get_user_liked_serial_ids,
    get_user_viewed_serial_ids,
    get_active_user_ids,
    get_user_daily_recommendations_for_users,
    count_users,
    iter_user_ids,
    get_similar_serials_by_likes,
    get_similar_serials_by_views,
    set_user_daily_recommendation,
    get_user_id_by_username,
)
from app.keyboards import (
    admin_back_keyboard,
    admin_panel_keyboard,
    admin_permissions_keyboard,
    admin_edit_list_keyboard,
    log_cancel_keyboard,
    post_link_keyboard,
    post_media_keyboard,
    post_channel_keyboard,
    serial_cancel_keyboard,
    serial_flow_keyboard,
    serial_parts_keyboard,
    serial_nav_keyboard,
    serials_list_keyboard,
    vip_info_keyboard,
    vip_duration_keyboard,
    vip_list_keyboard,
    vip_price_keyboard,
    user_serials_keyboard,
    user_search_keyboard,
    user_serials_menu_keyboard,
    user_search_results_keyboard,
    contact_admin_keyboard,
    subscribe_keyboard,
    users_keyboard,
    user_keyboard,
    broadcast_target_keyboard,
    users_manage_keyboard,
)
from app.userbot import (
    UserbotError,
    get_userbot_client,
    reset_userbot_client,
    set_userbot_api_hash,
    set_userbot_api_id,
    set_userbot_session,
)
from app.handlers_vip import (
    VIP_CARD_NUMBER_KEY,
    VIP_CARD_OWNER_KEY,
    VIP_MESSAGE_KEY,
    VIP_PRICE_KEY,
    get_vip_card_details as _get_vip_card_details,
    get_vip_message as _get_vip_message,
    get_vip_price as _get_vip_price,
    include_vip_serials as _include_vip_serials,
    is_vip_user as _is_vip_user,
    send_vip_info as _send_vip_info,
    send_vip_required as _send_vip_required,
    update_receipt_status as _update_receipt_status,
    vip_receipt_keyboard as _vip_receipt_keyboard,
    visible_serial_parts_for_user as _visible_serial_parts_for_user,
)

from app.handlers_sessions import (
    ADMIN_ADD_SESSIONS,
    ADMIN_USER_MESSAGE_SESSIONS,
    BROADCAST_SESSIONS,
    BROADCAST_TEXT_SESSIONS,
    CONTACT_ADMIN_SESSIONS,
    CONTACT_REPLY_MAP,
    CONTACT_REPLY_ORDER,
    GROUP_SPAM_TRACKER,
    IMPORT_SESSIONS,
    IMPORT_TASKS,
    LOG_QUERY_ADMINS,
    PENDING_START_CODES,
    POST_SESSIONS,
    RESTORE_DB_SESSIONS,
    SERIAL_BANNER_SESSIONS,
    SERIAL_RENAME_SESSIONS,
    SERIAL_UPLOAD_COUNTERS,
    SERIAL_UPLOAD_LOCKS,
    SERIAL_UPLOAD_NEXT_PART,
    SERIAL_UPLOAD_QUEUES,
    SERIAL_UPLOAD_TASKS,
    USER_SEARCH_RESULTS,
    USER_SEARCH_SESSIONS,
    USER_SERIALS_LIST,
    VIP_ADD_SESSIONS,
    VIP_CARD_SESSIONS,
    VIP_EXPIRED_NOTICE_MESSAGE_ID,
    VIP_MESSAGE_SESSIONS,
    VIP_PAYMENT_SESSIONS,
    VIP_PRICE_SESSIONS,
    VIP_RECEIPT_APPROVED,
    VIP_RECEIPT_MESSAGES,
    VIP_RECEIPT_REJECTED,
    VIP_REJECT_SESSIONS,
    cleanup_sessions,
)


_INLINE_EXPIRE_TASKS: dict[tuple[int, int], asyncio.Task] = {}
_INLINE_EXPIRE_CLEANUPS: dict[tuple[int, int], callable] = {}


def _cancel_inline_expire(chat_id: int, message_id: int) -> None:
    key = (int(chat_id), int(message_id))
    task = _INLINE_EXPIRE_TASKS.pop(key, None)
    if task and not task.done():
        task.cancel()
    _INLINE_EXPIRE_CLEANUPS.pop(key, None)


def _schedule_inline_expire(bot, chat_id: int, message_id: int, cleanup=None) -> None:
    if INLINE_KEYBOARD_EXPIRE_SECONDS <= 0:
        return
    key = (int(chat_id), int(message_id))
    _cancel_inline_expire(key[0], key[1])
    if cleanup is not None:
        _INLINE_EXPIRE_CLEANUPS[key] = cleanup

    async def _expire() -> None:
        try:
            await asyncio.sleep(INLINE_KEYBOARD_EXPIRE_SECONDS)
            await _safe_edit_reply_markup(bot, key[0], key[1], None)
            cleanup_fn = _INLINE_EXPIRE_CLEANUPS.pop(key, None)
            if cleanup_fn:
                try:
                    cleanup_fn()
                except Exception:
                    pass
        except asyncio.CancelledError:
            return
        finally:
            _INLINE_EXPIRE_TASKS.pop(key, None)

    _INLINE_EXPIRE_TASKS[key] = asyncio.create_task(_expire())



SERIAL_PARTS_PER_PAGE = 15
SERIALS_PER_PAGE = 20
USERS_PER_PAGE = 20
ADMINS_PER_PAGE = 20
USER_SERIALS_PER_PAGE = 30
VIP_LISTS_PER_PAGE = 20
RECOMMENDATION_LAST_DATE_KEY = "daily_reco_last_date"
RECOMMENDATION_NEXT_RUN_KEY = "daily_reco_next_run"
RECOMMENDATION_WINDOW_START = 19
RECOMMENDATION_WINDOW_END = 23
RECOMMENDATION_PREPARED_DATE_KEY = "daily_reco_prepared_date"
RECOMMENDATION_IDLE_SECONDS = 600
LAST_ACTIVITY_AT_KEY = "last_activity_at"
VIP_EXPIRED_NOTIFY_LAST_DATE_KEY = "vip_expired_last_date"
VIP_EXPIRED_NOTIFY_HOUR = 7
ADMIN_PERMISSION_LABELS = {
    "can_manage_admins": "Adminlarni boshqarish",
    "can_manage_channels": "Kanallarni boshqarish",
    "can_manage_vip": "VIP boshqarish",
    "can_add_serial": "Drama qo'shish",
    "can_add_part": "Qism qo'shish",
    "can_broadcast": "E'lon yuborish",
    "can_message_users": "Foydalanuvchiga yozish",
    "can_view_lists": "Ro'yxatlarni ko'rish",
    "can_view_logs": "Loglarni ko'rish",
    "can_view_stats": "Statistikani ko'rish",
    "can_backup": "Backup olish",
}

GROUP_SPAM_WINDOW = 60
GROUP_SPAM_LIMIT = 3
GROUP_MUTE_SECONDS = 120

ADMIN_PERMISSION_KEYS = list(ADMIN_PERMISSION_LABELS.keys())


def _default_admin_permissions() -> dict[str, int]:
    return {key: 1 for key in ADMIN_PERMISSION_LABELS}


def _has_perm(user_id: int, perm: str) -> bool:
    return has_admin_permission(user_id, perm)


def _is_admin_user(user_id: int) -> bool:
    if is_admin(user_id):
        return True
    perms = get_admin_permissions(user_id)
    return bool(perms)


def _format_perm_text(perms: dict[str, int]) -> str:
    lines = ["Ruxsatlarni tanlang:"]
    for key, label in ADMIN_PERMISSION_LABELS.items():
        icon = "✅" if perms.get(key) else "❌"
        lines.append(f"{icon} {label}")
    return "\n".join(lines)


def _utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _extract_media_payload(message: Message) -> Optional[dict[str, object]]:
    if message.photo:
        return {
            "type": "photo",
            "file_id": message.photo[-1].file_id,
            "caption": message.caption or "",
            "caption_entities": message.caption_entities or [],
        }
    if message.video:
        return {
            "type": "video",
            "file_id": message.video.file_id,
            "caption": message.caption or "",
            "caption_entities": message.caption_entities or [],
        }
    if message.document:
        return {
            "type": "document",
            "file_id": message.document.file_id,
            "caption": message.caption or "",
            "caption_entities": message.caption_entities or [],
        }
    return None


def _format_perm_inline(perms: dict[str, int]) -> str:
    parts = []
    for key in ADMIN_PERMISSION_KEYS:
        icon = "✅" if perms.get(key) else "❌"
        label = ADMIN_PERMISSION_LABELS.get(key, key)
        parts.append(f"{label}:{icon}")
    return ", ".join(parts)


def _new_drama_broadcast_keyboard(kind: str, serial_id: int):
    kb = InlineKeyboardBuilder()
    if kind == "all":
        kb.button(text="Hammaga yuborish", callback_data=f"newdrama:all:{serial_id}")
    elif kind == "vip":
        kb.button(text="VIP obunachilarga yuborish", callback_data=f"newdrama:vip:{serial_id}")
    kb.button(text="Yubormaslik", callback_data=f"newdrama:skip:{serial_id}")
    kb.adjust(1)
    return kb.as_markup()


def _new_part_broadcast_keyboard(kind: str, serial_id: int, part: int):
    kb = InlineKeyboardBuilder()
    if kind == "all":
        kb.button(text="Hammaga yuborish", callback_data=f"newpart:all:{serial_id}:{part}")
    elif kind == "vip":
        kb.button(text="VIP obunachilarga yuborish", callback_data=f"newpart:vip:{serial_id}:{part}")
    kb.button(text="Yubormaslik", callback_data=f"newpart:skip:{serial_id}:{part}")
    kb.adjust(1)
    return kb.as_markup()


def _serial_notify_optout_keyboard(serial_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(
        text="Bu drama uchun bildirishnomani o'chirish",
        callback_data=f"serialnotify:off:{serial_id}",
    )
    kb.adjust(1)
    return kb.as_markup()


def _next_missing_part(serial_id: int) -> int:
    parts = get_serial_parts(serial_id)
    existing = {int(row["part"]) for row in parts if row.get("part") is not None}
    part = 1
    while part in existing:
        part += 1
    return part


def _remember_contact_reply(admin_id: int, message_id: int, user_id: int) -> None:
    key = (admin_id, message_id)
    CONTACT_REPLY_MAP[key] = user_id
    CONTACT_REPLY_ORDER.append(key)
    while len(CONTACT_REPLY_MAP) > CONTACT_REPLY_ORDER.maxlen:
        old = CONTACT_REPLY_ORDER.popleft()
        CONTACT_REPLY_MAP.pop(old, None)


def _schedule_delete_message(bot, chat_id: int, message_id: int, delay_seconds: int = 86400) -> None:
    async def _delete_later() -> None:
        await asyncio.sleep(delay_seconds)
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception:
            pass

    asyncio.create_task(_delete_later())


def _filter_serials_for_user(user_id: int, serials: list[dict]) -> list[dict]:
    return serials


def _normalize_search_text(text: str) -> str:
    value = text.lower().strip()
    value = value.replace("o'", "o").replace("g'", "g")
    value = value.replace("o‘", "o").replace("g‘", "g")
    value = value.replace("o’", "o").replace("g’", "g")
    value = value.replace("x", "h")
    value = re.sub(r"[^a-z0-9]+", "", value)
    return value


def _strip_links(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"\b\w+\.\w+\b", "", text, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"(https?://\S+|www\.\S+|t\.me/\S+|tg://\S+|@\w+)",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned


def _suggest_serial_titles(user_id: int, query: str, limit: int = 5) -> list[str]:
    query = (query or "").strip()
    if not query:
        return []
    include_vip = _include_vip_serials(user_id)
    titles = []
    titles_norm = {}
    for item in get_serials():
        if not item or not item.get("title"):
            continue
        if not include_vip and item.get("is_vip"):
            continue
        title = str(item.get("title"))
        norm = _normalize_search_text(title)
        if not norm:
            continue
        titles.append(title)
        titles_norm[title] = norm
    qnorm = _normalize_search_text(query)
    if not qnorm:
        return []
    candidates = difflib.get_close_matches(
        qnorm,
        list(titles_norm.values()),
        n=max(limit * 3, limit),
        cutoff=0.55,
    )
    if not candidates:
        return []
    # map normalized back to original titles (may be duplicates; keep order)
    out: list[str] = []
    seen: set[str] = set()
    for norm in candidates:
        for title, tnorm in titles_norm.items():
            if tnorm != norm:
                continue
            if title in seen:
                continue
            seen.add(title)
            out.append(title)
            if len(out) >= limit:
                return out
    return out







async def _bot_in_chat(bot, chat_id: int) -> bool:
    try:
        me = await bot.get_me()
        member = await bot.get_chat_member(chat_id, me.id)
    except Exception:
        return False
    return member.status not in {ChatMemberStatus.LEFT, ChatMemberStatus.KICKED}


async def _fetch_forum_topics(client, entity) -> list[dict[str, object]]:
    topics: list[dict[str, object]] = []
    offset_date = None
    offset_id = 0
    offset_topic = 0
    while True:
        result = await client(
            GetForumTopicsRequest(
                peer=entity,
                offset_date=offset_date,
                offset_id=offset_id,
                offset_topic=offset_topic,
                limit=100,
                q="",
            )
        )
        if not result.topics:
            break
        for topic in result.topics:
            title = (getattr(topic, "title", "") or "").strip()
            if not title:
                continue
            topics.append(
                {
                    "topic_id": topic.id,
                    "title": title,
                }
            )
        last = result.topics[-1]
        offset_id = last.id
        offset_date = last.date
        offset_topic = last.id
    return topics


def _shorten_label(value: str, limit: int = 32) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 3)]}..."


def _chunk_lines(lines: list[str], limit: int = 3900) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in lines:
        add_len = len(line) + (1 if current else 0)
        if current and size + add_len > limit:
            chunks.append("\n".join(current))
            current = []
            size = 0
        current.append(line)
        size += add_len
    if current:
        chunks.append("\n".join(current))
    return chunks


def _import_selected_topics(session: dict[str, object]) -> list[dict[str, object]]:
    topics = session.get("topics") or []
    excluded = session.get("excluded") or set()
    return [item for idx, item in enumerate(topics, start=1) if idx not in excluded]


def _import_selected_parts(session: dict[str, object]) -> int:
    selected = _import_selected_topics(session)
    total = 0
    for item in selected:
        msg_ids = item.get("msg_ids")
        if isinstance(msg_ids, list):
            total += len(msg_ids)
    return total


def _import_total_parts(session: dict[str, object]) -> int:
    topics = session.get("topics") or []
    total = 0
    for item in topics:
        msg_ids = item.get("msg_ids")
        if isinstance(msg_ids, list):
            total += len(msg_ids)
    return total


def _import_has_counts(session: dict[str, object]) -> bool:
    topics = session.get("topics") or []
    for item in topics:
        if isinstance(item.get("msg_ids"), list):
            return True
    return False


def _render_import_selection_text(session: dict[str, object], page: int, per_page: int) -> str:
    topics = session.get("topics") or []
    total = len(topics)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    start = page * per_page
    end = start + per_page
    excluded = session.get("excluded") or set()
    selected = total - len(excluded)
    has_counts = _import_has_counts(session)
    selected_parts = _import_selected_parts(session)
    lines = [
        "Import tanlash:",
        f"Tanlangan mavzular: {selected}/{total} | Qismlar: {selected_parts if has_counts else '?'}",
        f"Sahifa: {page + 1}/{total_pages}",
        "",
    ]
    for idx, item in enumerate(topics[start:end], start=start + 1):
        title = _shorten_label(item["title"], 40)
        msg_ids = item.get("msg_ids")
        count = len(msg_ids) if isinstance(msg_ids, list) else None
        mark = "✅" if idx not in excluded else "❌"
        count_text = f"{count} qism" if count is not None else "? qism"
        lines.append(f"{mark} {idx}) {title} ({count_text})")
    return "\n".join(lines)


def _import_selection_keyboard(session: dict[str, object], page: int, per_page: int):
    topics = session.get("topics") or []
    total = len(topics)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    start = page * per_page
    end = start + per_page
    excluded = session.get("excluded") or set()
    kb = InlineKeyboardBuilder()
    for idx, item in enumerate(topics[start:end], start=start + 1):
        title = _shorten_label(item["title"], 24)
        mark = "✅" if idx not in excluded else "❌"
        kb.button(
            text=f"{mark} {idx}. {title}",
            callback_data=f"import:toggle:{idx}",
        )
    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(("⬅️", f"import:page:{page - 1}"))
        nav.append((f"{page + 1}/{total_pages}", "import:noop"))
        if page + 1 < total_pages:
            nav.append(("➡️", f"import:page:{page + 1}"))
        for text, data in nav:
            kb.button(text=text, callback_data=data)
    kb.button(text="Hammasini tanlash", callback_data="import:selectall")
    kb.button(text="Hammasini bekor qilish", callback_data="import:selectnone")
    kb.button(text="Tasdiqlash", callback_data="import:confirm")
    kb.button(text="Bekor qilish", callback_data="import:cancel")
    kb.adjust(1)
    return kb.as_markup()


def _import_confirm_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Ha", callback_data="import:apply")
    kb.button(text="⬅️ Ortga", callback_data="import:back")
    kb.button(text="❌ Bekor qilish", callback_data="import:cancel")
    kb.adjust(1)
    return kb.as_markup()


def _progress_bar(percent: int, width: int = 10) -> str:
    percent = max(0, min(100, percent))
    filled = int(round((percent / 100) * width))
    return f"{'█' * filled}{'░' * (width - filled)}"


def _progress_spinner(step: int) -> str:
    frames = ["⏳", "🔄", "⌛", "🔁"]
    return frames[step % len(frames)]


def _coerce_message_id(value: object) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if hasattr(value, "id"):
        try:
            return int(getattr(value, "id"))
        except Exception:
            return None
    return None


async def _click_bot_cancel_button(client, bot_entity) -> bool:
    try:
        messages = await client.get_messages(bot_entity, limit=5)
    except Exception:
        return False
    for msg in messages:
        if not msg or not getattr(msg, "message", ""):
            continue
        if "Davom ettirasizmi" not in msg.message:
            continue
        buttons = getattr(msg, "buttons", None)
        if not buttons:
            continue
        for row in buttons:
            for button in row:
                if not button or not getattr(button, "text", ""):
                    continue
                if "Bekor" not in button.text:
                    continue
                data = getattr(button, "data", None)
                if not data:
                    continue
                await client(
                    GetBotCallbackAnswerRequest(
                        peer=bot_entity,
                        msg_id=msg.id,
                        data=data,
                    )
                )
                return True
    return False


def _format_eta(seconds: float) -> str:
    if seconds < 0:
        return "?"
    total = int(seconds)
    mins, sec = divmod(total, 60)
    hours, mins = divmod(mins, 60)
    if hours:
        return f"{hours}so {mins}daqiqa"
    if mins:
        return f"{mins}daqiqa {sec}s"
    return f"{sec}s"


async def _copy_source_to_channel(
    message: Message,
    client,
    source_chat_id: int,
    source_message_id: int,
    bot_in_group: bool,
    source_msg=None,
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    async def _bot_copy(chat_id: int, from_chat_id: int, msg_id: int) -> Message:
        while True:
            try:
                return await message.bot.copy_message(chat_id, from_chat_id, msg_id)
            except TelegramRetryAfter as err:
                await _wait_retry(err)
    if bot_in_group:
        copied = await _bot_copy(SOURCE_CHANNEL_ID, source_chat_id, source_message_id)
        return _extract_media(copied)
    while True:
        try:
            if source_msg is None:
                source_msg = await client.get_messages(source_chat_id, ids=source_message_id)
                if isinstance(source_msg, list):
                    source_msg = source_msg[0] if source_msg else None
            try:
                media = getattr(source_msg, "media", None) if source_msg else None
                caption = _strip_links(getattr(source_msg, "message", "") or "")
            except Exception:
                return None, None, None
            if not media:
                return None, None, None
            forwarded_msg = await client.send_file(
                SOURCE_CHANNEL_ID,
                media,
                caption=caption,
                supports_streaming=True,
            )
            break
        except FloodWaitError as err:
            await asyncio.sleep(err.seconds + 1)
    copied = await _bot_copy(SOURCE_CHANNEL_ID, SOURCE_CHANNEL_ID, forwarded_msg.id)
    return _extract_media(copied)


async def _run_forum_import(message: Message, group_ref: str) -> None:
    user_id = message.from_user.id
    reply_chat_id = message.chat.id
    try:
        if not SOURCE_CHANNEL_ID:
            await message.bot.send_message(reply_chat_id, "SOURCE_CHANNEL_ID sozlanmagan.")
            return
        try:
            client = await get_userbot_client()
        except UserbotError as err:
            await message.bot.send_message(reply_chat_id, str(err))
            return
        try:
            entity = await client.get_entity(group_ref)
        except Exception:
            await message.bot.send_message(reply_chat_id, "Guruh topilmadi yoki userbotda yo'q.")
            return
        if not getattr(entity, "forum", False):
            await message.bot.send_message(reply_chat_id, "Bu guruh mavzuli emas.")
            return
        chat_id = get_peer_id(entity)
        if IMPORT_GROUP_ID and chat_id != IMPORT_GROUP_ID:
            await message.bot.send_message(reply_chat_id, "Ushbu guruh import uchun ruxsat etilmagan.")
            return
        bot_in_group = await _bot_in_chat(message.bot, chat_id)
        status = await message.bot.send_message(reply_chat_id, "Import skan boshlandi...")
        topics = await _fetch_forum_topics(client, entity)
        if not topics:
            await status.edit_text("Mavzular topilmadi.")
            return
        preview = topics
        total_topics = len(preview)
        total_parts = 0
        IMPORT_SESSIONS[user_id] = {
            "state": "select",
            "group_ref": group_ref,
            "chat_id": chat_id,
            "topics": preview,
            "total_parts": total_parts,
            "excluded": set(),
            "page": 0,
            "reply_chat_id": reply_chat_id,
            "status_message_id": status.message_id,
        }
        await status.edit_text(
            _render_import_selection_text(IMPORT_SESSIONS[user_id], 0, 8),
            reply_markup=_import_selection_keyboard(IMPORT_SESSIONS[user_id], 0, 8),
        )
        _log_event(
            "forum_import_preview",
            user_id,
            f"topics={len(preview)} parts={total_parts}",
        )
    finally:
        IMPORT_TASKS.pop(user_id, None)


async def _apply_forum_import(message: Message, session: dict[str, object]) -> None:
    user_id = message.from_user.id
    try:
        group_ref = session.get("group_ref")
        chat_id = int(session.get("chat_id") or 0)
        topics = session.get("selected_topics") or []
        total_parts = int(session.get("selected_parts") or 0)
        status_id = session.get("status_message_id")
        reply_chat_id = int(session.get("reply_chat_id") or message.chat.id)
        if not group_ref or not chat_id or not topics:
            await message.bot.send_message(reply_chat_id, "Import sessiya noto'g'ri.")
            return
        client = await get_userbot_client()
        entity = await client.get_entity(group_ref)
        bot_me = await message.bot.get_me()
        if not bot_me.username:
            await message.bot.send_message(reply_chat_id, "Bot username topilmadi.")
            return
        bot_entity = await client.get_entity(bot_me.username)
        bot_in_group = await _bot_in_chat(message.bot, chat_id)
        status = None
        if status_id:
            try:
                status = await message.bot.edit_message_text(
                    "Import boshlandi...",
                    reply_chat_id,
                    status_id,
                )
            except Exception:
                status = None
        if not status:
            status = await message.bot.send_message(reply_chat_id, "Import boshlandi...")
        added_topics: list[str] = []
        processed = 0
        total_topics = len(topics)
        processed_topics = 0
        last_edit = time.monotonic()
        spinner_step = 0
        started_at = time.monotonic()
        await message.bot.send_message(
            reply_chat_id,
            "Import bot orqali qo'shish rejimida ketadi. Userbot admin bo'lishi kerak.",
        )

        topic_counts: list[dict[str, object]] = []
        scan_idx = 0
        total_parts = 0
        for topic in topics:
            title = topic["title"]
            count = 0
            try:
                async for msg in client.iter_messages(entity, reply_to=topic["topic_id"], reverse=True):
                    if not (msg.video or msg.document):
                        continue
                    if getattr(msg, "gif", False):
                        continue
                    if msg.document and getattr(msg.document, "mime_type", "") == "image/gif":
                        continue
                    if serial_part_source_exists(chat_id, msg.id):
                        continue
                    if _coerce_message_id(msg) is None:
                        continue
                    count += 1
            except Exception as exc:
                _log_event(
                    "forum_import_scan_error",
                    user_id,
                    f"topic_id={topic['topic_id']} error={exc}",
                )
            if count:
                topic_counts.append(
                    {
                        "topic_id": topic["topic_id"],
                        "title": title,
                        "count": count,
                    }
                )
                total_parts += count
            scan_idx += 1
            now = time.monotonic()
            if now - last_edit > 1.5:
                spinner = _progress_spinner(spinner_step)
                spinner_step += 1
                try:
                    await status.edit_text(
                        f"{spinner} Skan ketmoqda:\n"
                        f"Mavzular: {scan_idx}/{total_topics}"
                    )
                except Exception:
                    pass
                last_edit = now

        if not topic_counts:
            await status.edit_text("Import tugadi. Yangi qismlar qo'shilmadi.")
            return

        topics = topic_counts
        processed_topics = 0
        last_edit = time.monotonic()
        spinner_step = 0
        started_at = time.monotonic()
        for topic in topics:
            title = topic["title"]
            added = 0
            try:
                await client.send_message(bot_entity, "/addserial")
                await asyncio.sleep(0.4)
                await client.send_message(bot_entity, title)
                await asyncio.sleep(0.4)
            except Exception as exc:
                _log_event(
                    "forum_import_botflow_error",
                    user_id,
                    f"stage=addserial title={title} error={exc}",
                )
                processed_topics += 1
                continue
            try:
                processed_in_topic = 0
                async for msg in client.iter_messages(entity, reply_to=topic["topic_id"], reverse=True):
                    msg_id = _coerce_message_id(msg)
                    if msg_id is None:
                        continue
                    try:
                        has_media = bool(getattr(msg, "video", None) or getattr(msg, "document", None))
                        is_gif = bool(getattr(msg, "gif", False))
                        is_doc_gif = bool(
                            getattr(getattr(msg, "document", None), "mime_type", "") == "image/gif"
                        )
                    except Exception:
                        continue
                    if not has_media or is_gif or is_doc_gif:
                        continue
                    if serial_part_source_exists(chat_id, msg.id):
                        continue
                    processed_in_topic += 1
                    caption = _strip_links(getattr(msg, "message", "") or "")
                    await client.send_file(
                        bot_entity,
                        msg.media,
                        caption=caption or None,
                        supports_streaming=True,
                    )
                    await asyncio.sleep(0.3)
                    added += 1
                processed += processed_in_topic
            except Exception as exc:
                _log_event(
                    "forum_import_apply_error",
                    user_id,
                    f"chat_id={chat_id} topic_id={topic['topic_id']} error={exc}",
                )
                if processed % 20 == 0 or processed == total_parts:
                    now = time.monotonic()
                    if now - last_edit > 2.0:
                        parts_percent = int((processed / total_parts) * 100)
                        topics_percent = int((processed_topics / total_topics) * 100) if total_topics else 100
                        elapsed = time.monotonic() - started_at
                        rate = processed / elapsed if elapsed > 0 else 0
                        remaining = (total_parts - processed) / rate if rate > 0 else -1
                        spinner = _progress_spinner(spinner_step)
                        spinner_step += 1
                        try:
                            await status.edit_text(
                                f"{spinner} Import ketmoqda:\n"
                                f"Mavzular: {topics_percent}% {_progress_bar(topics_percent)} "
                                f"({processed_topics}/{total_topics})\n"
                                f"Qismlar: {parts_percent}% {_progress_bar(parts_percent)} "
                                f"({processed}/{total_parts})\n"
                                f"Qolgan vaqt: {_format_eta(remaining)}"
                            )
                        except Exception:
                            pass
                        last_edit = now
            if added:
                added_topics.append(title)
            processed_topics += 1
            cancelled = False
            for _ in range(10):
                try:
                    if await _click_bot_cancel_button(client, bot_entity):
                        cancelled = True
                        break
                except Exception:
                    pass
                await asyncio.sleep(0.5)
            if not cancelled:
                try:
                    await client.send_message(bot_entity, "/serialcancel")
                except Exception:
                    pass
            now = time.monotonic()
            if now - last_edit > 2.0:
                parts_percent = int((processed / total_parts) * 100)
                topics_percent = int((processed_topics / total_topics) * 100) if total_topics else 100
                elapsed = time.monotonic() - started_at
                rate = processed / elapsed if elapsed > 0 else 0
                remaining = (total_parts - processed) / rate if rate > 0 else -1
                spinner = _progress_spinner(spinner_step)
                spinner_step += 1
                try:
                    await status.edit_text(
                        f"{spinner} Import ketmoqda:\n"
                        f"Mavzular: {topics_percent}% {_progress_bar(topics_percent)} "
                        f"({processed_topics}/{total_topics})\n"
                        f"Qismlar: {parts_percent}% {_progress_bar(parts_percent)} "
                        f"({processed}/{total_parts})\n"
                        f"Qolgan vaqt: {_format_eta(remaining)}"
                    )
                except Exception:
                    pass
                last_edit = now
        if not added_topics:
            await status.edit_text("Import tugadi. Yangi qismlar qo'shilmadi.")
            return
        lines = ["Import tugadi. Qo'shilgan dramalar:"]
        lines.extend(f"- {title}" for title in added_topics)
        for chunk in _chunk_lines(lines):
            await message.bot.send_message(reply_chat_id, chunk)
        _log_event(
            "forum_import_done",
            user_id,
            f"topics={len(added_topics)} parts={processed}",
        )
        try:
            await asyncio.sleep(5)
            await client.send_message(bot_entity, "/importstop")
        except Exception:
            pass
    finally:
        IMPORT_SESSIONS.pop(user_id, None)
        IMPORT_TASKS.pop(user_id, None)


async def _ensure_vip_access(message: Message, serial: dict, user_id: Optional[int] = None) -> bool:
    if user_id is None:
        user_id = message.from_user.id
    if _is_admin_user(user_id):
        return True
    if not serial.get("is_vip"):
        return True
    if _is_vip_user(user_id):
        return True
    _log_event(
        "vip_access_denied",
        user_id,
        f"serial_id={serial.get('id')} is_vip={serial.get('is_vip')}",
    )
    await _send_vip_required(message, headline="Bu drama VIP.")
    return False


async def _ensure_serial_access(
    message: Message,
    serial: dict,
    user_id: Optional[int] = None,
) -> bool:
    return await ensure_subscribed(message, user_id=user_id)


def _cleanup_restore_session(user_id: int) -> None:
    session = RESTORE_DB_SESSIONS.pop(user_id, None)
    if not session:
        return
    for path in session.get("cleanup", []):
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
        except Exception:
            pass

router = Router()

# Sub-routers
from app.handlers_vip import router as vip_router

router.include_router(vip_router)
LOG_TAIL_LINES = 40
LOG_MAX_BYTES = 10 * 1024 * 1024
LOG_BACKUP_COUNT = 3
BACKUP_KEEP = 7


@router.message(
    lambda message: (
        message
        and message.from_user
        and message.from_user.id in ADMIN_USER_MESSAGE_SESSIONS
    )
)
async def admin_user_message_handler(message: Message):
    if not _has_perm(message.from_user.id, "can_broadcast"):
        ADMIN_USER_MESSAGE_SESSIONS.pop(message.from_user.id, None)
        return
    session = ADMIN_USER_MESSAGE_SESSIONS.pop(message.from_user.id, None)
    if not session:
        return
    target_id = session.get("user_id")
    if not target_id:
        return
    if is_blocked_user(int(target_id)):
        await message.answer("Foydalanuvchi bloklangan.")
        return
    try:
        await message.copy_to(int(target_id))
    except Exception:
        await message.answer("Xabar yuborilmadi.")
        return
    await message.answer("Yuborildi.")


async def _get_missing_subscriptions(bot, user_id: int, channels: list) -> list[dict]:
    missing = []
    for channel in channels:
        chat_id = int(channel["chat_id"])
        try:
            member = await bot.get_chat_member(chat_id, user_id)
        except Exception:
            if has_join_request(chat_id, user_id):
                continue
            missing.append(channel)
            continue
        if member.status in {ChatMemberStatus.LEFT, ChatMemberStatus.KICKED}:
            if has_join_request(chat_id, user_id):
                continue
            missing.append(channel)
    return missing


async def _is_group_admin(message: Message) -> bool:
    if not message or not message.from_user:
        return False
    if message.chat.type not in {"group", "supergroup"}:
        return False
    try:
        member = await message.bot.get_chat_member(message.chat.id, message.from_user.id)
    except Exception:
        return False
    return member.status in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}


async def _get_bot_member(message: Message):
    try:
        me = await message.bot.get_me()
        return await message.bot.get_chat_member(message.chat.id, me.id)
    except Exception:
        return None


async def _is_bot_admin_in_group(message: Message) -> bool:
    if message.chat.type not in {"group", "supergroup"}:
        return False
    member = await _get_bot_member(message)
    if not member:
        return False
    return member.status in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}


async def _maybe_restrict_group_spam(message: Message) -> bool:
    if message.chat.type not in {"group", "supergroup"}:
        return False
    if not message.from_user:
        return False
    try:
        user_member = await message.bot.get_chat_member(message.chat.id, message.from_user.id)
    except Exception:
        return False
    if user_member.status in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}:
        return False
    now = time.time()
    key = (int(message.chat.id), int(message.from_user.id))
    timestamps = GROUP_SPAM_TRACKER.setdefault(key, deque())
    while timestamps and now - timestamps[0] > GROUP_SPAM_WINDOW:
        timestamps.popleft()
    timestamps.append(now)
    if len(timestamps) < GROUP_SPAM_LIMIT:
        return False
    bot_member = await _get_bot_member(message)
    if not bot_member:
        return False
    if bot_member.status not in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}:
        return False
    can_restrict = getattr(bot_member, "can_restrict_members", False)
    if not can_restrict:
        return False
    until = dt.datetime.utcnow() + dt.timedelta(seconds=GROUP_MUTE_SECONDS)
    try:
        await message.bot.restrict_chat_member(
            message.chat.id,
            message.from_user.id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until,
        )
        return True
    except Exception:
        return False


async def ensure_subscribed(message: Message, user_id: Optional[int] = None) -> bool:
    if user_id is None:
        user_id = message.from_user.id
    if message.chat.type in {"group", "supergroup"}:
        return True
    if _is_admin_user(user_id):
        return True
    if _is_vip_user(user_id):
        return True
    if await _is_group_admin(message):
        return True
    channels = get_channels()
    if not channels:
        return True
    missing = await _get_missing_subscriptions(message.bot, user_id, channels)
    if missing:
        try:
            await message.answer(
                "Iltimos, quyidagi kanallarga obuna bo'ling.",
                reply_markup=subscribe_keyboard(missing),
            )
        except TelegramForbiddenError:
            block_user(user_id, _now())
            _log_event("bot_blocked", user_id, "ensure_subscribed")
        return False
    return True


async def ensure_subscribed_callback(callback: CallbackQuery) -> bool:
    if _is_admin_user(callback.from_user.id):
        return True
    if _is_vip_user(callback.from_user.id):
        return True
    channels = get_channels()
    if not channels:
        return True
    missing = await _get_missing_subscriptions(callback.bot, callback.from_user.id, channels)
    if missing:
        try:
            await callback.message.answer(
                "Iltimos, quyidagi kanallarga obuna bo'ling.",
                reply_markup=subscribe_keyboard(missing),
            )
        except TelegramForbiddenError:
            block_user(callback.from_user.id, _now())
            _log_event("bot_blocked", callback.from_user.id, "ensure_subscribed_callback")
        return False
    return True


@router.callback_query(F.data == "check_subs")
async def check_subs_callback(callback: CallbackQuery):
    channels = get_channels()
    missing = await _get_missing_subscriptions(callback.bot, callback.from_user.id, channels)
    if not missing:
        pending = _get_pending_start(callback.from_user.id)
        if pending:
            pending_code, pending_part = pending
            _clear_pending_start(callback.from_user.id)
            serial = get_serial_by_code(int(pending_code))
            if serial:
                if pending_part:
                    if await _send_serial_part(
                        callback.message,
                        serial["id"],
                        int(pending_part),
                        user_id=callback.from_user.id,
                    ):
                        await callback.message.edit_text("Obuna tasdiqlandi.")
                        return
                elif await _show_serial_parts_for_user(callback.message, serial["id"], user_id=callback.from_user.id):
                    await callback.message.edit_text("Obuna tasdiqlandi.")
                    return
            await callback.message.edit_text("Obuna tasdiqlandi. Drama topilmadi.")
            return
        await callback.message.edit_text("Obuna tasdiqlandi. Drama kodini yuboring.")
    else:
        try:
            await callback.message.edit_text(
                "Hali obuna emassiz.",
                reply_markup=subscribe_keyboard(missing),
            )
        except:
            pass


@router.callback_query(F.data == "user:sendcode")
async def user_send_code_callback(callback: CallbackQuery):
    if is_admin(callback.from_user.id) and get_serial_session(callback.from_user.id):
        clear_serial_session(callback.from_user.id)
    await callback.message.edit_text("Drama kodini yuboring.")


@router.callback_query(F.data == "user:contact")
async def user_contact_callback(callback: CallbackQuery):
    if not await ensure_subscribed_callback(callback):
        return
    CONTACT_ADMIN_SESSIONS.add(callback.from_user.id)
    await callback.message.answer(
        "Adminlarga yuboriladigan xabarni yozing. Bekor qilish: Bekor",
        reply_markup=contact_admin_keyboard(),
    )


@router.message(Command("contact"))
async def user_contact_command(message: Message):
    if not await ensure_subscribed(message):
        return
    CONTACT_ADMIN_SESSIONS.add(message.from_user.id)
    await message.answer(
        "Adminlarga yuboriladigan xabarni yozing. Bekor qilish: Bekor",
        reply_markup=contact_admin_keyboard(),
    )


async def _forward_user_message_to_admins(message: Message, reason: str) -> None:
    admins = get_admins()
    if OWNER_ID and OWNER_ID not in admins:
        admins.append(OWNER_ID)
    username = f"@{message.from_user.username}" if message.from_user.username else "-"
    full_name = " ".join(
        part for part in [message.from_user.first_name, message.from_user.last_name] if part
    )
    name_text = full_name if full_name else "-"
    header = (
        "Foydalanuvchi xabari:\n"
        f"user_id: {message.from_user.id}\n"
        f"username: {username}\n"
        f"name: {name_text}\n"
        f"sabab: {reason}"
    )
    for admin_id in admins:
        try:
            header_msg = await message.bot.send_message(admin_id, header)
            _remember_contact_reply(admin_id, header_msg.message_id, message.from_user.id)
            copied = await message.copy_to(admin_id)
            _remember_contact_reply(admin_id, copied.message_id, message.from_user.id)
        except Exception:
            continue


@router.callback_query(F.data == "user:serials")
async def user_serials_callback(callback: CallbackQuery):
    if not await ensure_subscribed_callback(callback):
        return
    await _render_user_serials_page(callback, page=0, sort_key="az")


@router.callback_query(F.data == "user:toplikes")
async def user_toplikes_callback(callback: CallbackQuery):
    if not await ensure_subscribed_callback(callback):
        return
    include_vip = _include_vip_serials(callback.from_user.id)
    top = get_top_liked_serials(20, include_vip)
    if not top:
        await _safe_edit_or_answer(callback.message, "Dramalar yo'q.")
        return
    serials = [
        {"id": item["id"], "code": item["code"], "title": item["title"], "is_vip": item["is_vip"]}
        for item in top
    ]
    lines = ["Top dramalar:"]
    for idx, item in enumerate(top, start=1):
        title = _pretty_title_text(item.get("title") or "-")
        likes = int(item.get("likes") or 0)
        lines.append(f"{idx}. {title} ({likes})")
    text = "\n".join(lines)
    await _safe_edit_or_answer(
        callback.message,
        text,
        reply_markup=user_serials_keyboard(serials, page=0, total_pages=1, sort_key="top"),
    )


@router.callback_query(F.data == "user:search")
async def user_search_callback(callback: CallbackQuery):
    if not await ensure_subscribed_callback(callback):
        return
    USER_SEARCH_SESSIONS.add(callback.from_user.id)
    USER_SEARCH_RESULTS.pop(callback.from_user.id, None)
    await callback.message.answer("Drama nomini yozing:", reply_markup=user_search_keyboard())


@router.callback_query(F.data == "user:search_cancel")
async def user_search_cancel_callback(callback: CallbackQuery):
    USER_SEARCH_SESSIONS.discard(callback.from_user.id)
    USER_SEARCH_RESULTS.pop(callback.from_user.id, None)
    await callback.message.edit_text(
        "Bekor qilindi.",
        reply_markup=user_keyboard(),
    )


@router.callback_query(F.data.startswith("user:searchpage:"))
async def user_search_page_callback(callback: CallbackQuery):
    if not await ensure_subscribed_callback(callback):
        return
    results = USER_SEARCH_RESULTS.get(callback.from_user.id) or []
    if not results:
        await callback.answer("Natija topilmadi.", show_alert=True)
        return
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("Xatolik.", show_alert=True)
        return
    try:
        page = int(parts[2])
    except ValueError:
        await callback.answer("Xatolik.", show_alert=True)
        return
    await _render_user_search_results(callback, results, page)


@router.callback_query(F.data.startswith("user:searchserial:"))
async def user_search_serial_callback(callback: CallbackQuery):
    if not await ensure_subscribed_callback(callback):
        return
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Xatolik.", show_alert=True)
        return
    try:
        serial_id = int(parts[2])
    except ValueError:
        await callback.answer("Xatolik.", show_alert=True)
        return
    serial = get_serial_by_id(serial_id)
    if not serial:
        await callback.answer("Drama topilmadi.", show_alert=True)
        return
    if not await _ensure_serial_access(callback.message, serial, user_id=callback.from_user.id):
        return
    USER_SEARCH_RESULTS.pop(callback.from_user.id, None)
    ok = await _show_serial_parts(callback.message, serial["id"])
    if not ok:
        await callback.answer("Dramada qismlar yo'q.", show_alert=True)


@router.callback_query(F.data.startswith("user:serials:"))
async def user_serials_page_callback(callback: CallbackQuery):
    if not await ensure_subscribed_callback(callback):
        return
    parts = callback.data.split(":")
    sort_key = "az"
    page = 0
    if len(parts) == 3:
        try:
            page = int(parts[2])
        except ValueError:
            await callback.answer("Xatolik.", show_alert=True)
            return
    elif len(parts) == 4:
        sort_key = parts[2]
        try:
            page = int(parts[3])
        except ValueError:
            await callback.answer("Xatolik.", show_alert=True)
            return
    else:
        await callback.answer("Xatolik.", show_alert=True)
        return
    await _render_user_serials_page(callback, page=page, sort_key=sort_key)


@router.callback_query(F.data.startswith("user:serial:"))
async def user_serial_callback(callback: CallbackQuery):
    if not await ensure_subscribed_callback(callback):
        return
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Xatolik.", show_alert=True)
        return
    try:
        serial_id = int(parts[2])
    except ValueError:
        await callback.answer("Xatolik.", show_alert=True)
        return
    serial = get_serial_by_id(serial_id)
    if not serial:
        await callback.answer("Drama topilmadi.", show_alert=True)
        return
    if not await _ensure_serial_access(callback.message, serial, user_id=callback.from_user.id):
        return
    ok = await _show_serial_parts(callback.message, serial["id"])
    if not ok:
        await callback.answer("Dramada qismlar yo'q.", show_alert=True)


@router.callback_query(F.data.startswith("user:rate:"))
async def user_like_toggle_callback(callback: CallbackQuery):
    if not await ensure_subscribed_callback(callback):
        return
    parts = callback.data.split(":")
    if len(parts) not in {4, 5}:
        await callback.answer()
        return
    try:
        value = int(parts[2])
        serial_id = int(parts[3])
        current_part = int(parts[4]) if len(parts) == 5 else None
    except ValueError:
        await callback.answer()
        return
    serial = get_serial_by_id(serial_id)
    if not serial:
        await callback.answer()
        return
    if not await _ensure_serial_access(callback.message, serial, user_id=callback.from_user.id):
        return
    set_serial_rating(callback.from_user.id, serial_id, value)
    part_numbers, vip_parts = _serial_part_numbers_for_keyboard(serial_id)
    if not part_numbers:
        await callback.answer()
        return
    likes_count, dislikes_count = get_serial_rating_counts(serial_id)
    if current_part is not None:
        reply_markup = serial_nav_keyboard(
            serial_id,
            part_numbers,
            current_part=current_part,
            part_link_prefix=None,
            show_rating=True,
            notify_enabled=_is_serial_notify_enabled(callback.from_user.id, serial_id),
            rating=get_serial_rating(callback.from_user.id, serial_id),
            likes_count=likes_count,
            dislikes_count=dislikes_count,
        )
    else:
        share_link = await _get_share_link(
            callback.message.bot,
            int(serial.get("code")),
            serial.get("title") or "",
            len(part_numbers),
        )
        reply_markup = serial_parts_keyboard(
            serial_id,
            part_numbers,
            page=0,
            per_page=SERIAL_PARTS_PER_PAGE,
            vip_parts=vip_parts,
            share_link=share_link,
            notify_enabled=_is_serial_notify_enabled(callback.from_user.id, serial_id),
            rating=get_serial_rating(callback.from_user.id, serial_id),
            likes_count=likes_count,
            dislikes_count=dislikes_count,
        )
    await _safe_edit_reply_markup(
        callback.message.bot,
        callback.message.chat.id,
        callback.message.message_id,
        reply_markup,
    )
    _schedule_inline_expire(
        callback.message.bot,
        callback.message.chat.id,
        callback.message.message_id,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("user:like:"))
async def user_like_legacy_callback(callback: CallbackQuery):
    if not await ensure_subscribed_callback(callback):
        return
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer()
        return
    try:
        serial_id = int(parts[2])
    except ValueError:
        await callback.answer()
        return
    serial = get_serial_by_id(serial_id)
    if not serial:
        await callback.answer()
        return
    if not await _ensure_serial_access(callback.message, serial, user_id=callback.from_user.id):
        return
    set_serial_rating(callback.from_user.id, serial_id, 1)
    part_numbers, vip_parts = _serial_part_numbers_for_keyboard(serial_id)
    if not part_numbers:
        await callback.answer()
        return
    likes_count, dislikes_count = get_serial_rating_counts(serial_id)
    share_link = await _get_share_link(
        callback.message.bot,
        int(serial.get("code")),
        serial.get("title") or "",
        len(part_numbers),
    )
    reply_markup = serial_parts_keyboard(
        serial_id,
        part_numbers,
        page=0,
        per_page=SERIAL_PARTS_PER_PAGE,
        vip_parts=vip_parts,
        share_link=share_link,
        notify_enabled=_is_serial_notify_enabled(callback.from_user.id, serial_id),
        rating=get_serial_rating(callback.from_user.id, serial_id),
        likes_count=likes_count,
        dislikes_count=dislikes_count,
    )
    await _safe_edit_reply_markup(
        callback.message.bot,
        callback.message.chat.id,
        callback.message.message_id,
        reply_markup,
    )
    _schedule_inline_expire(
        callback.message.bot,
        callback.message.chat.id,
        callback.message.message_id,
    )
    await callback.answer()


@router.callback_query(F.data == "noop")
async def noop_callback(callback: CallbackQuery):
    await callback.answer()


@router.callback_query(F.data.startswith("serialpart:"))
async def serial_part_callback(callback: CallbackQuery):
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Xatolik.", show_alert=True)
        return
    try:
        serial_id = int(parts[1])
        part = int(parts[2])
    except ValueError:
        await callback.answer("Xatolik.", show_alert=True)
        return
    serial = get_serial_by_id(serial_id)
    if not serial:
        await callback.answer("Drama topilmadi.", show_alert=True)
        return
    if not await _ensure_serial_access(callback.message, serial, user_id=callback.from_user.id):
        return
    ok = await _send_serial_part(callback.message, serial_id, part, user_id=callback.from_user.id)
    if not ok:
        await callback.answer()
        return
    _cancel_inline_expire(callback.message.chat.id, callback.message.message_id)
    await _safe_edit_reply_markup(
        callback.message.bot,
        callback.message.chat.id,
        callback.message.message_id,
        None,
    )
    _log_event("serial_part_sent", callback.from_user.id, f"serial_id={serial_id} part={part}")


@router.callback_query(F.data.startswith("serialpage:"))
async def serial_page_callback(callback: CallbackQuery):
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Xatolik.", show_alert=True)
        return
    try:
        serial_id = int(parts[1])
        page = int(parts[2])
    except ValueError:
        await callback.answer("Xatolik.", show_alert=True)
        return
    serial = get_serial_by_id(serial_id)
    if not serial:
        await callback.answer("Drama topilmadi.", show_alert=True)
        return
    if not await _ensure_serial_access(callback.message, serial, user_id=callback.from_user.id):
        return
    part_numbers, vip_parts = _serial_part_numbers_for_keyboard(serial_id)
    if not part_numbers:
        await callback.answer("Dramada qismlar yo'q.", show_alert=True)
        return
    rating = get_serial_rating(callback.from_user.id, serial_id)
    likes_count, dislikes_count = get_serial_rating_counts(serial_id)
    await _safe_edit_or_answer(
        callback.message,
        f"{_pretty_title_text(serial['title'])} qismlari:",
        reply_markup=serial_parts_keyboard(
            serial_id,
            part_numbers,
            page=page,
            per_page=SERIAL_PARTS_PER_PAGE,
            vip_parts=vip_parts,
            notify_enabled=_is_serial_notify_enabled(callback.from_user.id, serial_id),
            rating=rating,
            likes_count=likes_count,
            dislikes_count=dislikes_count,
        ),
    )
    _schedule_inline_expire(
        callback.message.bot,
        callback.message.chat.id,
        callback.message.message_id,
    )


def _today() -> str:
    return dt.datetime.utcnow().date().isoformat()


def _serial_part_numbers_for_keyboard(serial_id: int) -> tuple[list[int], set[int]]:
    serial = get_serial_by_id(serial_id)
    all_parts = get_serial_parts(serial_id)
    return _serial_part_numbers_with_vip(serial, all_parts)


def _parse_code(raw: str) -> Optional[str]:
    value = raw.strip()
    if not value.isdigit():
        return None
    return str(int(value))


def _parse_start_payload(raw: str) -> tuple[Optional[int], Optional[int]]:
    value = (raw or "").strip()
    if not value:
        return None, None
    if "_" in value:
        parts = value.split("_", 1)
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            return int(parts[0]), int(parts[1])
    if value.isdigit():
        return int(value), None
    return None, None


def _parse_part(raw: str) -> Optional[int]:
    value = raw.strip()
    if not value.isdigit():
        return None
    part = int(value)
    return part if part > 0 else None


def _parse_target_user_id(raw: str) -> Optional[int]:
    value = (raw or "").strip()
    if not value:
        return None
    if value.isdigit():
        return int(value)
    return get_user_id_by_username(value)


def _now() -> str:
    return dt.datetime.utcnow().isoformat()


def _remember_pending_start(user_id: int, code: int, part: Optional[int]) -> None:
    PENDING_START_CODES[user_id] = (code, part, time.time())


def _clear_pending_start(user_id: int) -> None:
    PENDING_START_CODES.pop(user_id, None)


def _get_pending_start(user_id: int) -> Optional[tuple[int, Optional[int]]]:
    item = PENDING_START_CODES.get(user_id)
    if not item:
        return None
    code, part, ts = item
    if time.time() - ts > 86400:
        PENDING_START_CODES.pop(user_id, None)
        return None
    return code, part


def _pretty_title_text(title: str) -> str:
    clean = (title or "").strip()
    if not clean:
        return "🎬 DRAMA 🎬"
    return f"🎬 {clean.upper()} 🎬"


def _is_serial_notify_enabled(user_id: int, serial_id: int) -> bool:
    info = get_serial_notification(user_id, serial_id)
    if not info:
        return True
    return not bool(info.get("muted"))


def _broadcast_attach_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="Ha", callback_data="broadcastattach:yes")
    kb.button(text="Yo'q", callback_data="broadcastattach:no")
    kb.adjust(2)
    return kb.as_markup()


def _log_event(event: str, user_id: Optional[int] = None, detail: str = "") -> None:
    timestamp = dt.datetime.utcnow().isoformat()
    user_part = f"user_id={user_id}" if user_id is not None else "user_id=-"
    detail_part = detail.replace("\n", " ").strip()
    line = f"{timestamp} {event} {user_part}"
    if detail_part:
        line = f"{line} {detail_part}"
    log_dir = os.path.dirname(LOG_PATH)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
    _rotate_log_if_needed()
    with open(LOG_PATH, "a", encoding="utf-8") as handle:
        handle.write(f"{line}\n")


def _rotate_log_if_needed() -> None:
    if not os.path.exists(LOG_PATH):
        return
    try:
        if os.path.getsize(LOG_PATH) < LOG_MAX_BYTES:
            return
    except OSError:
        return
    oldest = f"{LOG_PATH}.{LOG_BACKUP_COUNT}"
    if os.path.exists(oldest):
        try:
            os.remove(oldest)
        except OSError:
            return
    for idx in range(LOG_BACKUP_COUNT - 1, 0, -1):
        src = f"{LOG_PATH}.{idx}"
        dst = f"{LOG_PATH}.{idx + 1}"
        if os.path.exists(src):
            try:
                os.replace(src, dst)
            except OSError:
                return
    try:
        os.replace(LOG_PATH, f"{LOG_PATH}.1")
    except OSError:
        return


def _tail_log(limit: int) -> list[str]:
    if not os.path.exists(LOG_PATH):
        return []
    lines = deque(maxlen=limit)
    with open(LOG_PATH, "r", encoding="utf-8") as handle:
        for line in handle:
            lines.append(line.rstrip("\n"))
    return list(lines)


def _tail_log_for_user(user_id: int, limit: int) -> list[str]:
    if not os.path.exists(LOG_PATH):
        return []
    lines = deque(maxlen=limit)
    needle = f"user_id={user_id}"
    with open(LOG_PATH, "r", encoding="utf-8") as handle:
        for line in handle:
            if needle in line:
                lines.append(line.rstrip("\n"))
    return list(lines)


def _extract_media(message: Message) -> tuple[Optional[str], Optional[str], Optional[str]]:
    if message.video:
        return message.video.file_id, "video", message.caption
    if message.document:
        if message.document.mime_type == "image/gif":
            return None, None, None
        return message.document.file_id, "document", message.caption
    return None, None, None


async def _wait_retry(err: TelegramRetryAfter) -> None:
    await asyncio.sleep(err.retry_after + 0.5)


async def _safe_edit_or_answer(message: Message, text: str, reply_markup=None) -> None:
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramAPIError:
        await message.answer(text, reply_markup=reply_markup)


async def _get_share_link(
    bot,
    serial_code: int,
    title: str,
    parts_count: int,
) -> Optional[str]:
    try:
        me = await bot.get_me()
    except Exception:
        return None
    if not me.username:
        return None
    target_url = f"https://t.me/{me.username}?start={serial_code}"
    text = (
        "Men sizga ushbu botni tavsiya qilaman. "
        f"Siz ushbu botda ushbu link orqali {title} dramasini "
        f"{parts_count} qismini ko'rishingiz mumkin. "
        "Dramalardan bahramand bo'ling."
    )
    share_url = (
        "https://t.me/share/url?"
        f"url={urllib.parse.quote(target_url)}"
        f"&text={urllib.parse.quote(text)}"
    )
    return share_url


async def _get_start_link(bot, serial_code: int) -> Optional[str]:
    try:
        me = await bot.get_me()
    except Exception:
        return None
    if not me.username:
        return None
    return f"https://t.me/{me.username}?start={serial_code}"


async def _get_start_link_with_payload(bot, payload: str) -> Optional[str]:
    try:
        me = await bot.get_me()
    except Exception:
        return None
    if not me.username:
        return None
    return f"https://t.me/{me.username}?start={payload}"


async def _get_start_group_link(bot) -> Optional[str]:
    try:
        me = await bot.get_me()
    except Exception:
        return None
    if not me.username:
        return None
    return f"https://t.me/{me.username}?startgroup=1"


def _build_serial_post_text(title: str, parts_count: int, link: str) -> str:
    return (
        f"Drama nomi: {title}\n"
        f"Qismlar soni: {parts_count}"
    )


def _build_new_drama_text(title: str, code: int) -> str:
    return f"Yangi drama: {title}\nKod: {code}"


def _build_new_part_text(title: str, code: int, part: int) -> str:
    return f"Yangi qism: {title}\nKod: {code}\nQism: {part}"


def _build_backup_zip() -> Optional[str]:
    timestamp = dt.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    backup_path = os.path.join("/tmp", f"serialbot-backup-{timestamp}.zip")
    files = []
    if os.path.exists(DB_PATH):
        files.append(DB_PATH)
    if os.path.exists(LOG_PATH):
        files.append(LOG_PATH)
    if not files:
        return None
    with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for file_path in files:
            archive.write(file_path, arcname=os.path.basename(file_path))
    return backup_path


def _build_scheduled_backup() -> Optional[str]:
    timestamp = dt.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    os.makedirs(BACKUP_DIR, exist_ok=True)
    backup_path = os.path.join(BACKUP_DIR, f"serialbot-backup-{timestamp}.zip")
    files = []
    if os.path.exists(DB_PATH):
        files.append(DB_PATH)
    if os.path.exists(LOG_PATH):
        files.append(LOG_PATH)
    if not files:
        return None
    with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for file_path in files:
            archive.write(file_path, arcname=os.path.basename(file_path))
    try:
        backups = [
            os.path.join(BACKUP_DIR, name)
            for name in os.listdir(BACKUP_DIR)
            if name.endswith(".zip")
        ]
        backups.sort(key=lambda path: os.path.getmtime(path), reverse=True)
        keep = 1
        for old_path in backups[keep:]:
            try:
                os.remove(old_path)
            except OSError:
                continue
    except OSError:
        pass
    return backup_path


async def _safe_copy_message(
    bot,
    chat_id: int,
    from_chat_id: int,
    message_id: int,
) -> Optional[Message]:
    while True:
        try:
            return await bot.copy_message(
                chat_id=chat_id,
                from_chat_id=from_chat_id,
                message_id=message_id,
                protect_content=True,
            )
        except TelegramRetryAfter as err:
            await _wait_retry(err)
        except TelegramAPIError:
            _log_event(
                "copy_message_error",
                None,
                f"from_chat_id={from_chat_id} message_id={message_id}",
            )
            return None


async def _safe_edit_reply_markup(bot, chat_id: int, message_id: int, reply_markup) -> None:
    try:
        await bot.edit_message_reply_markup(
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=reply_markup,
        )
    except TelegramAPIError:
        _log_event("edit_markup_error", None, f"chat_id={chat_id} message_id={message_id}")


async def _safe_send_video(
    message: Message,
    file_id: str,
    caption: Optional[str],
    reply_markup=None,
    reply_to_message_id: Optional[int] = None,
) -> Optional[Message]:
    while True:
        try:
            return await message.answer_video(
                file_id,
                caption=caption,
                protect_content=True,
                reply_markup=reply_markup,
                reply_to_message_id=reply_to_message_id,
            )
        except TelegramRetryAfter as err:
            await _wait_retry(err)
        except TelegramAPIError:
            _log_event(
                "send_video_error",
                message.from_user.id if message.from_user else None,
                f"file_id={file_id}",
            )
            return None


async def _safe_send_document(
    message: Message,
    file_id: str,
    caption: Optional[str],
    reply_markup=None,
    reply_to_message_id: Optional[int] = None,
) -> Optional[Message]:
    while True:
        try:
            return await message.answer_document(
                file_id,
                caption=caption,
                protect_content=True,
                reply_markup=reply_markup,
                reply_to_message_id=reply_to_message_id,
            )
        except TelegramRetryAfter as err:
            await _wait_retry(err)
        except TelegramAPIError:
            _log_event(
                "send_document_error",
                message.from_user.id if message.from_user else None,
                f"file_id={file_id}",
            )
            return None


async def _safe_send_video_to_user(
    bot,
    chat_id: int,
    file_id: str,
    caption: Optional[str],
    reply_markup=None,
) -> Optional[Message]:
    while True:
        try:
            return await bot.send_video(
                chat_id,
                file_id,
                caption=caption,
                protect_content=True,
                reply_markup=reply_markup,
            )
        except TelegramRetryAfter as err:
            await _wait_retry(err)
        except TelegramAPIError:
            _log_event(
                "send_video_error",
                None,
                f"chat_id={chat_id} file_id={file_id}",
            )
            return None


async def _safe_send_document_to_user(
    bot,
    chat_id: int,
    file_id: str,
    caption: Optional[str],
    reply_markup=None,
) -> Optional[Message]:
    while True:
        try:
            return await bot.send_document(
                chat_id,
                file_id,
                caption=caption,
                protect_content=True,
                reply_markup=reply_markup,
            )
        except TelegramRetryAfter as err:
            await _wait_retry(err)
        except TelegramAPIError:
            _log_event(
                "send_document_error",
                None,
                f"chat_id={chat_id} file_id={file_id}",
            )
            return None


async def _safe_send_to_channel(
    bot, chat_id: int, file_id: str, file_type: str, caption: Optional[str]
) -> Optional[Message]:
    while True:
        try:
            if file_type == "document":
                return await bot.send_document(chat_id, file_id, caption=caption)
            return await bot.send_video(chat_id, file_id, caption=caption)
        except TelegramRetryAfter as err:
            await _wait_retry(err)
        except TelegramAPIError:
            return None


@router.message(CommandStart())
async def start_handler(message: Message, command: CommandObject):
    full_name = " ".join(
        part
        for part in [message.from_user.first_name, message.from_user.last_name]
        if part
    ).strip()
    add_user(message.from_user.id, message.from_user.username, full_name or None)
    _log_event("user_start", message.from_user.id)
    if command.args:
        code, part = _parse_start_payload(command.args)
        if code:
            if not await ensure_subscribed(message):
                _remember_pending_start(message.from_user.id, int(code), part)
                return
            _clear_pending_start(message.from_user.id)
            serial = get_serial_by_code(int(code))
            if not serial:
                await message.answer("Drama topilmadi.")
                return
            if await _show_serial_parts(message, serial["id"]):
                return
            await message.answer("Drama topilmadi.")
            return
    if not await ensure_subscribed(message):
        return
    _clear_pending_start(message.from_user.id)
    banner = (
        "Qadrli dramshik sizni botimizda ko'rganimizdan xursandmiz 🙂\n"
        "O'zingizga kerakli qismni tanlab contentlardan bahramand bo'ling.\n\n"
        "Yordam uchun /help buyrug'idan foydalaning."
    )
    sent_menssage=await message.answer(banner, reply_markup=user_keyboard())
    if message.chat.type == "private":
        group_link = await _get_start_group_link(message.bot)
        if group_link:
            kb = InlineKeyboardBuilder()
            kb.button(text="Guruhga qo'shish", url=group_link)
            kb.adjust(1)
            await message.answer(
                "Guruhda foydalanish:\n"
                "- /drama <nom|kod> yuboring\n"
                "- drama haqida ma'lumot va qismlar tugmalari chiqadi",
                reply_markup=kb.as_markup(),
            )

    await asyncio.sleep(120)
    try:
        await sent_message.delete()
    except:
        pass


@router.message(F.new_chat_members)
async def bot_added_to_group_handler(message: Message):
    if message.chat.type not in {"group", "supergroup"}:
        return
    try:
        me = await message.bot.get_me()
    except Exception:
        return
    if not any(member.id == me.id for member in (message.new_chat_members or [])):
        return
    if not await _is_bot_admin_in_group(message):
        await message.answer(
            "Bot to'liq ishlashi uchun admin qilib qo'shing.",
        )


@router.message(Command("restoretest"))
async def restore_test(message: Message):

    if message.from_user.id != OWNER_ID:
        return

    await message.answer("Restore boshlandi...")

    try:
        result = await auto_restore_latest_backup(message.bot)

        if result:
            await message.answer("✅ Restore muvaffaqiyatli")
        else:
            await message.answer("❌ Backup topilmadi")
    except Exception as e:
        await message.answer(f"❌ Xato:\n{e}")
        raise
        

@router.message(Command("help"))
async def help_handler(message: Message):
    if not await ensure_subscribed(message):
        return
    if is_admin(message.from_user.id):
        lines = ["Buyruqlar:", "/admin - admin panel"]
        if _has_perm(message.from_user.id, "can_manage_admins"):
            lines.extend(
                [
                    "/addadmin <user_id> - admin qo'shish",
                    "/deladmin <user_id> - admin chiqarish",
                ]
            )
        if _has_perm(message.from_user.id, "can_view_lists"):
            lines.append("/admins - adminlar ro'yxati")
        if _has_perm(message.from_user.id, "can_manage_channels"):
            lines.append("/addchannel <@username|chat_id> [invite_link] - majburiy kanal qo'shish")
            lines.append("/delchannel <@username|chat_id> - kanalni chiqarish")
        if _has_perm(message.from_user.id, "can_view_lists"):
            lines.append("/channels - kanallar ro'yxati")
        lines.append("/serial <nom|kod> - dramani yuborish")
        lines.append("/search <nom> - drama qidirish")
        if _has_perm(message.from_user.id, "can_add_serial") and _has_perm(message.from_user.id, "can_add_part"):
            lines.append("/import <guruh_linki> - mavzuli guruhdan drama import")
        if _has_perm(message.from_user.id, "can_manage_vip"):
            lines.extend(
                [
                    "/addvip <user_id> - VIP qo'shish",
                    "/delvip <user_id> - VIP olib tashlash",
                    "/vippart <drama_kod> <qism> <on|off> - qismni VIP qilish",
                    "/viplist - VIP ro'yxati",
                    "/setvipprice <sum> - VIP narx belgilash",
                    "/vipprice - VIP narx ko'rish",
                    "/vipmsg - VIP xabarini o'zgartirish",
                    "/vipcard - VIP rekvizit o'zgartirish",
                ]
            )
        if _has_perm(message.from_user.id, "can_broadcast"):
            lines.append("/broadcast <text> - barchaga xabar (admin)")
            lines.append("/broadcast - reply bilan rasm/video yuborish")
            lines.append("/usend <@username|user_id> [text] - userbot orqali yuborish")
            lines.append("/post - kanalga post yaratish")
        if _has_perm(message.from_user.id, "can_add_serial"):
            lines.append("/renameserial <drama_kod> <yangi_nomi> - drama nomini o'zgartirish")
        lines.append("/vip - VIP holatini ko'rish")
        if message.from_user.id == OWNER_ID:
            lines.extend(
                [
                    "/setuserbotapiid <raqam> - userbot app id",
                    "/setuserbotapihash <hash> - userbot app hash",
                    "/setuserbotsession <session_string> - userbot session",
                    "/clearuserbotapi - userbot app id/hash tozalash",
                    "/clearuserbotsession - userbot session tozalash",
                ]
            )
        text = "\n".join(lines)
    else:
        text = (
            "Buyruqlar:\n"
            "Drama ko'rish: drama kodini yoki nomini yozing (masalan: 268)\n"
            "/serial <nom|kod> - dramani yuborish\n"
            "/search <nom> - drama qidirish\n"
            "/new - yangi dramalar\n"
            "/top - top dramalar\n"
            "/vip - VIP holatini ko'rish\n"
            "/myvip - VIP holati (tez)\n"
            "/settings - sozlamalar\n"
            "/contact - adminlarga yozish\n\n"
            "Misollar:\n"
            "- 268\n"
            "- /search queen\n"
        )
    await message.answer(text)
    _log_event("admins_list", message.from_user.id)


@router.message(Command("top"))
async def top_handler(message: Message):
    if not await ensure_subscribed(message):
        return
    include_vip = _include_vip_serials(message.from_user.id)
    top = get_top_liked_serials(20, include_vip)
    if not top:
        await message.answer("Dramalar yo'q.")
        return
    serials = [
        {"id": item["id"], "code": item["code"], "title": item["title"], "is_vip": item["is_vip"]}
        for item in top
    ]
    lines = ["Top dramalar:"]
    for idx, item in enumerate(top, start=1):
        title = _pretty_title_text(item.get("title") or "-")
        likes = int(item.get("likes") or 0)
        lines.append(f"{idx}. {title} ({likes})")
    sent_message=await message.answer(
        "\n".join(lines),
        reply_markup=user_serials_keyboard(serials, page=0, total_pages=1, sort_key="top"),
    )

    await asyncio.sleep(60)

    try:
        await sent_message.delete()
    except:
        pass


@router.message(Command("new"))
async def new_handler(message: Message):
    if not await ensure_subscribed(message):
        return
    include_vip = _include_vip_serials(message.from_user.id)
    latest = get_latest_serials(10, include_vip)
    if not latest:
        await message.answer("Dramalar yo'q.")
        return
    serials = [
        {"id": item["id"], "code": item["code"], "title": item["title"], "is_vip": item["is_vip"]}
        for item in latest
    ]
    lines = ["Yangi dramalar:"]
    for idx, item in enumerate(latest, start=1):
        title = _pretty_title_text(item.get("title") or "-")
        lines.append(f"{idx}. {title}")
    sent_message=await message.answer(
        "\n".join(lines),
        reply_markup=user_serials_keyboard(serials, page=0, total_pages=1, sort_key="new"),
    )

    await asyncio.sleep(60)

    try:
        await sent_message.delete()
    except:
        pass



@router.message(Command("addadmin"))
async def add_admin_handler(message: Message, command: CommandObject):
    if not _has_perm(message.from_user.id, "can_manage_admins"):
        await message.answer("Bu buyruq uchun ruxsat yo'q.")
        return
    if not command.args:
        await message.answer("Foydalanish: /addadmin <user_id>")
        return
    try:
        user_id = int(command.args.strip())
    except ValueError:
        await message.answer("user_id raqam bo'lishi kerak.")
        return
    perms = get_admin_permissions(user_id) or _default_admin_permissions()
    ADMIN_ADD_SESSIONS[message.from_user.id] = {
        "target_id": user_id,
        "perms": perms,
        "mode": "add",
    }
    _log_event("admin_add_start", message.from_user.id, f"target_id={user_id}")
    await message.answer(
        _format_perm_text(ADMIN_ADD_SESSIONS[message.from_user.id]["perms"]),
        reply_markup=admin_permissions_keyboard(
            ADMIN_ADD_SESSIONS[message.from_user.id]["perms"],
            ADMIN_PERMISSION_LABELS,
        ),
    )


@router.message(Command("deladmin"))
async def del_admin_handler(message: Message, command: CommandObject):
    if not _has_perm(message.from_user.id, "can_manage_admins"):
        await message.answer("Bu buyruq uchun ruxsat yo'q.")
        return
    if not command.args:
        await message.answer("Foydalanish: /deladmin <user_id>")
        return
    try:
        user_id = int(command.args.strip())
    except ValueError:
        await message.answer("user_id raqam bo'lishi kerak.")
        return
    del_admin(user_id)
    _log_event("admin_deleted", message.from_user.id, f"target_id={user_id}")
    await message.answer("Admin chiqarildi.")


@router.message(Command("renameserial"))
async def rename_serial_handler(message: Message, command: CommandObject):
    if not _has_perm(message.from_user.id, "can_add_serial"):
        await message.answer("Bu buyruq uchun ruxsat yo'q.")
        return
    if not command.args:
        await message.answer("Foydalanish: /renameserial <drama_kod> <yangi_nomi>")
        return
    parts = command.args.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Foydalanish: /renameserial <drama_kod> <yangi_nomi>")
        return
    code = _parse_code(parts[0])
    if not code:
        await message.answer("Kod faqat raqam bo'lishi kerak.")
        return
    new_title = parts[1].strip()
    if not new_title:
        await message.answer("Yangi nom bo'sh bo'lmasin.")
        return
    serial = get_serial_by_code(int(code))
    if not serial:
        await message.answer("Drama topilmadi.")
        return
    rename_serial(serial["id"], new_title)
    await message.answer("Drama nomi yangilandi.")
    _log_event(
        "serial_renamed",
        message.from_user.id,
        f"serial_id={serial['id']} code={serial['code']}",
    )


@router.message(Command("delserial"))
async def del_serial_handler(message: Message, command: CommandObject):
    if not _has_perm(message.from_user.id, "can_add_serial"):
        await message.answer("Bu buyruq uchun ruxsat yo'q.")
        return
    if not command.args:
        await message.answer("Foydalanish: /delserial <drama_kod>")
        return
    code = _parse_code(command.args)
    if not code:
        await message.answer("Kod faqat raqam bo'lishi kerak.")
        return
    del_serial(int(code))
    await message.answer("Drama o'chirildi.")


@router.message(Command("cleanup"))
async def cleanup_empty_serials_handler(message: Message):
    if not _has_perm(message.from_user.id, "can_add_serial"):
        await message.answer("Bu buyruq uchun ruxsat yo'q.")
        return
    removed = delete_empty_serials()
    if not removed:
        await message.answer("Bo'sh dramalar topilmadi.")
        return
    lines = ["Bo'sh dramalar o'chirildi:"]
    lines.extend(f"- {item['code']} {item['title']}" for item in removed)
    for chunk in _chunk_lines(lines):
        await message.answer(chunk)
    _log_event("serials_cleanup", message.from_user.id, f"removed={len(removed)}")


@router.message(Command("delpart"))
async def del_part_handler(message: Message, command: CommandObject):
    if not _has_perm(message.from_user.id, "can_add_part"):
        await message.answer("Bu buyruq uchun ruxsat yo'q.")
        return
    if not command.args:
        await message.answer("Foydalanish: /delpart <drama_kod> <qism>")
        return
    parts = command.args.split()
    if len(parts) != 2:
        await message.answer("Foydalanish: /delpart <drama_kod> <qism>")
        return
    code = _parse_code(parts[0])
    part = _parse_part(parts[1])
    if not code or part is None:
        await message.answer("Kod va qism raqami raqam bo'lishi kerak.")
        return
    serial = get_serial_by_code(int(code))
    if not serial:
        await message.answer("Drama topilmadi.")
        return
    del_serial_part(serial["id"], part)
    await message.answer("Qism o'chirildi.")


@router.message(Command("admins"))
async def list_admins_handler(message: Message):
    if not _has_perm(message.from_user.id, "can_view_lists"):
        await message.answer("Bu buyruq uchun ruxsat yo'q.")
        return
    admins = get_admins()
    if not admins:
        await message.answer("Adminlar yo'q.")
        return
    user_map = {user["user_id"]: user.get("username") for user in get_users()}
    lines = ["Adminlar:"]
    for admin_id in admins:
        perms = get_admin_permissions(admin_id) or _default_admin_permissions()
        username = user_map.get(admin_id)
        label = f"@{username}" if username else str(admin_id)
        lines.append(f"{label} | {_format_perm_inline(perms)}")
    text = "\n".join(lines)
    await message.answer(text)


@router.message(Command("admin"))
async def admin_panel_handler(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Bu buyruq faqat adminlar uchun.")
        return
    await message.answer("Admin panel:", reply_markup=admin_panel_keyboard())


@router.callback_query(F.data == "admin:back")
async def admin_back_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    LOG_QUERY_ADMINS.discard(callback.from_user.id)
    VIP_CARD_SESSIONS.discard(callback.from_user.id)
    VIP_REJECT_SESSIONS.pop(callback.from_user.id, None)
    BROADCAST_TEXT_SESSIONS.discard(callback.from_user.id)
    BROADCAST_SESSIONS.pop(callback.from_user.id, None)
    await callback.message.edit_text("Admin panel:", reply_markup=admin_panel_keyboard())


@router.callback_query(F.data == "serial:cancel")
async def serial_cancel_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    clear_serial_session(callback.from_user.id)
    try:
        await callback.message.edit_text(
            "Drama qo'shish bekor qilindi.",
            reply_markup=admin_panel_keyboard(),
        )
    except TelegramBadRequest:
        await callback.answer()


@router.message(Command("serialcancel"))
async def serial_cancel_command_handler(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Ruxsat yo'q.")
        return
    clear_serial_session(message.from_user.id)
    await message.answer(
        "Drama qo'shish bekor qilindi.",
        reply_markup=admin_panel_keyboard(),
    )


@router.callback_query(F.data == "log:cancel")
async def log_cancel_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    LOG_QUERY_ADMINS.discard(callback.from_user.id)
    await callback.message.edit_text(
        "Loglar so'rovi bekor qilindi.",
        reply_markup=admin_panel_keyboard(),
    )


@router.callback_query(F.data == "serial:continue")
async def serial_continue_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    if not _has_perm(callback.from_user.id, "can_add_part"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    session = get_serial_session(callback.from_user.id)
    if not session or session.get("state") != "await_part":
        await callback.answer("Drama sessiya topilmadi.", show_alert=True)
        return
    next_part = session.get("next_part") or 1
    await callback.message.edit_text(f"{next_part}-qismni yuboring.")


@router.callback_query(F.data == "admin:admins")
async def admin_list_callback(callback: CallbackQuery):
    if not _has_perm(callback.from_user.id, "can_view_lists"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    admins = get_admins()
    if not admins:
        text = "Adminlar yo'q."
    else:
        user_map = {user["user_id"]: user.get("username") for user in get_users()}
        lines = ["Adminlar:"]
        for admin_id in admins:
            perms = get_admin_permissions(admin_id) or _default_admin_permissions()
            username = user_map.get(admin_id)
            label = f"@{username}" if username else str(admin_id)
            lines.append(f"{label} | {_format_perm_inline(perms)}")
        text = "\n".join(lines)
    await callback.message.edit_text(text, reply_markup=admin_back_keyboard())
    _log_event("admins_list", callback.from_user.id)


@router.callback_query(F.data == "admin:channels")
async def admin_channels_callback(callback: CallbackQuery):
    if not (
        _has_perm(callback.from_user.id, "can_manage_channels")
        or _has_perm(callback.from_user.id, "can_view_lists")
    ):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    channels = get_channels()
    if not channels:
        text = "Kanallar ro'yxati bo'sh."
    else:
        text = "Kanallar:\n" + "\n".join(
            f"{item.get('title')} ({item.get('username') or item.get('chat_id')})"
            for item in channels
        )
    await callback.message.edit_text(text, reply_markup=admin_back_keyboard())


@router.callback_query(F.data == "admin:stats")
async def admin_stats_callback(callback: CallbackQuery):
    if not _has_perm(callback.from_user.id, "can_view_stats"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    day = _today()
    total, top = get_serial_day_stats(day)
    lines = [f"Bugungi ko'rishlar: {total}"]
    if top:
        lines.append("Top drama kodlari:")
        lines.extend([f"{code} - {count}" for code, count in top])
    recent = get_serial_recent_days()
    if recent:
        lines.append("So'nggi kunlar:")
        lines.extend([f"{d}: {c}" for d, c in recent])
    await callback.message.edit_text("\n".join(lines), reply_markup=admin_back_keyboard())


@router.callback_query(F.data == "admin:users")
async def admin_users_callback(callback: CallbackQuery):
    if not _has_perm(callback.from_user.id, "can_view_lists"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    await _render_users_page(callback, page=0)


@router.callback_query(F.data.startswith("admin:user:"))
async def admin_user_block_callback(callback: CallbackQuery):
    if not _has_perm(callback.from_user.id, "can_manage_admins"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    parts = callback.data.split(":")
    if len(parts) != 5:
        await callback.answer("Xatolik.", show_alert=True)
        return
    action = parts[2]
    try:
        user_id = int(parts[3])
        page = int(parts[4])
    except ValueError:
        await callback.answer("Xatolik.", show_alert=True)
        return
    if action == "msg":
        if not _has_perm(callback.from_user.id, "can_broadcast"):
            await callback.answer("Ruxsat yo'q.", show_alert=True)
            return
        ADMIN_USER_MESSAGE_SESSIONS[callback.from_user.id] = {
            "user_id": user_id,
            "page": page,
        }
        await callback.message.edit_text(
            "Foydalanuvchiga yuboriladigan xabarni jo'nating.\nBekor qilish: /cancel",
            reply_markup=admin_back_keyboard(),
        )
        return
    if user_id == OWNER_ID:
        await callback.answer("Owner bloklanmaydi.", show_alert=True)
        return
    if action == "block":
        block_user(user_id, _now())
        await callback.answer("Foydalanuvchi bloklandi.")
    elif action == "unblock":
        unblock_user(user_id)
        await callback.answer("Foydalanuvchi blokdan chiqarildi.")
    else:
        await callback.answer("Xatolik.", show_alert=True)
        return
    await _render_users_page(callback, page=page)


@router.callback_query(F.data == "admin:serials")
async def admin_serials_callback(callback: CallbackQuery):
    if not _has_perm(callback.from_user.id, "can_view_lists"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    await _render_serials_page(callback, page=0)


@router.callback_query(F.data.startswith("admin:serials:"))
async def admin_serials_page_callback(callback: CallbackQuery):
    if not _has_perm(callback.from_user.id, "can_view_lists"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Xatolik.", show_alert=True)
        return
    try:
        page = int(parts[2])
    except ValueError:
        await callback.answer("Xatolik.", show_alert=True)
        return
    await _render_serials_page(callback, page=page)


@router.callback_query(F.data.startswith("admin:serial:"))
async def admin_serial_callback(callback: CallbackQuery):
    if not _has_perm(callback.from_user.id, "can_view_lists"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Xatolik.", show_alert=True)
        return
    try:
        serial_id = int(parts[2])
    except ValueError:
        await callback.answer("Xatolik.", show_alert=True)
        return
    serial = get_serial_by_id(serial_id)
    if not serial:
        await callback.answer("Drama topilmadi.", show_alert=True)
        return
    if _has_perm(callback.from_user.id, "can_add_serial"):
        SERIAL_RENAME_SESSIONS[callback.from_user.id] = serial_id
        await callback.message.answer(
            "Drama nomini yuboring (bekor qilish: /cancel)."
        )
    ok = await _show_serial_parts(callback.message, serial["id"])
    if not ok:
        await callback.answer("Dramada qismlar yo'q.", show_alert=True)


@router.callback_query(F.data.startswith("admin:serialvip:"))
async def admin_serial_vip_callback(callback: CallbackQuery):
    if not _has_perm(callback.from_user.id, "can_manage_vip"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("Xatolik.", show_alert=True)
        return
    try:
        serial_id = int(parts[2])
        page = int(parts[3])
    except ValueError:
        await callback.answer("Xatolik.", show_alert=True)
        return
    serial = get_serial_by_id(serial_id)
    if not serial:
        await callback.answer("Drama topilmadi.", show_alert=True)
        return
    new_value = 0 if serial.get("is_vip") else 1
    set_serial_vip(serial_id, new_value)
    await _render_serials_page(callback, page=page)
    if new_value == 1 and _has_perm(callback.from_user.id, "can_broadcast"):
        await callback.message.answer(
            "Drama VIPga o'tdi. VIP obunachilarga xabar yuborilsinmi?",
            reply_markup=_new_drama_broadcast_keyboard("vip", serial_id),
        )


@router.callback_query(F.data == "admin:backup")
async def admin_backup_callback(callback: CallbackQuery):
    if not _has_perm(callback.from_user.id, "can_backup"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    await callback.message.edit_text("Backup tayyorlanmoqda...")
    await _send_backup(callback.message)
    _log_event("backup_sent", callback.from_user.id)


@router.callback_query(F.data.startswith("admin:users:"))
async def admin_users_page_callback(callback: CallbackQuery):
    if not _has_perm(callback.from_user.id, "can_view_lists"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Xatolik.", show_alert=True)
        return
    try:
        page = int(parts[2])
    except ValueError:
        await callback.answer("Xatolik.", show_alert=True)
        return
    await _render_users_page(callback, page=page)


async def _render_users_page(callback: CallbackQuery, page: int) -> None:
    if not _has_perm(callback.from_user.id, "can_view_lists"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    total = count_users()
    if total == 0:
        await callback.message.edit_text("Foydalanuvchilar yo'q.", reply_markup=admin_back_keyboard())
        return
    blocked_ids = set(get_blocked_users())
    total_pages = max(1, (total + USERS_PER_PAGE - 1) // USERS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * USERS_PER_PAGE
    end = start + USERS_PER_PAGE
    page_users = get_users_page(USERS_PER_PAGE, start)
    header = f"Foydalanuvchilar: {total} ta"
    lines = []
    entities: list[MessageEntity] = []
    offset = _utf16_len(header) + 1
    for user in page_users:
        user_id = int(user.get("user_id") or 0)
        username = (user.get("username") or "").strip()
        full_name = (user.get("full_name") or "").strip()
        raw_label = f"@{username}" if username else (full_name or str(user_id))
        suffix = " (bloklangan)" if user_id in blocked_ids else ""
        line = f"{raw_label}{suffix}"
        lines.append(line)
        try:
            chat = await callback.bot.get_chat(user_id)
            entities.append(
                MessageEntity(
                    type="text_mention",
                    offset=offset,
                    length=_utf16_len(raw_label),
                    user=chat,
                )
            )
        except Exception:
            pass
        offset += _utf16_len(line) + 1
    body = "\n".join(lines)
    text = f"{header}\n{body}"
    try:
        await callback.message.edit_text(
            text,
            reply_markup=users_manage_keyboard(page_users, blocked_ids, page, total_pages),
            entities=entities,
        )
    except TelegramBadRequest as err:
        if "message is not modified" not in str(err).lower():
            raise


async def _render_serials_page(callback: CallbackQuery, page: int) -> None:
    if not _has_perm(callback.from_user.id, "can_view_lists"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    total = count_serials()
    if total == 0:
        await callback.message.edit_text("Dramalar yo'q.", reply_markup=admin_back_keyboard())
        return
    total_pages = max(1, (total + SERIALS_PER_PAGE - 1) // SERIALS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * SERIALS_PER_PAGE
    end = start + SERIALS_PER_PAGE
    page_serials = get_serials_page(SERIALS_PER_PAGE, start)
    codes = [int(item["code"]) for item in page_serials if item.get("code") is not None]
    views_map = get_serial_total_views_map(codes)
    header = f"Dramalar: {total} ta"
    lines = []
    for item in page_serials:
        code = item.get("code")
        code_int = int(code) if code is not None else 0
        views = views_map.get(code_int, 0)
        lines.append(
            f"{code} - {'VIP ' if item.get('is_vip') else ''}{item.get('title')} | ko'rishlar: {views}"
        )
    body = "\n".join(lines)
    text = f"{header}\n{body}"
    await callback.message.edit_text(
        text,
        reply_markup=serials_list_keyboard(page_serials, page, total_pages),
    )


async def _render_admins_edit_page(callback: CallbackQuery, page: int) -> None:
    admins = [admin_id for admin_id in get_admins() if admin_id != callback.from_user.id]
    if not admins:
        await callback.message.edit_text("Boshqa adminlar yo'q.", reply_markup=admin_back_keyboard())
        return
    user_map = {user["user_id"]: user.get("username") for user in get_users()}
    total = len(admins)
    total_pages = max(1, (total + ADMINS_PER_PAGE - 1) // ADMINS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * ADMINS_PER_PAGE
    end = start + ADMINS_PER_PAGE
    page_admins = []
    for admin_id in admins[start:end]:
        username = user_map.get(admin_id)
        label = f"@{username}" if username else str(admin_id)
        page_admins.append({"user_id": admin_id, "label": label})
    await callback.message.edit_text(
        "Adminni tanlang:",
        reply_markup=admin_edit_list_keyboard(page_admins, page, total_pages),
    )


async def _render_user_serials_page(callback: CallbackQuery, page: int, sort_key: str = "az") -> None:
    serials = _filter_serials_for_user(callback.from_user.id, get_serials())
    if not serials:
        await _safe_edit_or_answer(callback.message, "Dramalar yo'q.")
        return
    sort_key = sort_key if sort_key in {"az", "code", "new", "top"} else "az"
    if sort_key == "code":
        serials = sorted(serials, key=lambda item: int(item.get("code") or 0))
    elif sort_key == "new":
        serials = sorted(
            serials,
            key=lambda item: item.get("last_part_at") or item.get("created_at") or "",
            reverse=True,
        )
    elif sort_key == "top":
        ids = [int(item["id"]) for item in serials if item.get("id") is not None]
        likes_map = get_serial_rating_like_counts_map(ids)
        serials = sorted(
            serials,
            key=lambda item: (
                -likes_map.get(int(item.get("id") or 0), 0),
                (item.get("title") or "").casefold(),
            ),
        )
    else:
        serials = sorted(
            serials,
            key=lambda item: ((item.get("title") or "").casefold(), int(item.get("code") or 0)),
        )
    total = len(serials)
    total_pages = max(1, (total + USER_SERIALS_PER_PAGE - 1) // USER_SERIALS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * USER_SERIALS_PER_PAGE
    end = start + USER_SERIALS_PER_PAGE
    page_serials = serials[start:end]
    label = {"az": "A-Z", "code": "Kod", "new": "Yangi", "top": "Top"}.get(sort_key, "A-Z")
    text = f"Dramalar ({label}): {total} ta"
    await _safe_edit_or_answer(
        callback.message,
        text,
        reply_markup=user_serials_keyboard(page_serials, page, total_pages, sort_key=sort_key),
    )


async def _send_user_serials_menu(message: Message, page: int) -> None:
    serials = _filter_serials_for_user(message.from_user.id, get_serials())
    if not serials:
        await message.answer("Dramalar yo'q.", reply_markup=user_keyboard())
        return
    total = len(serials)
    total_pages = max(1, (total + USER_SERIALS_PER_PAGE - 1) // USER_SERIALS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * USER_SERIALS_PER_PAGE
    end = start + USER_SERIALS_PER_PAGE
    page_serials = serials[start:end]
    USER_SERIALS_LIST[message.from_user.id] = {
        "mode": "list",
        "serials": serials,
        "page": page,
        "total_pages": total_pages,
        "page_serials": page_serials,
    }
    await message.answer(
        "Dramalar ro'yxati:",
        reply_markup=user_serials_menu_keyboard(page_serials, page, total_pages),
    )


async def _render_user_search_results(
    callback: CallbackQuery,
    results: list[dict],
    page: int,
) -> None:
    total = len(results)
    total_pages = max(1, (total + USER_SERIALS_PER_PAGE - 1) // USER_SERIALS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * USER_SERIALS_PER_PAGE
    end = start + USER_SERIALS_PER_PAGE
    page_serials = results[start:end]
    text = f"Dramalar: {total} ta"
    await _safe_edit_or_answer(
        callback.message,
        text,
        reply_markup=user_search_results_keyboard(page_serials, page, total_pages),
    )


@router.callback_query(F.data == "admin:logs")
async def admin_logs_callback(callback: CallbackQuery):
    if not _has_perm(callback.from_user.id, "can_view_logs"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    LOG_QUERY_ADMINS.add(callback.from_user.id)
    last_lines = _tail_log(2)
    if last_lines:
        preview = "\n".join(f"{idx + 1}) {line}" for idx, line in enumerate(last_lines))
        text = (
            "So'nggi loglar:\n"
            f"{preview}\n\n"
            "Foydalanuvchi ID yoki @username yuboring."
        )
    else:
        text = "Foydalanuvchi ID yoki @username yuboring."
    await callback.message.edit_text(
        text,
        reply_markup=log_cancel_keyboard(),
    )


@router.callback_query(F.data == "admin:logfile")
async def admin_logfile_callback(callback: CallbackQuery):
    if not _has_perm(callback.from_user.id, "can_view_logs"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    await callback.message.edit_text("Log fayli yuborilmoqda...")
    await _send_log_file(callback.message)
    _log_event("logfile_sent", callback.from_user.id)


@router.callback_query(F.data == "admin:help")
async def admin_help_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    text = (
        "Admin buyruqlar:\n"
        "/addadmin <user_id>\n"
        "/editadmin <user_id>\n"
        "/deladmin <user_id>\n"
        "/addvip <user_id>\n"
        "/delvip <user_id>\n"
        "/viplist\n"
        "/setvipprice <sum>\n"
        "/vipprice\n"
        "/vipmsg\n"
        "/vipcard\n"
        "/addchannel <@username|chat_id> [invite_link]\n"
        "/delchannel <@username|chat_id>\n"
        "/addserial (inline)\n"
        "/addpart <drama_nomi|kod>\n"
        "/import <guruh_linki>\n"
        "/search <nom>\n"
        "/part <qism_raqami>\n"
        "/delserial <drama_kod>\n"
        "/delpart <drama_kod> <qism>\n"
        "Admin panel -> Loglar\n"
        "Admin panel -> Log fayli\n"
        "Admin panel -> Dramalar\n"
        "Admin panel -> Statistika\n"
        "Admin panel -> Backup\n"
        "Admin panel -> Foydalanuvchilar\n"
        "/log <user_id|@username>\n"
        "/logfile\n"
        "/stats\n"
        "/backup\n"
        "/restoredb\n"
        "/cancelrestore\n"
        "/post - kanalga post yaratish\n"
    )
    await callback.message.edit_text(text, reply_markup=admin_back_keyboard())


@router.callback_query(F.data == "admin:addadmin")
async def admin_addadmin_callback(callback: CallbackQuery):
    if not _has_perm(callback.from_user.id, "can_manage_admins"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    await callback.message.edit_text(
        "Foydalanish: /addadmin <user_id>",
        reply_markup=admin_back_keyboard(),
    )


@router.callback_query(F.data.startswith("perm:"))
async def admin_permissions_callback(callback: CallbackQuery):
    if not _has_perm(callback.from_user.id, "can_manage_admins"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    session = ADMIN_ADD_SESSIONS.get(callback.from_user.id)
    if not session:
        await callback.answer("Sessiya topilmadi.", show_alert=True)
        return
    parts = callback.data.split(":")
    if len(parts) < 2:
        await callback.answer("Xatolik.", show_alert=True)
        return
    action = parts[1]
    perms = session.get("perms") or {}
    if action == "toggle":
        if len(parts) != 3:
            await callback.answer("Xatolik.", show_alert=True)
            return
        key = parts[2]
        if key not in ADMIN_PERMISSION_LABELS:
            await callback.answer("Xatolik.", show_alert=True)
            return
        perms[key] = 0 if perms.get(key) else 1
        await callback.message.edit_text(
            _format_perm_text(perms),
            reply_markup=admin_permissions_keyboard(perms, ADMIN_PERMISSION_LABELS),
        )
        _log_event(
            "admin_perm_toggle",
            callback.from_user.id,
            f"target_id={session.get('target_id')} key={key} value={perms[key]}",
        )
        return
    if action == "save":
        target_id = session.get("target_id")
        if not isinstance(target_id, int):
            await callback.answer("Xatolik.", show_alert=True)
            return
        add_admin(target_id)
        set_admin_permissions(target_id, perms)
        ADMIN_ADD_SESSIONS.pop(callback.from_user.id, None)
        _log_event("admin_saved", callback.from_user.id, f"target_id={target_id}")
        await callback.message.edit_text(
            "Admin saqlandi.",
            reply_markup=admin_back_keyboard(),
        )
        return
    if action == "cancel":
        ADMIN_ADD_SESSIONS.pop(callback.from_user.id, None)
        _log_event("admin_add_cancel", callback.from_user.id, f"target_id={session.get('target_id')}")
        await callback.message.edit_text("Bekor qilindi.", reply_markup=admin_back_keyboard())
        return
    await callback.answer("Xatolik.", show_alert=True)


@router.callback_query(F.data == "admin:deladmin")
async def admin_deladmin_callback(callback: CallbackQuery):
    if not _has_perm(callback.from_user.id, "can_manage_admins"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    await callback.message.edit_text(
        "Foydalanish: /deladmin <user_id>",
        reply_markup=admin_back_keyboard(),
    )


@router.callback_query(F.data == "admin:editadmin")
async def admin_editadmin_callback(callback: CallbackQuery):
    if not _has_perm(callback.from_user.id, "can_manage_admins"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    await _render_admins_edit_page(callback, page=0)


@router.callback_query(F.data.startswith("admin:editadmin:"))
async def admin_editadmin_page_callback(callback: CallbackQuery):
    if not _has_perm(callback.from_user.id, "can_manage_admins"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Xatolik.", show_alert=True)
        return
    try:
        page = int(parts[2])
    except ValueError:
        await callback.answer("Xatolik.", show_alert=True)
        return
    await _render_admins_edit_page(callback, page=page)


@router.callback_query(F.data.startswith("admin:edit:"))
async def admin_edit_select_callback(callback: CallbackQuery):
    if not _has_perm(callback.from_user.id, "can_manage_admins"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Xatolik.", show_alert=True)
        return
    try:
        user_id = int(parts[2])
    except ValueError:
        await callback.answer("Xatolik.", show_alert=True)
        return
    if not is_admin(user_id):
        await callback.answer("Admin topilmadi.", show_alert=True)
        return
    perms = get_admin_permissions(user_id) or _default_admin_permissions()
    ADMIN_ADD_SESSIONS[callback.from_user.id] = {
        "target_id": user_id,
        "perms": perms,
        "mode": "edit",
    }
    _log_event("admin_edit_start", callback.from_user.id, f"target_id={user_id}")
    await callback.message.edit_text(
        _format_perm_text(perms),
        reply_markup=admin_permissions_keyboard(perms, ADMIN_PERMISSION_LABELS),
    )


@router.message(Command("editadmin"))
async def edit_admin_handler(message: Message, command: CommandObject):
    if not _has_perm(message.from_user.id, "can_manage_admins"):
        await message.answer("Bu buyruq uchun ruxsat yo'q.")
        return
    if not command.args:
        await message.answer("Foydalanish: /editadmin <user_id>")
        return
    try:
        user_id = int(command.args.strip())
    except ValueError:
        await message.answer("user_id raqam bo'lishi kerak.")
        return
    if not is_admin(user_id):
        await message.answer("Admin topilmadi.")
        return
    perms = get_admin_permissions(user_id) or _default_admin_permissions()
    ADMIN_ADD_SESSIONS[message.from_user.id] = {
        "target_id": user_id,
        "perms": perms,
        "mode": "edit",
    }
    _log_event("admin_edit_start", message.from_user.id, f"target_id={user_id}")
    await message.answer(
        _format_perm_text(perms),
        reply_markup=admin_permissions_keyboard(perms, ADMIN_PERMISSION_LABELS),
    )


@router.callback_query(F.data == "admin:addchannel")
async def admin_addchannel_callback(callback: CallbackQuery):
    if not _has_perm(callback.from_user.id, "can_manage_channels"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    await callback.message.edit_text(
        "Foydalanish: /addchannel <@username|chat_id> [invite_link]",
        reply_markup=admin_back_keyboard(),
    )


@router.callback_query(F.data == "admin:delchannel")
async def admin_delchannel_callback(callback: CallbackQuery):
    if not _has_perm(callback.from_user.id, "can_manage_channels"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    await callback.message.edit_text(
        "Foydalanish: /delchannel <@username|chat_id>",
        reply_markup=admin_back_keyboard(),
    )


@router.callback_query(F.data == "admin:addmovie")
async def admin_addmovie_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    await callback.message.edit_text(
        "Kino funksiyalari o'chirilgan.",
        reply_markup=admin_back_keyboard(),
    )


@router.callback_query(F.data == "admin:addserial")
async def admin_addserial_callback(callback: CallbackQuery):
    if not _has_perm(callback.from_user.id, "can_add_serial"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    save_serial_session(
        callback.from_user.id,
        state="await_title",
        created_at=_now(),
    )
    _log_event("serial_add_start", callback.from_user.id)
    await callback.message.edit_text(
        "Drama nomini yuboring.",
        reply_markup=serial_cancel_keyboard(),
    )


@router.message(Command("addserial"))
async def add_serial_command_handler(message: Message):
    if not _has_perm(message.from_user.id, "can_add_serial"):
        await message.answer("Bu buyruq uchun ruxsat yo'q.")
        return
    save_serial_session(
        message.from_user.id,
        state="await_title",
        created_at=_now(),
    )
    _log_event("serial_add_start", message.from_user.id)
    await message.answer(
        "Drama nomini yuboring.",
        reply_markup=serial_cancel_keyboard(),
    )


@router.callback_query(F.data == "admin:addpart")
async def admin_addpart_callback(callback: CallbackQuery):
    if not _has_perm(callback.from_user.id, "can_add_part"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    await callback.message.edit_text(
        "Foydalanish: /addpart <drama_nomi|kod>",
        reply_markup=admin_back_keyboard(),
    )


@router.callback_query(F.data == "admin:delserial")
async def admin_delserial_callback(callback: CallbackQuery):
    if not _has_perm(callback.from_user.id, "can_add_serial"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    await callback.message.edit_text(
        "Foydalanish: /delserial <drama_kod>",
        reply_markup=admin_back_keyboard(),
    )


@router.callback_query(F.data == "admin:delpart")
async def admin_delpart_callback(callback: CallbackQuery):
    if not _has_perm(callback.from_user.id, "can_add_part"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    await callback.message.edit_text(
        "Foydalanish: /delpart <drama_kod> <qism>",
        reply_markup=admin_back_keyboard(),
    )


@router.callback_query(F.data == "admin:delmovie")
async def admin_delmovie_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    await callback.message.edit_text(
        "Kino funksiyalari o'chirilgan.",
        reply_markup=admin_back_keyboard(),
    )


@router.callback_query(F.data == "admin:broadcast")
async def admin_broadcast_callback(callback: CallbackQuery):
    if not _has_perm(callback.from_user.id, "can_broadcast"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    BROADCAST_TEXT_SESSIONS.add(callback.from_user.id)
    BROADCAST_SESSIONS.pop(callback.from_user.id, None)
    await callback.message.edit_text(
        "E'lon matnini yuboring yoki xabarga reply qiling.\n"
        "Bekor qilish: /cancel",
        reply_markup=admin_back_keyboard(),
    )


@router.message(Command("restoredb"))
async def restore_db_handler(message: Message):
    if message.from_user.id != OWNER_ID:
        await message.answer("Bu buyruq faqat owner uchun.")
        return
    RESTORE_DB_SESSIONS[message.from_user.id] = {
        "state": "await_file",
        "cleanup": [],
    }
    if message.reply_to_message and message.reply_to_message.document:
        await _process_restore_document(message, message.reply_to_message.document)
        _log_event("restore_db_start", message.from_user.id)
        return
    await message.answer("Backup zip yoki bot.db faylni yuboring. Bekor qilish: /cancelrestore")
    _log_event("restore_db_start", message.from_user.id)


@router.message(Command("post"))
async def post_handler(message: Message, command: CommandObject):
    if not _has_perm(message.from_user.id, "can_broadcast"):
        await message.answer("Bu buyruq uchun ruxsat yo'q.")
        return
    channels = get_channels()
    if not channels:
        await message.answer("Ulangan kanallar yo'q. Avval /addchannel bilan qo'shing.")
        return
    session = {
        "state": "await_channel",
    }
    if command.args:
        code = _parse_code(command.args)
        if not code:
            await message.answer("Kod faqat raqam bo'lishi kerak.")
            return
        serial = get_serial_by_code(int(code))
        if not serial:
            await message.answer("Drama topilmadi.")
            return
        parts_count = len(get_serial_parts(serial["id"]))
        session.update(
            {
                "serial_id": serial["id"],
                "title": serial["title"],
                "code": serial["code"],
                "parts_count": parts_count,
            }
        )
    POST_SESSIONS[message.from_user.id] = session
    await message.answer(
        "Qaysi kanalga post yuborilsin?",
        reply_markup=post_channel_keyboard(channels),
    )
    _log_event("post_start", message.from_user.id)


@router.callback_query(F.data.startswith("post:"))
async def post_callback(callback: CallbackQuery):
    if not _has_perm(callback.from_user.id, "can_broadcast"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    session = POST_SESSIONS.get(callback.from_user.id)
    if not session:
        await callback.answer("Sessiya topilmadi.", show_alert=True)
        return
    parts = callback.data.split(":")
    if len(parts) < 2:
        await callback.answer("Xatolik.", show_alert=True)
        return
    action = parts[1]
    if action == "cancel":
        POST_SESSIONS.pop(callback.from_user.id, None)
        await callback.message.edit_text("Post yaratish bekor qilindi.")
        _log_event("post_cancel", callback.from_user.id)
        return
    if action == "channel":
        if len(parts) != 3:
            await callback.answer("Xatolik.", show_alert=True)
            return
        try:
            channel_id = int(parts[2])
        except ValueError:
            await callback.answer("Xatolik.", show_alert=True)
            return
        session["channel_id"] = channel_id
        if session.get("serial_id"):
            serial = get_serial_by_id(int(session["serial_id"]))
            session["state"] = "await_media"
            await callback.message.edit_text(
                "Rasm va caption yuboring.",
                reply_markup=post_media_keyboard(),
            )
        else:
            session["state"] = "await_code"
            await callback.message.edit_text("Drama kodini yuboring.")
        return
    await callback.answer("Xatolik.", show_alert=True)


@router.message(Command("cancelrestore"))
async def cancel_restore_handler(message: Message):
    if message.from_user.id != OWNER_ID:
        await message.answer("Bu buyruq faqat owner uchun.")
        return
    _cleanup_restore_session(message.from_user.id)
    await message.answer("DB tiklash bekor qilindi.")
    _log_event("restore_db_cancel", message.from_user.id)


async def _process_restore_document(message: Message, document) -> None:
    if not document:
        return
    filename = (document.file_name or "").lower()
    if not (filename.endswith(".db") or filename.endswith(".zip")):
        await message.answer("Faqat .db yoki .zip fayl yuboring.")
        return
    temp_dir = tempfile.mkdtemp(prefix="serialbot-restore-")
    RESTORE_DB_SESSIONS.setdefault(message.from_user.id, {"cleanup": []})
    RESTORE_DB_SESSIONS[message.from_user.id].setdefault("cleanup", []).append(temp_dir)
    download_path = os.path.join(temp_dir, document.file_name or "upload.db")
    try:
        file = await message.bot.get_file(document.file_id)
        await message.bot.download_file(file.file_path, download_path)
    except Exception:
        await message.answer("Faylni yuklab bo'lmadi.")
        return
    db_path = None
    if filename.endswith(".db"):
        db_path = download_path
    else:
        try:
            with zipfile.ZipFile(download_path, "r") as archive:
                candidate = None
                for name in archive.namelist():
                    if name.lower().endswith("bot.db"):
                        candidate = name
                        break
                if not candidate:
                    await message.answer("Zip ichida bot.db topilmadi.")
                    return
                with archive.open(candidate) as src:
                    db_path = os.path.join(temp_dir, "bot.db")
                    with open(db_path, "wb") as dst:
                        shutil.copyfileobj(src, dst)
        except Exception:
            await message.answer("Zip faylni ochib bo'lmadi.")
            return
    if not db_path or not os.path.exists(db_path):
        await message.answer("DB fayl topilmadi.")
        return
    RESTORE_DB_SESSIONS[message.from_user.id]["state"] = "await_confirm"
    RESTORE_DB_SESSIONS[message.from_user.id]["db_path"] = db_path
    kb = InlineKeyboardBuilder()
    kb.button(text="Tasdiqlash", callback_data="restoredb:confirm")
    kb.button(text="Bekor qilish", callback_data="restoredb:cancel")
    kb.adjust(2)
    await message.answer(
        "DB tiklashni tasdiqlaysizmi? Hozirgi baza almashtiriladi.",
        reply_markup=kb.as_markup(),
    )


@router.message(Command("addchannel"))
async def add_channel_handler(message: Message, command: CommandObject):
    if not _has_perm(message.from_user.id, "can_manage_channels"):
        await message.answer("Bu buyruq uchun ruxsat yo'q.")
        return
    if not command.args:
        await message.answer("Foydalanish: /addchannel <@username|chat_id>")
        return
    parts = command.args.split()
    target = parts[0]
    provided_invite = parts[1] if len(parts) > 1 else ""
    try:
        chat = await message.bot.get_chat(target)
    except Exception:
        await message.answer("Kanal topilmadi.")
        return
    try:
        member = await message.bot.get_chat_member(chat.id, message.from_user.id)
    except Exception:
        await message.answer("Kanal a'zolik holatini tekshirib bo'lmadi.")
        return
    if member.status not in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}:
        await message.answer("Iltimos, avval kanalda admin qiling.")
        return
    can_post = getattr(member, "can_post_messages", None)
    if can_post is False:
        await message.answer("Kanalda post yozish huquqi yo'q. Ruxsat bering.")
        return
    invite_link = ""
    if not chat.username:
        if provided_invite:
            invite_link = provided_invite
        else:
            try:
                invite = await message.bot.create_chat_invite_link(
                    chat.id,
                    creates_join_request=True,
                )
                invite_link = invite.invite_link
            except Exception:
                await message.answer("Kanal uchun invite link yaratilmayapti.")
                return
    add_channel(chat.id, chat.username, chat.title or chat.username or str(chat.id), invite_link)
    _log_event("channel_added", message.from_user.id, f"chat_id={chat.id}")
    await message.answer("Kanal qo'shildi.")


@router.message(Command("delchannel"))
async def del_channel_handler(message: Message, command: CommandObject):
    if not _has_perm(message.from_user.id, "can_manage_channels"):
        await message.answer("Bu buyruq uchun ruxsat yo'q.")
        return
    if not command.args:
        await message.answer("Foydalanish: /delchannel <@username|chat_id>")
        return
    target = command.args.strip()
    try:
        chat = await message.bot.get_chat(target)
    except Exception:
        await message.answer("Kanal topilmadi.")
        return
    del_channel(chat.id)
    _log_event("channel_deleted", message.from_user.id, f"chat_id={chat.id}")
    await message.answer("Kanal chiqarildi.")


@router.message(Command("channels"))
async def list_channels_handler(message: Message):
    if not (_has_perm(message.from_user.id, "can_manage_channels") or _has_perm(message.from_user.id, "can_view_lists")):
        await message.answer("Bu buyruq uchun ruxsat yo'q.")
        return
    channels = get_channels()
    if not channels:
        await message.answer("Kanallar ro'yxati bo'sh.")
        return
    text = "Kanallar:\n" + "\n".join(
        f"{item.get('title')} ({item.get('username') or item.get('chat_id')})"
        for item in channels
    )
    await message.answer(text)
    _log_event("channels_list", message.from_user.id)


@router.message(Command("addpart"))
async def add_part_handler(message: Message, command: CommandObject):
    if not _has_perm(message.from_user.id, "can_add_part"):
        await message.answer("Bu buyruq uchun ruxsat yo'q.")
        return
    if not command.args:
        await message.answer("Foydalanish: /addpart <drama_nomi|kod>")
        return
    raw = command.args.strip()
    serial = None
    if raw.isdigit():
        serial = get_serial_by_code(int(raw))
    if not serial:
        serial = get_serial_by_title(raw)
    if not serial:
        await message.answer("Drama topilmadi.")
        return
    next_part = _next_missing_part(serial["id"])
    save_serial_session(
        message.from_user.id,
        state="await_part",
        serial_id=serial["id"],
        next_part=next_part,
        created_at=_now(),
    )
    prompt = f"{serial['title']} - {next_part}-qismni yuboring."
    await message.answer(prompt, reply_markup=serial_flow_keyboard())
    _log_event(
        "serial_addpart_start",
        message.from_user.id,
        f"serial_id={serial['id']} next_part={next_part}",
    )


@router.message(Command("import"))
async def import_forum_handler(message: Message, command: CommandObject):
    if not (_has_perm(message.from_user.id, "can_add_serial") and _has_perm(message.from_user.id, "can_add_part")):
        await message.answer("Bu buyruq uchun ruxsat yo'q.")
        return
    if not command.args:
        await message.answer("Foydalanish: /import <guruh_linki>")
        return
    if message.from_user.id in IMPORT_TASKS or message.from_user.id in IMPORT_SESSIONS:
        await message.answer("Import allaqachon ketmoqda. Tugashini kuting.")
        return
    group_ref = command.args.strip()
    await message.answer("Import boshlandi. Bu biroz vaqt olishi mumkin.")
    _log_event("forum_import_start", message.from_user.id, f"group_ref={group_ref}")
    task = asyncio.create_task(_run_forum_import(message, group_ref))
    IMPORT_TASKS[message.from_user.id] = task


@router.message(Command("importcancel"))
async def import_cancel_handler(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Ruxsat yo'q.")
        return
    task = IMPORT_TASKS.pop(message.from_user.id, None)
    if task:
        task.cancel()
    IMPORT_SESSIONS.pop(message.from_user.id, None)
    await message.answer("Import bekor qilindi.")


@router.message(Command("importstop"))
async def import_stop_handler(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Ruxsat yo'q.")
        return
    task = IMPORT_TASKS.pop(message.from_user.id, None)
    if task:
        task.cancel()
    IMPORT_SESSIONS.pop(message.from_user.id, None)
    await message.answer("Import to'xtatildi.")


@router.callback_query(F.data.startswith("import:"))
async def import_callback_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    session = IMPORT_SESSIONS.get(user_id)
    if not session:
        await callback.answer("Import sessiya topilmadi.", show_alert=True)
        return
    parts = (callback.data or "").split(":")
    if len(parts) < 2:
        await callback.answer("Xatolik.", show_alert=True)
        return
    action = parts[1]
    per_page = 8
    if action == "noop":
        await callback.answer()
        return
    if action == "toggle":
        if len(parts) != 3 or not parts[2].isdigit():
            await callback.answer("Xatolik.", show_alert=True)
            return
        idx = int(parts[2])
        excluded = session.get("excluded") or set()
        if idx in excluded:
            excluded.remove(idx)
        else:
            excluded.add(idx)
        session["excluded"] = excluded
    elif action == "page":
        if len(parts) != 3 or not parts[2].isdigit():
            await callback.answer("Xatolik.", show_alert=True)
            return
        session["page"] = int(parts[2])
    elif action == "selectall":
        session["excluded"] = set()
    elif action == "selectnone":
        topics = session.get("topics") or []
        session["excluded"] = set(range(1, len(topics) + 1))
    elif action == "confirm":
        selected_topics = _import_selected_topics(session)
        if not selected_topics:
            await callback.answer("Hech narsa tanlanmagan.", show_alert=True)
            return
        total_parts = _import_selected_parts(session)
        session["state"] = "confirm"
        session["selected_topics"] = selected_topics
        session["selected_parts"] = total_parts
        parts_text = f"{total_parts} qism" if total_parts else "qismlar skan qilinadi"
        await callback.message.edit_text(
            f"Tanlandi: {len(selected_topics)} mavzu, {parts_text}. Tasdiqlaysizmi?",
            reply_markup=_import_confirm_keyboard(),
        )
        return
    elif action == "back":
        session["state"] = "select"
    elif action == "apply":
        if session.get("state") != "confirm":
            await callback.answer("Tasdiqlash kerak.", show_alert=True)
            return
        if user_id in IMPORT_TASKS:
            await callback.answer("Import allaqachon ketmoqda.", show_alert=True)
            return
        await callback.message.edit_text("Import boshlanmoqda...")
        task = asyncio.create_task(_apply_forum_import(callback.message, session))
        IMPORT_TASKS[user_id] = task
        return
    elif action == "cancel":
        IMPORT_SESSIONS.pop(user_id, None)
        await callback.message.edit_text("Import bekor qilindi.")
        return
    else:
        await callback.answer("Xatolik.", show_alert=True)
        return
    page = int(session.get("page") or 0)
    await callback.message.edit_text(
        _render_import_selection_text(session, page, per_page),
        reply_markup=_import_selection_keyboard(session, page, per_page),
    )


@router.message(Command("part"))
async def set_part_handler(message: Message, command: CommandObject):
    if not _has_perm(message.from_user.id, "can_add_part"):
        await message.answer("Bu buyruq uchun ruxsat yo'q.")
        return
    session = get_serial_session(message.from_user.id)
    if not session or session.get("state") != "await_part":
        await message.answer("Drama sessiya topilmadi. /addserial yoki /addpart ishlating.")
        return
    if not command.args:
        await message.answer("Foydalanish: /part <qism_raqami>")
        return
    part = _parse_part(command.args)
    if part is None:
        await message.answer("Qism raqami faqat musbat raqam bo'lishi kerak.")
        return
    SERIAL_UPLOAD_NEXT_PART[(message.from_user.id, int(session.get("serial_id") or 0))] = part
    save_serial_session(
        message.from_user.id,
        state="await_part",
        serial_id=session.get("serial_id"),
        next_part=part,
        created_at=session.get("created_at") or _now(),
    )
    prompt = f"{part}-qismni yuboring."
    await message.answer(prompt, reply_markup=serial_flow_keyboard())
    _log_event(
        "serial_part_set",
        message.from_user.id,
        f"serial_id={session.get('serial_id')} part={part}",
    )


@router.message(Command("addmovie"))
async def add_movie_disabled(message: Message, command: CommandObject):
    await message.answer("Kino funksiyalari o'chirilgan.")


@router.message(Command("delmovie"))
async def del_movie_disabled(message: Message, command: CommandObject):
    await message.answer("Kino funksiyalari o'chirilgan.")


@router.message(
    lambda message: (
        message.text
        and not message.text.startswith("/")
        and is_admin(message.from_user.id)
        and message.from_user.id in LOG_QUERY_ADMINS
    )
)
async def admin_log_text_handler(message: Message):
    if not _has_perm(message.from_user.id, "can_view_logs"):
        return
    if get_serial_session(message.from_user.id):
        return
    raw = message.text.strip()
    user_id: Optional[int] = None
    if raw.isdigit():
        user_id = int(raw)
    else:
        try:
            chat = await message.bot.get_chat(raw)
            user_id = chat.id
        except Exception:
            await message.answer("Foydalanuvchi topilmadi.")
            return
    lines = _tail_log_for_user(user_id, LOG_TAIL_LINES)
    LOG_QUERY_ADMINS.discard(message.from_user.id)
    if not lines:
        await message.answer("Ushbu foydalanuvchi uchun log topilmadi.")
        return
    text = "\n".join(lines)
    if len(text) > 3900:
        text = text[-3900:]
    await message.answer(text)


@router.message(
    lambda message: (
        message.text
        and not message.text.startswith("/")
        and is_admin(message.from_user.id)
        and get_serial_session(message.from_user.id)
    )
)
async def admin_serial_text_handler(message: Message):
    session = get_serial_session(message.from_user.id)
    raw_text = message.text.strip()
    raw_lower = raw_text.lower()
    if (
        raw_lower in {"dramalar ro'yxati", "ortga"}
        or "keyingi" in raw_lower
        or "oldingi" in raw_lower
    ):
        if raw_lower == "dramalar ro'yxati":
            await _send_user_serials_menu(message, page=0)
            return
        if raw_lower == "ortga":
            USER_SERIALS_LIST.pop(message.from_user.id, None)
            USER_SEARCH_SESSIONS.discard(message.from_user.id)
            USER_SEARCH_RESULTS.pop(message.from_user.id, None)
            await message.answer("Menyu:", reply_markup=user_keyboard())
            return
        state = USER_SERIALS_LIST.get(message.from_user.id)
        if not state:
            await _send_user_serials_menu(message, page=0)
            return
        mode = state.get("mode") or "list"
        page = int(state.get("page") or 0)
        total_pages = int(state.get("total_pages") or 1)
        if raw_text == "⬅️ Oldingi":
            page = max(0, page - 1)
        else:
            page = min(total_pages - 1, page + 1)
        state["page"] = page
        if mode == "search_db":
            query = state.get("query") or ""
            include_vip = bool(state.get("include_vip"))
            page_serials = search_serials_by_title(
                query,
                include_vip,
                USER_SERIALS_PER_PAGE,
                page * USER_SERIALS_PER_PAGE,
            )
        else:
            serials = state.get("serials") or []
            start = page * USER_SERIALS_PER_PAGE
            end = start + USER_SERIALS_PER_PAGE
            page_serials = serials[start:end]
        state["page_serials"] = page_serials
        await message.answer(
            "Dramalar ro'yxati:",
            reply_markup=user_serials_menu_keyboard(page_serials, page, total_pages),
        )
        return
    state = session.get("state")
    if state == "await_title":
        if not _has_perm(message.from_user.id, "can_add_serial"):
            await message.answer("Bu buyruq uchun ruxsat yo'q.")
            return
        title = message.text.strip()
        if not title:
            await message.answer("Drama nomi bo'sh bo'lmasin.")
            return
        existing = get_serial_by_title(title)
        if existing:
            await message.answer(
                f"Drama mavjud. Kod: {existing['code']}. /addpart <drama_nomi|kod> bilan davom ettiring."
            )
            clear_serial_session(message.from_user.id)
            return
        serial = add_serial(title, _now())
        _log_event("serial_created", message.from_user.id, f"serial_id={serial['id']} code={serial['code']}")
        save_serial_session(
            message.from_user.id,
            state="await_part",
            serial_id=serial["id"],
            next_part=1,
            created_at=_now(),
        )
        await message.answer(
            f"Drama yaratildi: {serial['title']}. Kod: {serial['code']}. 1-qismni yuboring.",
            reply_markup=serial_flow_keyboard(),
        )
        if _has_perm(message.from_user.id, "can_broadcast"):
            await message.answer(
                "Yangi drama qo'shildi. Hammaga xabar yuborilsinmi?",
                reply_markup=_new_drama_broadcast_keyboard("all", serial["id"]),
            )
        return
    if state == "await_part":
        if not _has_perm(message.from_user.id, "can_add_part"):
            await message.answer("Bu buyruq uchun ruxsat yo'q.")
            return
        part = _parse_part(message.text)
        if part is None:
            await message.answer("Qism raqamini yuboring yoki video/document yuboring.")
            return
        save_serial_session(
            message.from_user.id,
            state="await_part",
            serial_id=session.get("serial_id"),
            next_part=part,
            created_at=session.get("created_at") or _now(),
        )
        prompt = f"{part}-qismni yuboring."
        if part >= 11:
            await message.answer(prompt, reply_markup=serial_cancel_keyboard())
        else:
            await message.answer(prompt)
        return


@router.message(
    lambda message: (
        message.text
        and not message.text.startswith("/")
        and is_admin(message.from_user.id)
        and message.from_user.id in IMPORT_SESSIONS
    )
)
async def import_text_handler(message: Message):
    session = IMPORT_SESSIONS.get(message.from_user.id) or {}
    state = session.get("state")
    raw = (message.text or "").strip().lower()
    if state == "confirm":
        if raw in {"yo'q", "yoq", "no"}:
            IMPORT_SESSIONS.pop(message.from_user.id, None)
            await message.answer("Import bekor qilindi.")
            return
        await message.answer(
            "Tasdiqlash inline tugmalar orqali qilinadi. Bekor qilish uchun /importcancel."
        )
        return


@router.message(
    lambda message: (
        message
        and message.from_user
        and is_admin(message.from_user.id)
        and message.from_user.id not in RESTORE_DB_SESSIONS
        and message.from_user.id not in POST_SESSIONS
    ),
    F.video | F.document,
)
async def admin_serial_media_handler(message: Message):
    if not _has_perm(message.from_user.id, "can_add_part"):
        if not _has_perm(message.from_user.id, "can_broadcast"):
            await message.answer("Bu buyruq uchun ruxsat yo'q.")
            return
    if message.from_user.id in BROADCAST_TEXT_SESSIONS or message.from_user.id in BROADCAST_SESSIONS:
        BROADCAST_TEXT_SESSIONS.discard(message.from_user.id)
        media = _extract_media_payload(message)
        BROADCAST_SESSIONS[message.from_user.id] = {
            "mode": "media" if media else "reply",
            "media": media,
            "from_chat_id": message.chat.id,
            "reply_message_id": message.message_id,
            "state": "await_attach",
        }
        await message.answer(
            "Dramani biriktirasizmi?",
            reply_markup=_broadcast_attach_keyboard(),
        )
        return
    session = get_serial_session(message.from_user.id)
    if not session or session.get("state") != "await_part":
        return
    serial_id = session.get("serial_id")
    if not serial_id:
        await message.answer("Drama topilmadi. /addserial yoki /addpart ishlating.")
        return
    queue = SERIAL_UPLOAD_QUEUES.setdefault(message.from_user.id, asyncio.PriorityQueue())
    if message.from_user.id not in SERIAL_UPLOAD_TASKS:
        SERIAL_UPLOAD_TASKS[message.from_user.id] = asyncio.create_task(
            _serial_upload_worker(message.from_user.id)
        )
    count = SERIAL_UPLOAD_COUNTERS.get(message.from_user.id, 0) + 1
    SERIAL_UPLOAD_COUNTERS[message.from_user.id] = count
    await queue.put((message.message_id, count, serial_id, message))


@router.message(
    lambda message: (
        message
        and message.from_user
        and message.from_user.id in CONTACT_ADMIN_SESSIONS
    )
)
async def contact_admin_message_handler(message: Message):
    if message.text and message.text.strip().lower() in {"bekor", "/cancel"}:
        CONTACT_ADMIN_SESSIONS.discard(message.from_user.id)
        await message.answer("Bekor qilindi.", reply_markup=ReplyKeyboardRemove())
        await message.answer("Menyu:", reply_markup=user_keyboard())
        return
    await _forward_user_message_to_admins(message, "contact")
    CONTACT_ADMIN_SESSIONS.discard(message.from_user.id)
    await message.answer("Xabaringiz adminlarga yuborildi.", reply_markup=ReplyKeyboardRemove())
    await message.answer("Menyu:", reply_markup=user_keyboard())


@router.message(
    lambda message: (
        message
        and message.from_user
        and message.reply_to_message
        and _is_admin_user(message.from_user.id)
    )
)
async def admin_reply_to_contact_handler(message: Message):
    key = (message.from_user.id, message.reply_to_message.message_id)
    target_id = CONTACT_REPLY_MAP.get(key)
    if not target_id:
        return
    if is_blocked_user(int(target_id)):
        return
    try:
        await message.copy_to(target_id)
    except Exception:
        pass


@router.message(
    lambda message: (
        message
        and message.from_user
        and message.reply_to_message
        and VIP_EXPIRED_NOTICE_MESSAGE_ID.get(message.from_user.id)
        == message.reply_to_message.message_id
    )
)
async def vip_expired_reply_handler(message: Message) -> None:
    if not await ensure_subscribed(message):
        return
    await _forward_user_message_to_admins(message, "vip_expired_reply")
    VIP_EXPIRED_NOTICE_MESSAGE_ID.pop(message.from_user.id, None)
    await message.answer("Xabaringiz adminlarga yuborildi.")

import html

from aiogram.filters import Command, CommandObject

from aiogram.exceptions import (
    TelegramForbiddenError,
    TelegramBadRequest,
    TelegramRetryAfter,
)



@router.message(Command("usend"))
async def userbot_send_handler(message: Message, command: CommandObject):
    """
    Foydalanish:

    1) Text yuborish:
    /usend USER_ID Salom

    2) Media yuborish:
    /usend USER_ID
    (reply qilib)

    """

    if not _has_perm(message.from_user.id, "can_message_users"):
        await message.answer("❌ Sizda ruxsat yo'q.")
        return

    if not command.args:
        await message.answer(
            "📨 Xabar yuborish\n\n"
            "Text yuborish:\n"
            "<code>/usend USER_ID xabar</code>\n\n"
            "Media yuborish:\n"
            "1. User ID yozing\n"
            "2. Xabarga reply qiling\n\n"
            "Misol:\n"
            "<code>/usend 123456789 Salom</code>",
            parse_mode="HTML",
        )
        return

    parts = command.args.split(maxsplit=1)

    try:
        user_id = int(parts[0])
    except ValueError:
        await message.answer(
            "❌ USER_ID noto'g'ri.\n\n"
            "Misol:\n"
            "<code>/usend 123456789 Salom</code>",
            parse_mode="HTML",
        )
        return

    if is_blocked_user(user_id):
        await message.answer(
            "❌ Bu foydalanuvchi bloklangan."
        )
        return

    waiting_msg = await message.answer(
        "⏳ Xabar yuborilmoqda..."
    )

    success = False
    error_text = None

    try:

        # =========================
        # REPLY MESSAGE BO'LSA
        # =========================

        if message.reply_to_message:

            reply = message.reply_to_message

            # reply command message bo'lmasligi uchun
            if reply.message_id == message.message_id:
                await waiting_msg.edit_text(
                    "❌ Xabarga reply qiling."
                )
                return

            await reply.copy_to(chat_id=user_id)

            success = True

        # =========================
        # TEXT YUBORISH
        # =========================

        else:

            if len(parts) < 2:
                await waiting_msg.edit_text(
                    "❌ Xabar matni yo'q.\n\n"
                    "Misol:\n"
                    "<code>/usend 123456789 Salom</code>",
                    parse_mode="HTML",
                )
                return

            text = parts[1].strip()

            if not text:
                await waiting_msg.edit_text(
                    "❌ Xabar bo'sh."
                )
                return

            await message.bot.send_message(
                chat_id=user_id,
                text=text,
            )

            success = True

    except TelegramForbiddenError:
        error_text = (
            "❌ User botni bloklagan\n"
            "yoki /start bosmagan."
        )

    except TelegramBadRequest as e:
        error_text = (
            "❌ Telegram xatosi:\n"
            f"<code>{html.escape(str(e))}</code>"
        )

    except TelegramRetryAfter as e:
        error_text = (
            "⏳ Flood limit.\n"
            f"{e.retry_after} sekund kuting."
        )

    except Exception as e:
        error_text = (
            "❌ Noma'lum xatolik:\n"
            f"<code>{html.escape(str(e))}</code>"
        )

    # =========================
    # NATIJA
    # =========================

    if success:

        await waiting_msg.edit_text(
            "✅ Xabar muvaffaqiyatli yuborildi.\n\n"
            f"👤 User ID: <code>{user_id}</code>",
            parse_mode="HTML",
        )

        _log_event(
            "usend_success",
            message.from_user.id,
            f"target={user_id}",
        )

    else:

        await waiting_msg.edit_text(
            f"{error_text}\n\n"
            f"👤 User ID: <code>{user_id}</code>",
            parse_mode="HTML",
        )

        _log_event(
            "usend_failed",
            message.from_user.id,
            f"target={user_id} error={error_text}",
        )







@router.message(
    lambda message: (
        message
        and message.from_user
        and message.from_user.id in BROADCAST_TEXT_SESSIONS
    ),
    F.photo | F.video | F.document,
)
async def broadcast_media_handler(message: Message):
    if not _has_perm(message.from_user.id, "can_broadcast"):
        BROADCAST_TEXT_SESSIONS.discard(message.from_user.id)
        return
    BROADCAST_TEXT_SESSIONS.discard(message.from_user.id)
    media = _extract_media_payload(message)
    BROADCAST_SESSIONS[message.from_user.id] = {
        "mode": "media" if media else "reply",
        "media": media,
        "from_chat_id": message.chat.id,
        "reply_message_id": message.message_id,
    }
    await message.answer("Kimlarga yuborilsin?", reply_markup=broadcast_target_keyboard())


@router.message(
    F.text,
    lambda message: (
        message
        and message.from_user
        and message.from_user.id in POST_SESSIONS
        and POST_SESSIONS.get(message.from_user.id, {}).get("state") == "await_code"
    ),
)
async def post_code_handler(message: Message):
    if not _has_perm(message.from_user.id, "can_broadcast"):
        return
    code = _parse_code(message.text or "")
    if not code:
        await message.answer("Kod faqat raqam bo'lishi kerak.")
        return
    serial = get_serial_by_code(int(code))
    if not serial:
        await message.answer("Drama topilmadi.")
        return
    parts_count = len(get_serial_parts(serial["id"]))
    session = POST_SESSIONS.get(message.from_user.id)
    if not session:
        return
    session.update(
        {
            "serial_id": serial["id"],
            "title": serial["title"],
            "code": serial["code"],
            "parts_count": parts_count,
        }
    )
    session["state"] = "await_media"
    await message.answer("Rasm yoki video va caption yuboring.", reply_markup=post_media_keyboard())


@router.message(
    F.text,
    lambda message: (
        message
        and message.from_user
        and message.from_user.id in POST_SESSIONS
        and POST_SESSIONS.get(message.from_user.id, {}).get("state") == "await_media"
    ),
)
async def post_caption_handler(message: Message):
    if not _has_perm(message.from_user.id, "can_broadcast"):
        return
    if not message.text:
        return
    session = POST_SESSIONS.get(message.from_user.id)
    if not session:
        return
    session["caption"] = message.text.strip()
    session["caption_entities"] = message.entities or []
    await message.answer("Rasm yoki video yuboring.", reply_markup=post_media_keyboard())


@router.message(
    lambda message: (
        message
        and message.from_user
        and message.from_user.id in VIP_PAYMENT_SESSIONS
    ),
    F.photo | F.document,
)
async def vip_payment_receipt_handler(message: Message):
    VIP_PAYMENT_SESSIONS.discard(message.from_user.id)
    admins = [admin_id for admin_id in get_admins() if has_admin_permission(admin_id, "can_manage_vip")]
    if OWNER_ID and OWNER_ID not in admins:
        admins.append(OWNER_ID)
    username = f"@{message.from_user.username}" if message.from_user.username else "-"
    header = (
        "VIP to'lov cheki.\n"
        f"user_id: {message.from_user.id}\n"
        f"username: {username}"
    )
    for admin_id in admins:
        try:
            sent = await message.bot.send_message(
                admin_id,
                header,
                reply_markup=_vip_receipt_keyboard(message.from_user.id),
            )
            VIP_RECEIPT_MESSAGES.setdefault(message.from_user.id, []).append(
                (admin_id, sent.message_id)
            )
            await message.copy_to(admin_id)
        except Exception:
            continue
    await message.answer("Chek qabul qilindi. Tez orada adminlar tekshiradi.")


@router.message(F.document)
async def restore_db_document_handler(message: Message):
    if message.from_user.id != OWNER_ID:
        return
    session = RESTORE_DB_SESSIONS.get(message.from_user.id)
    if not session or session.get("state") != "await_file":
        return
    await _process_restore_document(message, message.document)


@router.callback_query(F.data.startswith("restoredb:"))
async def restore_db_callback(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID:
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    session = RESTORE_DB_SESSIONS.get(callback.from_user.id)
    if not session or session.get("state") != "await_confirm":
        await callback.answer("Sessiya topilmadi.", show_alert=True)
        return
    action = callback.data.split(":")[-1]
    if action == "cancel":
        _cleanup_restore_session(callback.from_user.id)
        await callback.message.edit_text("DB tiklash bekor qilindi.")
        _log_event("restore_db_cancel", callback.from_user.id)
        return
    if action != "confirm":
        await callback.answer("Xatolik.", show_alert=True)
        return
    db_path = session.get("db_path")
    if not db_path or not os.path.exists(db_path):
        await callback.message.edit_text("DB fayl topilmadi.")
        _cleanup_restore_session(callback.from_user.id)
        return
    backup_path = os.path.join(
        "/tmp",
        f"serialbot-db-backup-{dt.datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.db",
    )
    try:
        if os.path.exists(DB_PATH):
            shutil.copy2(DB_PATH, backup_path)
        shutil.move(db_path, DB_PATH)
        init_db()
    except Exception as exc:
        _log_event("restore_db_error", callback.from_user.id, f"error={exc}")
        await callback.message.edit_text("DB tiklashda xatolik.")
        _cleanup_restore_session(callback.from_user.id)
        return
    _cleanup_restore_session(callback.from_user.id)
    await callback.message.edit_text("DB tiklandi.")
    _log_event("restore_db_success", callback.from_user.id, f"backup={backup_path}")


@router.message(
    F.photo | F.document | F.video,
    lambda message: (
        message
        and message.from_user
        and message.from_user.id in POST_SESSIONS
        and POST_SESSIONS.get(message.from_user.id, {}).get("state") == "await_media"
    ),
)
async def post_photo_handler(message: Message):
    if not _has_perm(message.from_user.id, "can_broadcast"):
        return
    session = POST_SESSIONS.get(message.from_user.id)
    if not session:
        return
    if session.get("state") != "await_media":
        return
    if message.document:
        mime_type = message.document.mime_type or ""
        if not (mime_type.startswith("image/") or mime_type.startswith("video/")):
            await message.answer("Faqat rasm yoki video yuboring.")
            return
    caption = message.caption or session.get("caption") or ""
    caption_entities = message.caption_entities or session.get("caption_entities")
    if not caption.strip():
        await message.answer("Caption yuboring yoki avval matn yuboring.")
        return
    link = await _get_start_link(message.bot, int(session["code"]))
    if not link:
        await message.answer("Bot linkini olishda xatolik.")
        return
    try:
        if message.video:
            await message.bot.send_video(
                chat_id=int(session["channel_id"]),
                video=message.video.file_id,
                caption=caption,
                caption_entities=caption_entities,
                reply_markup=post_link_keyboard(link),
            )
        elif message.photo:
            photo = message.photo[-1]
            await message.bot.send_photo(
                chat_id=int(session["channel_id"]),
                photo=photo.file_id,
                caption=caption,
                caption_entities=caption_entities,
                reply_markup=post_link_keyboard(link),
            )
        else:
            await message.bot.send_document(
                chat_id=int(session["channel_id"]),
                document=message.document.file_id,
                caption=caption,
                caption_entities=caption_entities,
                reply_markup=post_link_keyboard(link),
            )
    except Exception:
        await message.answer("Kanalga yuborishda xatolik.")
        return
    POST_SESSIONS.pop(message.from_user.id, None)
    await message.answer("Post kanalga yuborildi.")
    _log_event(
        "post_created",
        message.from_user.id,
        f"serial_id={session['serial_id']} channel_id={session.get('channel_id')}",
    )


async def _show_serial_parts(message: Message, serial_id: int) -> bool:
    user_id = message.from_user.id if message.from_user else 0
    return await _show_serial_parts_for_user(message, serial_id, user_id=user_id)


def _serial_part_numbers_with_vip(serial: Optional[dict], parts_rows: list[dict]) -> tuple[list[int], set[int]]:
    part_numbers = [int(item["part"]) for item in parts_rows if item.get("part") is not None]
    part_numbers_sorted = sorted(set(part_numbers))
    vip_parts = {
        int(item["part"])
        for item in parts_rows
        if item.get("part") is not None and int(item.get("is_vip") or 0) == 1
    }
    if serial and serial.get("is_vip"):
        vip_parts = set(part_numbers_sorted)
    return part_numbers_sorted, vip_parts


async def _show_serial_parts_for_user(message: Message, serial_id: int, user_id: int) -> bool:

    try:
        await message.delete()
    except:
        pass

    all_parts = get_serial_parts(serial_id)
    serial = get_serial_by_id(serial_id)
    if not all_parts:
        return False
    part_numbers_sorted, vip_parts = _serial_part_numbers_with_vip(serial, all_parts)
    if not part_numbers_sorted:
        return False
    parts_count = len(part_numbers_sorted)
    share_link = (
        await _get_share_link(
            message.bot,
            int(serial["code"]),
            serial.get("title") or "",
            parts_count,
        )
        if serial
        else None
    )
    part_link_prefix = None
    if message.chat.type in {"group", "supergroup"} and serial:
        part_link_prefix = await _get_start_link_with_payload(
            message.bot,
            f"{int(serial['code'])}_",
        )
    show_rating = message.chat.type not in {"group", "supergroup"}
    likes_count, dislikes_count = get_serial_rating_counts(serial_id)
    has_vip_parts = bool(serial and serial.get("is_vip")) or any(int(p.get("is_vip") or 0) for p in all_parts)
    if serial and has_vip_parts:
        title = _pretty_title_text(f"💎 {serial.get('title') or '-'}")
    else:
        title = _pretty_title_text(serial.get("title") or "-") if serial else "-"
    sent = await message.answer(
        f"Drama nomi: {title}\nQismlar soni: {parts_count}",
        reply_markup=serial_parts_keyboard(
            serial_id,
            part_numbers_sorted,
            page=0,
            per_page=SERIAL_PARTS_PER_PAGE,
            vip_parts=vip_parts,
            share_link=share_link,
            part_link_prefix=part_link_prefix,
            show_rating=show_rating,
            notify_enabled=_is_serial_notify_enabled(user_id, serial_id),
            rating=get_serial_rating(user_id, serial_id),
            likes_count=likes_count,
            dislikes_count=dislikes_count,
        ),
    )
    
    if sent:
        async def delete_later():
            await asyncio.sleep(60)
            try:
                await sent.delete()
            except:
                pass

        asyncio.create_task(delete_later())
    return True


async def _send_serial_part(
    message: Message,
    serial_id: int,
    part: int,
    part_numbers: Optional[list[int]] = None,
    user_id: Optional[int] = None,
) -> bool:

    requester_id = user_id if user_id is not None else (message.from_user.id if message.from_user else 0)
    item = get_serial_part(serial_id, part)
    if not item:
        return False
    caption = item.get("caption") or None
    serial = get_serial_by_id(serial_id)
    part_is_vip = int(item.get("is_vip") or 0) == 1

    


    if serial and serial.get("is_vip") and not _is_admin_user(requester_id) and not _is_vip_user(requester_id):
        await _send_vip_required(message, headline="Bu drama VIP.")
        return False
    if part_is_vip and not _is_admin_user(requester_id) and not _is_vip_user(requester_id):
        await _send_vip_required(message, headline="Bu qism VIP.")
        return False
    if serial:
        record_serial_view(_today(), int(serial["code"]))
        record_user_serial_view(
            requester_id,
            int(serial["id"]),
            dt.datetime.utcnow().isoformat(),
        )
    if part_numbers is None:
        all_parts = get_serial_parts(serial_id)
        part_numbers, _vip_parts = _serial_part_numbers_with_vip(serial, all_parts)
    part_numbers_sorted = sorted(part_numbers) if part_numbers else []
    parts_count = len(part_numbers_sorted)
    share_link = (
        await _get_share_link(
            message.bot,
            int(serial["code"]),
            serial.get("title") or "",
            parts_count,
        )
        if serial
        else None
    )
    page = 0
    if part_numbers_sorted:
        try:
            index = part_numbers_sorted.index(part)
            page = index // SERIAL_PARTS_PER_PAGE
        except ValueError:
            page = 0
    likes_count, dislikes_count = get_serial_rating_counts(serial_id)
    part_link_prefix = None
    if message.chat.type in {"group", "supergroup"} and serial:
        part_link_prefix = await _get_start_link_with_payload(
            message.bot,
            f"{int(serial['code'])}_",
        )
    show_rating = message.chat.type not in {"group", "supergroup"}
    reply_markup = serial_nav_keyboard(
        serial_id,
        part_numbers_sorted or [part],
        current_part=part,
        part_link_prefix=part_link_prefix,
        show_rating=show_rating,
        notify_enabled=_is_serial_notify_enabled(requester_id, serial_id),
        rating=get_serial_rating(requester_id, serial_id),
        likes_count=likes_count,
        dislikes_count=dislikes_count,
    )
    source_chat_id = item.get("source_chat_id")
    source_message_id = item.get("source_message_id")
    sent_message = None
    if source_chat_id and source_message_id:
        copied = await _safe_copy_message(
            message.bot,
            message.chat.id,
            source_chat_id,
            source_message_id,
        )
        if copied:
            sent_message = copied
            if reply_markup:
                await _safe_edit_reply_markup(
                    message.bot,
                    message.chat.id,
                    copied.message_id,
                    reply_markup,
                )
    if sent_message is None:
        if item.get("file_type") == "document":
            sent_message = await _safe_send_document(
                message,
                item["file_id"],
                caption,
                reply_markup=reply_markup,
            )
        else:
            sent_message = await _safe_send_video(
                message,
                item["file_id"],
                caption,
                reply_markup=reply_markup,
            )
    if sent_message:
        if part_is_vip and not _is_admin_user(message.from_user.id):
            _schedule_delete_message(message.bot, message.chat.id, sent_message.message_id)
        _schedule_inline_expire(message.bot, message.chat.id, sent_message.message_id)
        return True
    if not sent_message:
        await message.answer("Dramani yuborib bo'lmadi.")
        _log_event(
            "serial_send_failed",
            message.from_user.id if message.from_user else None,
            f"serial_id={serial_id} part={part}",
        )
        return False
    return True




@router.message(Command("movie"))
async def movie_command_disabled(message: Message, command: CommandObject):
    await message.answer("Kino funksiyalari o'chirilgan.")


async def _handle_serial_request(message: Message, raw: str) -> None:
    _log_event("serial_request", message.from_user.id, f"query={raw}")
    serial = None
    if raw.isdigit():
        serial = get_serial_by_code(int(raw))
    if not serial:
        serial = get_serial_by_title(raw)
    if not serial:
        await message.answer("Drama topilmadi.")
        return
    if not await _ensure_serial_access(message, serial):
        return
    if not await _show_serial_parts(message, serial["id"]):
        await message.answer("Dramada qismlar yo'q.")


@router.message(Command("serial"))
async def serial_command_handler(message: Message, command: CommandObject):
    if not command.args:
        await message.answer("Foydalanish: /serial <drama_nomi|kod>")
        return
    raw = command.args.strip()
    await _handle_serial_request(message, raw)


@router.message(Command("search"))
async def search_command_handler(message: Message, command: CommandObject):
    if not await ensure_subscribed(message):
        return
    query = (command.args or "").strip()
    if not query:
        USER_SEARCH_SESSIONS.add(message.from_user.id)
        USER_SEARCH_RESULTS.pop(message.from_user.id, None)
        await message.answer("Drama nomini yozing:", reply_markup=user_search_keyboard())
        return
    raw = query
    include_vip = _include_vip_serials(message.from_user.id)
    total = count_serials_by_title(raw, include_vip)
    if total == 0:
        query_norm = _normalize_search_text(raw)
        serials = []
        for item in get_serials():
            title = item.get("title") or ""
            title_norm = _normalize_search_text(title)
            if query_norm and query_norm in title_norm:
                serials.append(item)
        serials = _filter_serials_for_user(message.from_user.id, serials)
        if not serials:
            suggestions = _suggest_serial_titles(message.from_user.id, raw, limit=5)
            if suggestions:
                lines = ["Drama topilmadi. Balki shularni nazarda tutgandirsiz:"]
                lines.extend(f"- {title}" for title in suggestions)
                await message.answer("\n".join(lines), reply_markup=user_keyboard())
            else:
                await message.answer("Drama topilmadi.", reply_markup=user_keyboard())
            return
        total = len(serials)
        total_pages = max(1, (total + USER_SERIALS_PER_PAGE - 1) // USER_SERIALS_PER_PAGE)
        page_serials = serials[:USER_SERIALS_PER_PAGE]
        USER_SERIALS_LIST[message.from_user.id] = {
            "mode": "search_local",
            "serials": serials,
            "page": 0,
            "total_pages": total_pages,
            "page_serials": page_serials,
        }
        await message.answer(
            "Natijalar:",
            reply_markup=user_serials_menu_keyboard(page_serials, 0, total_pages),
        )
        return
    total_pages = max(1, (total + USER_SERIALS_PER_PAGE - 1) // USER_SERIALS_PER_PAGE)
    page_serials = search_serials_by_title(raw, include_vip, USER_SERIALS_PER_PAGE, 0)
    USER_SERIALS_LIST[message.from_user.id] = {
        "mode": "search_db",
        "query": raw,
        "include_vip": include_vip,
        "page": 0,
        "total_pages": total_pages,
        "page_serials": page_serials,
    }
    await message.answer(
        "Natijalar:",
        reply_markup=user_serials_menu_keyboard(page_serials, 0, total_pages),
    )


@router.message(Command("drama"))
async def drama_command_handler(message: Message, command: CommandObject):
    if message.chat.type in {"group", "supergroup"}:
        if await _maybe_restrict_group_spam(message):
            return
        if not await _is_bot_admin_in_group(message):
            await message.answer("Botni admin qilib qo'shing.")
            return
    if not command.args:
        await message.answer("Foydalanish: /drama <drama_nomi|kod>")
        return
    raw = command.args.strip()
    await _handle_serial_request(message, raw)


@router.message(F.text & ~F.text.startswith("/"))
async def movie_text_handler(message: Message):
    if message.chat.type in {"group", "supergroup"}:
        return
    session = BROADCAST_SESSIONS.get(message.from_user.id)
    if session and session.get("state") == "await_serial_code":
        raw = (message.text or "").strip()
        code = _parse_code(raw)
        if not code:
            await message.answer("Kod faqat raqam bo'lishi kerak.")
            return
        serial = get_serial_by_code(int(code))
        if not serial:
            await message.answer("Drama topilmadi.")
            return
        session["serial_code"] = int(serial["code"])
        session["state"] = "ready"
        await message.answer(
            "Kimlarga yuborilsin?",
            reply_markup=broadcast_target_keyboard(),
        )
        return
    if not await ensure_subscribed(message):
        return
    if message.from_user.id in SERIAL_RENAME_SESSIONS:
        if not _has_perm(message.from_user.id, "can_add_serial"):
            SERIAL_RENAME_SESSIONS.pop(message.from_user.id, None)
            return
        if message.text.strip().lower() in {"/cancel", "bekor"}:
            SERIAL_RENAME_SESSIONS.pop(message.from_user.id, None)
            await message.answer("Bekor qilindi.")
            return
        new_title = message.text.strip()
        if not new_title:
            await message.answer("Yangi nom bo'sh bo'lmasin.")
            return
        serial_id = SERIAL_RENAME_SESSIONS.pop(message.from_user.id, None)
        if not serial_id:
            return
        rename_serial(serial_id, new_title)
        await message.answer("Drama nomi yangilandi.")
        _log_event("serial_renamed", message.from_user.id, f"serial_id={serial_id}")
        return
    if message.from_user.id in BROADCAST_TEXT_SESSIONS:
        await broadcast_text_handler(message)
        return
    if message.from_user.id in VIP_PRICE_SESSIONS:
        VIP_PRICE_SESSIONS.discard(message.from_user.id)
        raw = message.text.strip().replace(" ", "")
        if not raw.isdigit():
            await message.answer("Narx raqam bo'lishi kerak.")
            return
        set_setting(VIP_PRICE_KEY, raw)
        await message.answer(f"VIP oylik narx: {raw} so'm")
        return
    if message.from_user.id in VIP_MESSAGE_SESSIONS:
        VIP_MESSAGE_SESSIONS.discard(message.from_user.id)
        text = message.text.strip()
        if not text:
            await message.answer("VIP xabari bo'sh bo'lmasin.")
            return
        set_setting(VIP_MESSAGE_KEY, text)
        await message.answer("VIP xabari saqlandi.")
        return
    if message.from_user.id in VIP_REJECT_SESSIONS:
        if not _has_perm(message.from_user.id, "can_manage_vip"):
            VIP_REJECT_SESSIONS.pop(message.from_user.id, None)
            return
        reason = message.text.strip()
        if not reason:
            await message.answer("Rad etish sababini yuboring.")
            return
        target_id = VIP_REJECT_SESSIONS.pop(message.from_user.id, None)
        if target_id:
            try:
                await message.bot.send_message(
                    target_id,
                    "VIP to'lov cheki rad etildi.\n"
                    f"Sabab: {reason}",
                )
            except Exception:
                pass
            admin_label = f"@{message.from_user.username}" if message.from_user.username else str(message.from_user.id)
            admins = [admin_id for admin_id in get_admins() if has_admin_permission(admin_id, "can_manage_vip")]
            if OWNER_ID and OWNER_ID not in admins:
                admins.append(OWNER_ID)
            notify_text = (
                "VIP cheki rad etildi.\n"
                f"user_id: {target_id}\n"
                f"Rad qilgan: {admin_label}\n"
                f"Sabab: {reason}"
            )
            for admin_id in admins:
                if admin_id == message.from_user.id:
                    continue
                try:
                    await message.bot.send_message(admin_id, notify_text)
                except Exception:
                    continue
            await _update_receipt_status(
                message.bot,
                target_id,
                f"Chek rad etilgan. Rad qilgan: {admin_label}",
            )
        await message.answer("Rad etish sababi yuborildi.")
        return
    if message.from_user.id in VIP_CARD_SESSIONS:
        if not _has_perm(message.from_user.id, "can_manage_vip"):
            VIP_CARD_SESSIONS.discard(message.from_user.id)
            return
        text = message.text.strip()
        if not text:
            await message.answer("Rekvizit bo'sh bo'lmasin.")
            return
        number = ""
        owner = ""
        if "|" in text:
            parts = [part.strip() for part in text.split("|", 1)]
            if len(parts) == 2:
                number, owner = parts
        elif "\n" in text:
            parts = [part.strip() for part in text.splitlines() if part.strip()]
            if len(parts) >= 2:
                number, owner = parts[0], parts[1]
        if not number or not owner:
            await message.answer(
                "Format noto'g'ri. Misol:\n8600 0000 0000 0000 | FIO"
            )
            return
        set_setting(VIP_CARD_NUMBER_KEY, number)
        set_setting(VIP_CARD_OWNER_KEY, owner)
        VIP_CARD_SESSIONS.discard(message.from_user.id)
        await message.answer("VIP rekvizit saqlandi.")
        return
    raw = message.text.strip()
    if raw == "Drama kodini yuborish":
        if is_admin(message.from_user.id) and get_serial_session(message.from_user.id):
            clear_serial_session(message.from_user.id)
        await message.answer("Drama kodini yuboring.")
        return
    state = USER_SERIALS_LIST.get(message.from_user.id)
    if state:
        serials = state.get("page_serials") or []
        raw_norm = _normalize_search_text(raw)
        for item in serials:
            title = item.get("title") or ""
            if _normalize_search_text(title) == raw_norm:
                if not await _ensure_serial_access(message, item):
                    return
                if await _show_serial_parts(message, item["id"]):
                    return
                await message.answer("Dramada qismlar yo'q.")
                return
    if raw == "Dramalar ro'yxati":
        await _send_user_serials_menu(message, page=0)
        return
    if raw == "Drama qidirish":
        await message.answer("Qidirish uchun /search buyrug'idan foydalaning.")
        return
    if raw == "Ortga":
        USER_SERIALS_LIST.pop(message.from_user.id, None)
        USER_SEARCH_SESSIONS.discard(message.from_user.id)
        USER_SEARCH_RESULTS.pop(message.from_user.id, None)
        await message.answer("Menyu:", reply_markup=user_keyboard())
        return
    if raw in {"⬅️ Oldingi", "➡️ Keyingi"}:
        state = USER_SERIALS_LIST.get(message.from_user.id)
        if not state:
            await _send_user_serials_menu(message, page=0)
            return
        mode = state.get("mode") or "list"
        page = int(state.get("page") or 0)
        total_pages = int(state.get("total_pages") or 1)
        if raw == "⬅️ Oldingi":
            page = max(0, page - 1)
        else:
            page = min(total_pages - 1, page + 1)
        state["page"] = page
        if mode == "search_db":
            query = state.get("query") or ""
            include_vip = bool(state.get("include_vip"))
            page_serials = search_serials_by_title(
                query,
                include_vip,
                USER_SERIALS_PER_PAGE,
                page * USER_SERIALS_PER_PAGE,
            )
        else:
            serials = state.get("serials") or []
            start = page * USER_SERIALS_PER_PAGE
            end = start + USER_SERIALS_PER_PAGE
            page_serials = serials[start:end]
        state["page_serials"] = page_serials
        await message.answer(
            "Dramalar ro'yxati:",
            reply_markup=user_serials_menu_keyboard(page_serials, page, total_pages),
        )
        return
    if message.from_user.id in USER_SEARCH_SESSIONS:
        query = raw
        USER_SEARCH_SESSIONS.discard(message.from_user.id)
        if not query:
            await message.answer("Drama nomini yozing.", reply_markup=user_search_keyboard())
            return
        include_vip = _include_vip_serials(message.from_user.id)
        total = count_serials_by_title(query, include_vip)
        if total == 0:
            query_norm = _normalize_search_text(query)
            serials = []
            for item in get_serials():
                title = item.get("title") or ""
                title_norm = _normalize_search_text(title)
                if query_norm and query_norm in title_norm:
                    serials.append(item)
            serials = _filter_serials_for_user(message.from_user.id, serials)
            if not serials:
                await message.answer("Drama topilmadi.", reply_markup=user_keyboard())
                return
            total = len(serials)
            total_pages = max(1, (total + USER_SERIALS_PER_PAGE - 1) // USER_SERIALS_PER_PAGE)
            page_serials = serials[:USER_SERIALS_PER_PAGE]
            USER_SERIALS_LIST[message.from_user.id] = {
                "mode": "search_local",
                "serials": serials,
                "page": 0,
                "total_pages": total_pages,
                "page_serials": page_serials,
            }
            await message.answer(
                "Natijalar:",
                reply_markup=user_serials_menu_keyboard(page_serials, 0, total_pages),
            )
            return
        total_pages = max(1, (total + USER_SERIALS_PER_PAGE - 1) // USER_SERIALS_PER_PAGE)
        page_serials = search_serials_by_title(query, include_vip, USER_SERIALS_PER_PAGE, 0)
        USER_SERIALS_LIST[message.from_user.id] = {
            "mode": "search_db",
            "query": query,
            "include_vip": include_vip,
            "page": 0,
            "total_pages": total_pages,
            "page_serials": page_serials,
        }
        await message.answer(
            "Natijalar:",
            reply_markup=user_serials_menu_keyboard(page_serials, 0, total_pages),
        )
        return
    code = _parse_code(raw)
    if code:
        _log_event("serial_request", message.from_user.id, f"query={code}")
        serial = get_serial_by_code(int(code))
        if serial:
            if not await _ensure_serial_access(message, serial):
                return
            if await _show_serial_parts(message, serial["id"]):
                return
            await message.answer("Drama topilmadi.")
            return
        await message.answer("Drama topilmadi.")
        return
    if is_admin(message.from_user.id) and get_serial_session(message.from_user.id):
        return
    serial = get_serial_by_title(raw)
    _log_event("serial_request", message.from_user.id, f"query={raw}")
    if serial:
        if not await _ensure_serial_access(message, serial):
            return
        if await _show_serial_parts(message, serial["id"]):
            return
        await message.answer("Drama topilmadi.")
        return
    await message.answer("Drama topilmadi.")


@router.message(Command("stats"))
async def stats_handler(message: Message):
    if message.chat.type in {"group", "supergroup"}:
        return
    if not _has_perm(message.from_user.id, "can_view_stats"):
        await message.answer("Bu buyruq uchun ruxsat yo'q.")
        return
    day = _today()
    total, top = get_serial_day_stats(day)
    lines = [f"Bugungi ko'rishlar: {total}"]
    if top:
        lines.append("Top drama kodlari:")
        lines.extend([f"{code} - {count}" for code, count in top])
    recent = get_serial_recent_days()
    if recent:
        lines.append("So'nggi kunlar:")
        lines.extend([f"{d}: {c}" for d, c in recent])
    await message.answer("\n".join(lines))
    _log_event("stats_view", message.from_user.id)


@router.message(Command("vip"))
async def vip_info_handler(message: Message):
    await _send_vip_info(message, message.from_user.id)


@router.message(Command("myvip"))
async def myvip_info_handler(message: Message):
    await _send_vip_info(message, message.from_user.id)


@router.message(Command("settings"))
async def settings_handler(message: Message):
    if not await ensure_subscribed(message):
        return
    text = (
        "Sozlamalar:\n"
        "- Bildirishnomalar (🔔) har bir drama uchun alohida.\n"
        "- Qism (video) ostidagi 🔔 tugmasi orqali yoqib/o'chirasiz.\n"
        "- Like/Dislike: 👍 / 👎 tugmalari orqali baho berasiz."
    )
    await message.answer(text)


async def _send_backup(message: Message) -> None:
    backup_path = _build_backup_zip()
    if not backup_path:
        await message.answer("Backup uchun fayl topilmadi.")
        return
    try:
        await message.answer_document(FSInputFile(backup_path), caption="Backup")
    finally:
        try:
            os.remove(backup_path)
        except Exception:
            pass


async def _send_log_file(message: Message) -> None:
    if not os.path.exists(LOG_PATH):
        await message.answer("Log fayli topilmadi.")
        return
    await message.answer_document(FSInputFile(LOG_PATH), caption="Log fayli")


async def vip_reminder_loop(bot) -> None:
    tz = ZoneInfo(BACKUP_TZ)
    while True:
        try:
            await _run_vip_expired_notifications(bot, tz)
            await _run_vip_reminders(bot)
        except Exception:
            pass
        await asyncio.sleep(VIP_REMINDER_INTERVAL)


async def cache_cleanup_loop() -> None:
    if CACHE_CLEAN_INTERVAL <= 0:
        return
    while True:
        await asyncio.sleep(CACHE_CLEAN_INTERVAL)
        try:
            cleanup_sessions()
            for user_id in list(USER_SEARCH_RESULTS.keys()):
                if user_id not in USER_SEARCH_SESSIONS:
                    USER_SEARCH_RESULTS.pop(user_id, None)
            for user_id in list(BROADCAST_SESSIONS.keys()):
                if user_id not in BROADCAST_TEXT_SESSIONS:
                    BROADCAST_SESSIONS.pop(user_id, None)
        except Exception:
            pass


def _seconds_until_next_backup(now: dt.datetime, tz: ZoneInfo) -> float:
    local_now = now.astimezone(tz)
    next_hour = (local_now + dt.timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    return (next_hour - local_now).total_seconds()


def _build_recommendation_target(day: dt.date, tz: ZoneInfo) -> dt.datetime:
    start = dt.datetime(
        day.year,
        day.month,
        day.day,
        RECOMMENDATION_WINDOW_START,
        0,
        0,
        tzinfo=tz,
    )
    end = dt.datetime(
        day.year,
        day.month,
        day.day,
        RECOMMENDATION_WINDOW_END,
        0,
        0,
        tzinfo=tz,
    )
    minutes_range = int((end - start).total_seconds() // 60)
    offset_minutes = random.randint(0, max(0, minutes_range))
    return start + dt.timedelta(minutes=offset_minutes)


def _get_next_recommendation_run(now: dt.datetime, tz: ZoneInfo) -> dt.datetime:
    local_now = now.astimezone(tz)
    stored = get_setting(RECOMMENDATION_NEXT_RUN_KEY)
    if stored:
        try:
            candidate = dt.datetime.fromisoformat(stored)
        except Exception:
            candidate = None
        if candidate and candidate.tzinfo:
            if candidate > local_now:
                return candidate
    today = local_now.date()
    target = _build_recommendation_target(today, tz)
    if target <= local_now:
        target = _build_recommendation_target(today + dt.timedelta(days=1), tz)
    set_setting(RECOMMENDATION_NEXT_RUN_KEY, target.isoformat())
    return target


def _should_prepare_recommendations(now: dt.datetime) -> bool:
    last_activity = get_setting(LAST_ACTIVITY_AT_KEY)
    if not last_activity:
        return True
    try:
        last_dt = dt.datetime.fromisoformat(last_activity)
    except Exception:
        return True
    return (now - last_dt).total_seconds() >= RECOMMENDATION_IDLE_SECONDS


async def backup_schedule_loop(bot) -> None:
    tz = ZoneInfo(BACKUP_TZ)
    while True:
        try:
            delay = _seconds_until_next_backup(dt.datetime.utcnow(), tz)
            await asyncio.sleep(max(60, delay))
            path = _build_scheduled_backup()
            if path:
                if OWNER_ID:
                    await bot.send_document(BACKUP_CHANNEL_ID, FSInputFile(path), caption="Backup")
                _log_event("backup_scheduled", None, f"path={path}")
        except Exception:
            pass


async def daily_recommendation_loop(bot) -> None:
    tz = ZoneInfo(BACKUP_TZ)
    while True:
        try:
            now = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
            target = _get_next_recommendation_run(now, tz)
            delay = (target - now.astimezone(tz)).total_seconds()
            await asyncio.sleep(max(60, delay))
            await _send_daily_recommendation(bot, tz)
        except Exception:
            pass


async def daily_recommendation_prepare_loop(bot) -> None:
    tz = ZoneInfo(BACKUP_TZ)
    while True:
        try:
            await asyncio.sleep(300)
            now_utc = dt.datetime.utcnow()
            local_now = now_utc.replace(tzinfo=dt.timezone.utc).astimezone(tz)
            today = local_now.date().isoformat()
            if get_setting(RECOMMENDATION_PREPARED_DATE_KEY) == today:
                continue
            if not _should_prepare_recommendations(now_utc):
                continue
            await _prepare_daily_recommendations(bot, local_now.date())
        except Exception:
            pass


def _pick_user_recommendation(
    user_id: int,
    top_liked: list[dict],
) -> Optional[dict]:
    candidate_ids = get_similar_serials_by_likes(user_id, limit=10)
    if not candidate_ids:
        candidate_ids = get_similar_serials_by_views(user_id, limit=10, seed_limit=5)
    if candidate_ids:
        for serial_id in candidate_ids:
            serial = get_serial_by_id(int(serial_id))
            if serial:
                return serial
    liked_ids = set(get_user_liked_serial_ids(user_id, limit=200))
    viewed_ids = set(get_user_viewed_serial_ids(user_id, limit=200))
    seen_ids = liked_ids | viewed_ids
    for item in top_liked:
        serial_id = int(item.get("id") or 0)
        if serial_id and serial_id not in seen_ids:
            return item
    return None


async def _prepare_daily_recommendations(bot, day: dt.date) -> None:
    today = day.isoformat()
    if get_setting(RECOMMENDATION_PREPARED_DATE_KEY) == today:
        return
    active_users = get_active_user_ids(3)
    if not active_users:
        set_setting(RECOMMENDATION_PREPARED_DATE_KEY, today)
        return
    top_liked = get_top_liked_serials(50, include_vip=True)
    for user_id in active_users:
        if is_blocked_user(int(user_id)):
            continue
        serial = _pick_user_recommendation(int(user_id), top_liked)
        if not serial:
            continue
        serial_id = serial.get("id")
        if serial_id is None:
            continue
        set_user_daily_recommendation(today, int(user_id), int(serial_id))
    set_setting(RECOMMENDATION_PREPARED_DATE_KEY, today)


async def _send_daily_recommendation(bot, tz: ZoneInfo) -> None:
    local_now = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc).astimezone(tz)
    today = local_now.date().isoformat()
    if get_setting(RECOMMENDATION_LAST_DATE_KEY) == today:
        next_day = local_now.date() + dt.timedelta(days=1)
        target = _build_recommendation_target(next_day, tz)
        set_setting(RECOMMENDATION_NEXT_RUN_KEY, target.isoformat())
        return
    total_users = count_users()
    if total_users == 0:
        return
    top_liked = get_top_liked_serials(50, include_vip=True)
    fallback_serial = top_liked[0] if top_liked else None
    serial_cache: dict[int, dict] = {}
    ok = 0
    failed = 0
    counter = 0
    for batch in iter_user_ids():
        rec_map = get_user_daily_recommendations_for_users(today, batch)
        for user_id in batch:
            if is_blocked_user(int(user_id)):
                continue
            serial_id = rec_map.get(int(user_id))
            serial = None
            if serial_id is not None:
                serial = serial_cache.get(serial_id)
                if serial is None:
                    serial = get_serial_by_id(int(serial_id))
                    if serial:
                        serial_cache[int(serial_id)] = serial
            if serial is None:
                serial = fallback_serial
            if not serial or serial.get("id") is None:
                continue
            try:
                if await _send_serial_part_to_user(bot, int(user_id), int(serial["id"])):
                    ok += 1
                else:
                    failed += 1
            except TelegramAPIError as exc:
                _log_event("recommend_failed", None, f"user_id={user_id} error={exc}")
                failed += 1
            except Exception:
                _log_event("recommend_failed", None, f"user_id={user_id} error=unknown")
                failed += 1
            counter += 1
            if BROADCAST_BATCH_EVERY and BROADCAST_BATCH_SLEEP and counter % BROADCAST_BATCH_EVERY == 0:
                await asyncio.sleep(BROADCAST_BATCH_SLEEP)
    set_setting(RECOMMENDATION_LAST_DATE_KEY, today)
    next_day = local_now.date() + dt.timedelta(days=1)
    target = _build_recommendation_target(next_day, tz)
    set_setting(RECOMMENDATION_NEXT_RUN_KEY, target.isoformat())
    _log_event("daily_recommendation", None, f"ok={ok} failed={failed}")


async def _run_vip_reminders(bot) -> None:
    users = get_vip_users()
    if not users:
        return
    now = dt.datetime.utcnow()
    price = _get_vip_price()
    for item in users:
        if is_blocked_user(int(item["user_id"])):
            continue
        try:
            expires_at = dt.datetime.fromisoformat(item["expires_at"])
        except Exception:
            continue
        days_left = (expires_at.date() - now.date()).days
        if days_left == 7 and not item.get("reminded_7d"):
            text = "VIP obuna muddati 7 kundan so'ng tugaydi."
            if price:
                text += f" Oylik narx: {price} so'm."
            try:
                await bot.send_message(item["user_id"], text)
                mark_vip_reminder(item["user_id"], 7)
            except Exception:
                pass
        if days_left == 2 and not item.get("reminded_2d"):
            text = "VIP obuna muddati 2 kundan so'ng tugaydi."
            if price:
                text += f" Oylik narx: {price} so'm."
            try:
                await bot.send_message(item["user_id"], text)
                mark_vip_reminder(item["user_id"], 2)
            except Exception:
                pass
        if days_left == 1 and not item.get("reminded_1d"):
            text = "VIP obuna muddati 1 kundan so'ng tugaydi."
            if price:
                text += f" Oylik narx: {price} so'm."
            try:
                await bot.send_message(item["user_id"], text)
                mark_vip_reminder(item["user_id"], 1)
            except Exception:
                pass


async def _run_vip_expired_notifications(bot, tz: ZoneInfo) -> None:
    now_utc = dt.datetime.utcnow()
    local_now = now_utc.astimezone(tz)
    if local_now.hour < VIP_EXPIRED_NOTIFY_HOUR:
        return
    today = local_now.date().isoformat()
    if get_setting(VIP_EXPIRED_NOTIFY_LAST_DATE_KEY) == today:
        return
    users = get_vip_users()
    for item in users:
        user_id = int(item["user_id"])
        if is_blocked_user(user_id):
            continue
        try:
            expires_at = dt.datetime.fromisoformat(item["expires_at"])
        except Exception:
            continue
        expires_date = expires_at.date()
        expires_at_local = dt.datetime(
            expires_date.year,
            expires_date.month,
            expires_date.day,
            VIP_EXPIRED_NOTIFY_HOUR,
            0,
            0,
            tzinfo=tz,
        )
        if local_now < expires_at_local:
            continue
        remove_vip_user(user_id)
        try:
            sent = await bot.send_message(
                user_id,
                "VIP obuna muddati tugadi.\n"
                "Savol bo'lsa adminlarga yozing: /contact",
            )
            VIP_EXPIRED_NOTICE_MESSAGE_ID[user_id] = sent.message_id
        except Exception:
            pass
        if OWNER_ID and int(OWNER_ID) != user_id:
            try:
                await bot.send_message(
                    int(OWNER_ID),
                    f"VIP obuna tugadi: user_id={user_id} (muddati: {expires_date.isoformat()})",
                )
            except Exception:
                pass
    set_setting(VIP_EXPIRED_NOTIFY_LAST_DATE_KEY, today)


def _is_vip_part_expired(created_at: Optional[str]) -> bool:
    if not created_at:
        return False
    try:
        created = dt.datetime.fromisoformat(created_at)
    except Exception:
        return False
    return created <= (dt.datetime.utcnow() - dt.timedelta(hours=24))


async def _process_serial_part_message(message: Message, serial_id: int) -> None:
    if not _has_perm(message.from_user.id, "can_add_part"):
        await message.answer("Bu buyruq uchun ruxsat yo'q.")
        return
    key = (message.from_user.id, serial_id)
    part = SERIAL_UPLOAD_NEXT_PART.get(key)
    if part is None:
        part = _next_missing_part(serial_id)
    while serial_part_exists(serial_id, part):
        part += 1
    SERIAL_UPLOAD_NEXT_PART[key] = part
    file_id, file_type, caption = _extract_media(message)
    if not file_id:
        await message.answer("Faqat video yoki document qabul qilinadi.")
        return
    if not SOURCE_CHANNEL_ID:
        await message.answer("SOURCE_CHANNEL_ID sozlanmagan.")
        return
    safe_caption = _strip_links(caption or "")
    msg = await _safe_send_to_channel(
        message.bot,
        SOURCE_CHANNEL_ID,
        file_id,
        file_type,
        safe_caption,
    )
    if not msg:
        await message.answer("Kanalga yuklab bo'lmadi.")
        return
    add_serial_part(
        serial_id,
        part,
        file_id,
        file_type,
        safe_caption,
        source_chat_id=msg.chat.id,
        source_message_id=msg.message_id,
    )
    _log_event(
        "serial_part_added",
        message.from_user.id,
        f"serial_id={serial_id} part={part} message_id={message.message_id}",
    )
    if _has_perm(message.from_user.id, "can_broadcast"):
        serial = get_serial_by_id(serial_id)
        if serial:
            kind = "vip" if serial.get("is_vip") else "all"
            prompt = "Yangi qism qo'shildi. "
            if kind == "vip":
                prompt += "VIP obunachilarga xabar yuborilsinmi?"
            else:
                prompt += "Hammaga xabar yuborilsinmi?"
                await message.answer(
                    prompt,
                    reply_markup=_new_part_broadcast_keyboard(kind, serial_id, part),
                )
    next_part = _next_missing_part(serial_id)
    SERIAL_UPLOAD_NEXT_PART[key] = next_part
    save_serial_session(
        message.from_user.id,
        state="await_part",
        serial_id=serial_id,
        next_part=next_part,
        created_at=_now(),
    )
    await message.answer(
        f"{part}-qism qabul qilindi. Davom ettirasizmi?",
        reply_markup=serial_flow_keyboard(),
    )


async def _serial_upload_worker(admin_id: int) -> None:
    queue = SERIAL_UPLOAD_QUEUES[admin_id]
    while True:
        _, _, serial_id, message = await queue.get()
        try:
            await _process_serial_part_message(message, serial_id)
        except Exception as exc:
            _log_event("serial_upload_error", admin_id, f"error={exc}")
        finally:
            queue.task_done()


@router.message(Command("log"))
async def log_handler(message: Message, command: CommandObject):
    if not _has_perm(message.from_user.id, "can_view_logs"):
        await message.answer("Bu buyruq uchun ruxsat yo'q.")
        return
    if not command.args:
        await message.answer("Foydalanish: /log <user_id|@username>")
        return
    raw = command.args.strip()
    user_id: Optional[int] = None
    if raw.isdigit():
        user_id = int(raw)
    else:
        try:
            chat = await message.bot.get_chat(raw)
            user_id = chat.id
        except Exception:
            await message.answer("Foydalanuvchi topilmadi.")
            return
    lines = _tail_log_for_user(user_id, LOG_TAIL_LINES)
    if not lines:
        await message.answer("Ushbu foydalanuvchi uchun log topilmadi.")
        return
    text = "\n".join(lines)
    if len(text) > 3900:
        text = text[-3900:]
    await message.answer(text)
    _log_event("log_view", message.from_user.id, f"target_id={user_id}")


@router.message(Command("logfile"))
async def logfile_handler(message: Message):
    if not _has_perm(message.from_user.id, "can_view_logs"):
        await message.answer("Bu buyruq uchun ruxsat yo'q.")
        return
    await _send_log_file(message)
    _log_event("logfile_sent", message.from_user.id)


@router.message(Command("backup"))
async def backup_handler(message: Message):
    if not _has_perm(message.from_user.id, "can_backup"):
        await message.answer("Bu buyruq uchun ruxsat yo'q.")
        return
    await message.answer("Backup tayyorlanmoqda...")
    await _send_backup(message)
    _log_event("backup_sent", message.from_user.id)


@router.message(Command("setuserbotsession"))
async def set_userbot_session_handler(message: Message, command: CommandObject):
    if message.from_user.id != OWNER_ID:
        await message.answer("Bu buyruq faqat owner uchun.")
        return
    value = (command.args or "").strip()
    if not value:
        await message.answer("Foydalanish: /setuserbotsession <session_string>")
        return
    set_userbot_session(value)
    await reset_userbot_client()
    await message.answer("Userbot session yangilandi.")


@router.message(Command("clearuserbotsession"))
async def clear_userbot_session_handler(message: Message):
    if message.from_user.id != OWNER_ID:
        await message.answer("Bu buyruq faqat owner uchun.")
        return
    set_userbot_session("")
    await reset_userbot_client()
    await message.answer("Userbot session tozalandi.")


@router.message(Command("setuserbotapiid"))
async def set_userbot_api_id_handler(message: Message, command: CommandObject):
    if message.from_user.id != OWNER_ID:
        await message.answer("Bu buyruq faqat owner uchun.")
        return
    value = (command.args or "").strip()
    if not value or not value.isdigit():
        await message.answer("Foydalanish: /setuserbotapiid <raqam>")
        return
    set_userbot_api_id(value)
    await reset_userbot_client()
    await message.answer("USERBOT_API_ID yangilandi.")


@router.message(Command("setuserbotapihash"))
async def set_userbot_api_hash_handler(message: Message, command: CommandObject):
    if message.from_user.id != OWNER_ID:
        await message.answer("Bu buyruq faqat owner uchun.")
        return
    value = (command.args or "").strip()
    if not value:
        await message.answer("Foydalanish: /setuserbotapihash <hash>")
        return
    set_userbot_api_hash(value)
    await reset_userbot_client()
    await message.answer("USERBOT_API_HASH yangilandi.")


@router.message(Command("clearuserbotapi"))
async def clear_userbot_api_handler(message: Message):
    if message.from_user.id != OWNER_ID:
        await message.answer("Bu buyruq faqat owner uchun.")
        return
    set_userbot_api_id("")
    set_userbot_api_hash("")
    await reset_userbot_client()
    await message.answer("USERBOT_API_ID va USERBOT_API_HASH tozalandi.")


@router.chat_join_request()
async def join_request_handler(join_request: ChatJoinRequest):
    add_join_request(
        join_request.chat.id,
        join_request.from_user.id,
        _now(),
    )


async def _broadcast_to_users(message: Message, text: Optional[str]) -> tuple[int, int]:
    ok = 0
    failed = 0
    counter = 0
    for user in get_users():
        user_id = user.get("user_id") if isinstance(user, dict) else user
        if not user_id:
            failed += 1
            continue
        try:
            if message.reply_to_message:
                await message.reply_to_message.copy_to(chat_id=user_id)
            else:
                await message.bot.send_message(chat_id=user_id, text=text or "")
            ok += 1
        except TelegramAPIError as exc:
            _log_event("broadcast_failed", message.from_user.id, f"user_id={user_id} error={exc}")
            failed += 1
        except Exception:
            _log_event("broadcast_failed", message.from_user.id, f"user_id={user_id} error=unknown")
            failed += 1
        counter += 1
        if BROADCAST_BATCH_EVERY and BROADCAST_BATCH_SLEEP and counter % BROADCAST_BATCH_EVERY == 0:
            await asyncio.sleep(BROADCAST_BATCH_SLEEP)
    return ok, failed


async def _broadcast_to_user_ids(
    message: Message,
    user_ids: list[int],
    text: Optional[str],
    from_chat_id: Optional[int] = None,
    reply_message_id: Optional[int] = None,
    media: Optional[dict[str, object]] = None,
    attach_link: Optional[str] = None,
    attach_text: str = "Dramani ko'rish",
    progress: Optional[dict[str, object]] = None,
) -> tuple[int, int]:
    ok = 0
    failed = 0
    counter = 0
    total = len(user_ids)
    last_update = time.monotonic()
    progress_every = 20
    progress_interval = 2.0

    async def _update_progress(force: bool = False) -> None:
        nonlocal last_update
        if not progress:
            return
        now = time.monotonic()
        if not force and counter % progress_every != 0 and now - last_update < progress_interval:
            return
        try:
            await progress["bot"].edit_message_text(
                chat_id=progress["chat_id"],
                message_id=progress["message_id"],
                text=(
                    f"Yuborilmoqda... {counter}/{total}\n"
                    f"Yuborildi: {ok}, xatolik: {failed}"
                ),
            )
            last_update = now
        except Exception:
            last_update = now
    for user_id in user_ids:
        if is_blocked_user(int(user_id)):
            continue
        try:
            if media:
                reply_markup = post_link_keyboard(attach_link) if attach_link else None
                caption = (media.get("caption") or "").strip() or None
                caption_entities = media.get("caption_entities") or None
                if media.get("type") == "photo":
                    await message.bot.send_photo(
                        chat_id=user_id,
                        photo=str(media.get("file_id")),
                        caption=caption,
                        caption_entities=caption_entities,
                        protect_content=True,
                        reply_markup=reply_markup,
                    )
                elif media.get("type") == "video":
                    await message.bot.send_video(
                        chat_id=user_id,
                        video=str(media.get("file_id")),
                        caption=caption,
                        caption_entities=caption_entities,
                        protect_content=True,
                        reply_markup=reply_markup,
                    )
                else:
                    await message.bot.send_document(
                        chat_id=user_id,
                        document=str(media.get("file_id")),
                        caption=caption,
                        caption_entities=caption_entities,
                        protect_content=True,
                        reply_markup=reply_markup,
                    )
            elif reply_message_id and from_chat_id:
                await message.bot.copy_message(
                    chat_id=user_id,
                    from_chat_id=from_chat_id,
                    message_id=reply_message_id,
                    protect_content=True,
                )
                if attach_link:
                    await message.bot.send_message(
                        chat_id=user_id,
                        text=attach_text,
                        protect_content=True,
                        reply_markup=post_link_keyboard(attach_link),
                    )
            else:
                await message.bot.send_message(
                    chat_id=user_id,
                    text=text or "",
                    protect_content=True,
                    reply_markup=post_link_keyboard(attach_link) if attach_link else None,
                )
            ok += 1
        except TelegramAPIError as exc:
            _log_event("broadcast_failed", message.from_user.id, f"user_id={user_id} error={exc}")
            failed += 1
        except Exception:
            _log_event("broadcast_failed", message.from_user.id, f"user_id={user_id} error=unknown")
            failed += 1
        counter += 1
        await _update_progress()
        if BROADCAST_BATCH_EVERY and BROADCAST_BATCH_SLEEP and counter % BROADCAST_BATCH_EVERY == 0:
            await asyncio.sleep(BROADCAST_BATCH_SLEEP)
    await _update_progress(force=True)
    return ok, failed


async def _broadcast_serial_notification(
    message: Message,
    user_ids: list[int],
    serial_id: int,
    text: str,
) -> tuple[int, int]:
    prefs = get_serial_notification_map(serial_id)
    serial = get_serial_by_id(serial_id)
    link = None
    if serial:
        link = await _get_start_link(message.bot, int(serial["code"]))
    ok = 0
    failed = 0
    counter = 0
    for user_id in user_ids:
        pref = prefs.get(user_id, {})
        if pref.get("muted"):
            continue
        first_time = not pref.get("notified")
        send_text = text
        reply_markup = post_link_keyboard(link) if link else None
        try:
            await message.bot.send_message(
                chat_id=user_id,
                text=send_text,
                reply_markup=reply_markup,
            )
            ok += 1
            if first_time:
                mark_serial_notification_sent(user_id, serial_id)
        except TelegramAPIError as exc:
            _log_event("broadcast_failed", message.from_user.id, f"user_id={user_id} error={exc}")
            failed += 1
        except Exception:
            _log_event("broadcast_failed", message.from_user.id, f"user_id={user_id} error=unknown")
            failed += 1
        counter += 1
        if BROADCAST_BATCH_EVERY and BROADCAST_BATCH_SLEEP and counter % BROADCAST_BATCH_EVERY == 0:
            await asyncio.sleep(BROADCAST_BATCH_SLEEP)
    return ok, failed


def _collect_broadcast_targets(kind: str) -> list[int]:
    blocked_ids = {int(uid) for uid in get_blocked_users()}
    if kind == "admins":
        return list({int(admin_id) for admin_id in get_admins()} - blocked_ids)
    users = [user.get("user_id") for user in get_users() if user.get("user_id")]
    users_set = {int(uid) for uid in users} - blocked_ids
    if kind == "all":
        return list(users_set)
    vip_ids = {
        int(item["user_id"])
        for item in get_vip_users()
        if item.get("user_id") and _is_vip_user(int(item["user_id"]))
    }
    vip_ids -= blocked_ids
    if kind == "vip":
        return list(vip_ids)
    if kind == "regular":
        admin_ids = {int(admin_id) for admin_id in get_admins()}
        return list(users_set - vip_ids - admin_ids - blocked_ids)
    return list(users_set)


@router.message(Command("broadcast"))
async def broadcast_handler(message: Message, command: CommandObject):
    if not _has_perm(message.from_user.id, "can_broadcast"):
        await message.answer("Bu buyruq uchun ruxsat yo'q.")
        return
    BROADCAST_TEXT_SESSIONS.discard(message.from_user.id)
    if not command.args and not message.reply_to_message:
        await message.answer("Foydalanish: /broadcast <text> yoki reply bilan yuboring.")
        return
    if message.reply_to_message:
        media = _extract_media_payload(message.reply_to_message)
        BROADCAST_SESSIONS[message.from_user.id] = {
            "mode": "media" if media else "reply",
            "media": media,
            "from_chat_id": message.chat.id,
            "reply_message_id": message.reply_to_message.message_id,
            "state": "await_attach",
        }
    else:
        text = command.args.strip()
        BROADCAST_SESSIONS[message.from_user.id] = {
            "mode": "text",
            "text": text,
            "state": "await_attach",
        }
    await message.answer("Dramani biriktirasizmi?", reply_markup=_broadcast_attach_keyboard())


@router.message(Command("send"))
async def send_to_user_handler(message: Message, command: CommandObject):
    if not _has_perm(message.from_user.id, "can_message_users"):
        await message.answer("Bu buyruq uchun ruxsat yo'q.")
        return
    raw = (command.args or "").strip()
    if not raw:
        await message.answer("Foydalanish: /send <user_id> <text> yoki reply bilan: /send <user_id>")
        return
    parts = raw.split(maxsplit=1)
    try:
        target_id = int(parts[0])
    except ValueError:
        await message.answer("user_id raqam bo'lishi kerak.")
        return
    if is_blocked_user(target_id):
        await message.answer("Foydalanuvchi bloklangan.")
        return
    if message.reply_to_message:
        try:
            await message.reply_to_message.copy_to(target_id)
            await message.answer("Yuborildi.")
            _log_event("send_user_reply", message.from_user.id, f"target_id={target_id}")
        except Exception:
            await message.answer("Yuborib bo'lmadi.")
        return
    text = parts[1].strip() if len(parts) > 1 else ""
    if not text:
        await message.answer("Matn kiriting yoki reply bilan yuboring.")
        return
    try:
        await message.bot.send_message(target_id, text)
        await message.answer("Yuborildi.")
        _log_event("send_user_text", message.from_user.id, f"target_id={target_id}")
    except Exception:
        await message.answer("Yuborib bo'lmadi.")


@router.message(Command("cancel"))
async def cancel_handler(message: Message):
    user_id = message.from_user.id
    cleared = False

    if is_admin(user_id):
        if ADMIN_USER_MESSAGE_SESSIONS.pop(user_id, None) is not None:
            cleared = True
        if ADMIN_ADD_SESSIONS.pop(user_id, None) is not None:
            cleared = True
        if IMPORT_SESSIONS.pop(user_id, None) is not None:
            cleared = True
        if IMPORT_TASKS.pop(user_id, None) is not None:
            cleared = True
        if POST_SESSIONS.pop(user_id, None) is not None:
            cleared = True

    if SERIAL_RENAME_SESSIONS.pop(user_id, None) is not None:
        cleared = True

    if user_id in BROADCAST_TEXT_SESSIONS:
        BROADCAST_TEXT_SESSIONS.discard(user_id)
        cleared = True
    if BROADCAST_SESSIONS.pop(user_id, None) is not None:
        cleared = True

    if user_id in VIP_PRICE_SESSIONS:
        VIP_PRICE_SESSIONS.discard(user_id)
        cleared = True
    if user_id in VIP_MESSAGE_SESSIONS:
        VIP_MESSAGE_SESSIONS.discard(user_id)
        cleared = True
    if user_id in VIP_CARD_SESSIONS:
        VIP_CARD_SESSIONS.discard(user_id)
        cleared = True
    if user_id in VIP_PAYMENT_SESSIONS:
        VIP_PAYMENT_SESSIONS.discard(user_id)
        cleared = True
    if VIP_REJECT_SESSIONS.pop(user_id, None) is not None:
        cleared = True

    if user_id in CONTACT_ADMIN_SESSIONS:
        CONTACT_ADMIN_SESSIONS.discard(user_id)
        cleared = True

    if user_id in USER_SEARCH_SESSIONS:
        USER_SEARCH_SESSIONS.discard(user_id)
        cleared = True
    if USER_SEARCH_RESULTS.pop(user_id, None) is not None:
        cleared = True
    if USER_SERIALS_LIST.pop(user_id, None) is not None:
        cleared = True

    if cleared:
        await message.answer("Bekor qilindi.")
        return
    await message.answer("Bekor qilindi.")


@router.message(
    lambda message: (
        message
        and message.from_user
        and message.from_user.id in BROADCAST_TEXT_SESSIONS
    )
)
async def broadcast_text_handler(message: Message):
    if not _has_perm(message.from_user.id, "can_broadcast"):
        BROADCAST_TEXT_SESSIONS.discard(message.from_user.id)
        return
    if message.reply_to_message:
        BROADCAST_TEXT_SESSIONS.discard(message.from_user.id)
        media = _extract_media_payload(message.reply_to_message)
        BROADCAST_SESSIONS[message.from_user.id] = {
            "mode": "media" if media else "reply",
            "media": media,
            "from_chat_id": message.chat.id,
            "reply_message_id": message.reply_to_message.message_id,
            "state": "await_attach",
        }
        await message.answer("Dramani biriktirasizmi?", reply_markup=_broadcast_attach_keyboard())
        return
    text = (message.text or "").strip()
    if not text:
        await message.answer("E'lon matnini yuboring.")
        return
    BROADCAST_TEXT_SESSIONS.discard(message.from_user.id)
    BROADCAST_SESSIONS[message.from_user.id] = {
        "mode": "text",
        "text": text,
        "state": "await_attach",
    }
    await message.answer("Dramani biriktirasizmi?", reply_markup=_broadcast_attach_keyboard())




@router.callback_query(F.data.startswith("broadcastattach:"))
async def broadcast_attach_callback(callback: CallbackQuery):
    if not _has_perm(callback.from_user.id, "can_broadcast"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    session = BROADCAST_SESSIONS.get(callback.from_user.id)
    if not session:
        await callback.answer("Sessiya topilmadi.", show_alert=True)
        return
    action = callback.data.split(":")[-1]
    if action == "yes":
        session["attach_serial"] = True
        session["state"] = "await_serial_code"
        await callback.message.edit_text("Drama kodini yuboring.")
        return
    if action == "no":
        session["attach_serial"] = False
        session["state"] = "ready"
        await callback.message.edit_text(
            "Kimlarga yuborilsin?",
            reply_markup=broadcast_target_keyboard(),
        )
        return
    await callback.answer("Xatolik.", show_alert=True)


@router.callback_query(F.data.startswith("broadcast:"))
async def broadcast_target_callback(callback: CallbackQuery):
    if not _has_perm(callback.from_user.id, "can_broadcast"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    action = callback.data.split(":")[-1]
    if action == "cancel":
        BROADCAST_SESSIONS.pop(callback.from_user.id, None)
        await callback.message.edit_text("Bekor qilindi.", reply_markup=admin_back_keyboard())
        return
    session = BROADCAST_SESSIONS.get(callback.from_user.id)
    if not session:
        await callback.answer("Sessiya topilmadi.", show_alert=True)
        return
    attach_link = None
    if session.get("attach_serial"):
        serial_code = session.get("serial_code")
        if serial_code:
            attach_link = await _get_start_link(callback.bot, int(serial_code))
    targets = _collect_broadcast_targets(action)
    if not targets:
        await callback.message.edit_text("Foydalanuvchilar topilmadi.", reply_markup=admin_back_keyboard())
        BROADCAST_SESSIONS.pop(callback.from_user.id, None)
        return
    if session.get("mode") == "reply":
        await callback.message.edit_text(
            f"Yuborish boshlandi... 0/{len(targets)}\nYuborildi: 0, xatolik: 0"
        )
        ok, failed = await _broadcast_to_user_ids(
            callback.message,
            targets,
            text=None,
            from_chat_id=session.get("from_chat_id"),
            reply_message_id=session.get("reply_message_id"),
            attach_link=attach_link,
            progress={
                "bot": callback.bot,
                "chat_id": callback.message.chat.id,
                "message_id": callback.message.message_id,
            },
        )
    elif session.get("mode") == "media":
        await callback.message.edit_text(
            f"Yuborish boshlandi... 0/{len(targets)}\nYuborildi: 0, xatolik: 0"
        )
        ok, failed = await _broadcast_to_user_ids(
            callback.message,
            targets,
            text=None,
            media=session.get("media"),
            attach_link=attach_link,
            progress={
                "bot": callback.bot,
                "chat_id": callback.message.chat.id,
                "message_id": callback.message.message_id,
            },
        )
    else:
        await callback.message.edit_text(
            f"Yuborish boshlandi... 0/{len(targets)}\nYuborildi: 0, xatolik: 0"
        )
        ok, failed = await _broadcast_to_user_ids(
            callback.message,
            targets,
            text=session.get("text"),
            attach_link=attach_link,
            progress={
                "bot": callback.bot,
                "chat_id": callback.message.chat.id,
                "message_id": callback.message.message_id,
            },
        )
    BROADCAST_SESSIONS.pop(callback.from_user.id, None)
    await callback.message.edit_text(f"Yuborildi: {ok}, xatolik: {failed}")
    _log_event(
        "broadcast",
        callback.from_user.id,
        f"target={action} ok={ok} failed={failed}",
    )


@router.callback_query(F.data.startswith("newdrama:"))
async def new_drama_broadcast_callback(callback: CallbackQuery):
    if not _has_perm(callback.from_user.id, "can_broadcast"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Xatolik.", show_alert=True)
        return
    action = parts[1]
    try:
        serial_id = int(parts[2])
    except ValueError:
        await callback.answer("Xatolik.", show_alert=True)
        return
    if action == "skip":
        await callback.message.edit_text("Yuborilmadi.")
        return
    serial = get_serial_by_id(serial_id)
    if not serial:
        await callback.message.edit_text("Drama topilmadi.")
        return
    target = "vip" if action == "vip" else "all"
    targets = _collect_broadcast_targets(target)
    if not targets:
        await callback.message.edit_text("Foydalanuvchilar topilmadi.")
        return
    text = _build_new_drama_text(serial["title"], int(serial["code"]))
    ok, failed = await _broadcast_serial_notification(
        callback.message,
        targets,
        serial_id,
        text,
    )
    await callback.message.edit_text(f"Yuborildi: {ok}, xatolik: {failed}")
    _log_event(
        "broadcast_new_drama",
        callback.from_user.id,
        f"serial_id={serial_id} target={target} ok={ok} failed={failed}",
    )


@router.callback_query(F.data.startswith("newpart:"))
async def new_part_broadcast_callback(callback: CallbackQuery):
    if not _has_perm(callback.from_user.id, "can_broadcast"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("Xatolik.", show_alert=True)
        return
    action = parts[1]
    try:
        serial_id = int(parts[2])
        part = int(parts[3])
    except ValueError:
        await callback.answer("Xatolik.", show_alert=True)
        return
    if action == "skip":
        await callback.message.edit_text("Yuborilmadi.")
        return
    serial = get_serial_by_id(serial_id)
    if not serial:
        await callback.message.edit_text("Drama topilmadi.")
        return
    target = "vip" if action == "vip" else "all"
    targets = _collect_broadcast_targets(target)
    if not targets:
        await callback.message.edit_text("Foydalanuvchilar topilmadi.")
        return
    text = _build_new_part_text(serial["title"], int(serial["code"]), part)
    ok, failed = await _broadcast_serial_notification(
        callback.message,
        targets,
        serial_id,
        text,
    )
    await callback.message.edit_text(f"Yuborildi: {ok}, xatolik: {failed}")
    _log_event(
        "broadcast_new_part",
        callback.from_user.id,
        f"serial_id={serial_id} part={part} target={target} ok={ok} failed={failed}",
    )


@router.message(Command("reconow"))
async def recommendation_now_handler(message: Message):
    if not _has_perm(message.from_user.id, "can_broadcast"):
        await message.answer("Bu buyruq uchun ruxsat yo'q.")
        return
    tz = ZoneInfo(BACKUP_TZ)
    today = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc).astimezone(tz).date().isoformat()
    total_users = count_users()
    if total_users == 0:
        await message.answer("Foydalanuvchilar topilmadi.")
        return
    status = await message.answer(
        f"Tavsiya yuborish boshlandi... 0/{total_users}\n"
        "Yuborildi: 0, xatolik: 0, o'tkazildi: 0"
    )
    ok = 0
    failed = 0
    skipped = 0
    counter = 0
    last_update = time.monotonic()
    total = total_users
    for batch in iter_user_ids():
        rec_map = get_user_daily_recommendations_for_users(today, batch)
        for user_id in batch:
            counter += 1
            if is_blocked_user(int(user_id)):
                skipped += 1
            else:
                serial_id = rec_map.get(int(user_id))
                if not serial_id:
                    skipped += 1
                else:
                    try:
                        if await _send_serial_part_to_user(
                            message.bot, int(user_id), int(serial_id)
                        ):
                            ok += 1
                        else:
                            failed += 1
                    except TelegramAPIError as exc:
                        _log_event("recommend_failed", None, f"user_id={user_id} error={exc}")
                        failed += 1
                    except Exception:
                        _log_event("recommend_failed", None, f"user_id={user_id} error=unknown")
                        failed += 1
            now = time.monotonic()
            if counter % 20 == 0 or now - last_update >= 2.0:
                try:
                    await status.edit_text(
                        f"Tavsiya yuborilmoqda... {counter}/{total}\n"
                        f"Yuborildi: {ok}, xatolik: {failed}, o'tkazildi: {skipped}"
                    )
                    last_update = now
                except Exception:
                    last_update = now
            if BROADCAST_BATCH_EVERY and BROADCAST_BATCH_SLEEP and counter % BROADCAST_BATCH_EVERY == 0:
                await asyncio.sleep(BROADCAST_BATCH_SLEEP)
    try:
        await status.edit_text(
            f"Tugadi. Yuborildi: {ok}, xatolik: {failed}, o'tkazildi: {skipped}"
        )
    except Exception:
        await message.answer(
            f"Tugadi. Yuborildi: {ok}, xatolik: {failed}, o'tkazildi: {skipped}"
        )
    _log_event(
        "recommend_now",
        message.from_user.id,
        f"ok={ok} failed={failed} skipped={skipped}",
    )


@router.callback_query(F.data.startswith("serialnotify:"))
async def serial_notify_callback(callback: CallbackQuery):
    parts = callback.data.split(":")
    if len(parts) < 3:
        await callback.answer("Xatolik.", show_alert=True)
        return
    action = parts[1]
    try:
        serial_id = int(parts[2])
    except ValueError:
        await callback.answer("Xatolik.", show_alert=True)
        return
    if action == "info":
        await callback.answer(
            "Bildirishnomalar yoniq bo'lganda bu dramaga oid yangi qismlar, "
            "yangiliklar va so'nggi yangiliklardan xabardor bolasiz.",
            show_alert=True,
        )
        return
    if action == "off":
        set_serial_notification_muted(callback.from_user.id, serial_id, 1)
        await callback.answer("Bildirishnomalar o'chirildi.")
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        return
    if action not in {"toggle", "togglep"}:
        await callback.answer("Xatolik.", show_alert=True)
        return
    page = 0
    current_part = None
    if action == "toggle":
        if len(parts) >= 4 and parts[3].isdigit():
            page = int(parts[3])
    else:
        if len(parts) >= 4 and parts[3].isdigit():
            current_part = int(parts[3])
    current = _is_serial_notify_enabled(callback.from_user.id, serial_id)
    set_serial_notification_muted(callback.from_user.id, serial_id, 0 if not current else 1)
    serial = get_serial_by_id(serial_id)
    title = serial.get("title") if serial else "Drama"
    status_text = "yondi" if not current else "o'chdi"
    await callback.answer(f"{title} uchun bildirishnomalar {status_text}.")
    if not serial:
        return
    part_numbers, vip_parts = _serial_part_numbers_for_keyboard(serial_id)
    if not part_numbers:
        return
    likes_count, dislikes_count = get_serial_rating_counts(serial_id)
    if current_part is not None:
        reply_markup = serial_nav_keyboard(
            serial_id,
            part_numbers,
            current_part=current_part,
            part_link_prefix=None,
            show_rating=True,
            notify_enabled=_is_serial_notify_enabled(callback.from_user.id, serial_id),
            rating=get_serial_rating(callback.from_user.id, serial_id),
            likes_count=likes_count,
            dislikes_count=dislikes_count,
        )
    else:
        share_link = await _get_share_link(
            callback.message.bot,
            int(serial.get("code")),
            serial.get("title") or "",
            len(part_numbers),
        )
        reply_markup = serial_parts_keyboard(
            serial_id,
            part_numbers,
            page=page,
            per_page=SERIAL_PARTS_PER_PAGE,
            vip_parts=vip_parts,
            share_link=share_link,
            notify_enabled=_is_serial_notify_enabled(callback.from_user.id, serial_id),
            rating=get_serial_rating(callback.from_user.id, serial_id),
            likes_count=likes_count,
            dislikes_count=dislikes_count,
        )
    await _safe_edit_reply_markup(
        callback.message.bot,
        callback.message.chat.id,
        callback.message.message_id,
        reply_markup,
    )
