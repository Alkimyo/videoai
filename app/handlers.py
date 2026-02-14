import asyncio
import datetime as dt
import os
import re
import shutil
import tempfile
import urllib.parse
import zipfile
from collections import deque
from typing import Optional

from aiogram import F, Router
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, ChatJoinRequest, FSInputFile, Message, ReplyKeyboardRemove
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import DB_PATH, LOG_PATH, OWNER_ID, SOURCE_CHANNEL_ID
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
    get_serial_session,
    get_serials,
    search_serials_by_title,
    count_serials_by_title,
    del_serial,
    del_serial_part,
    init_db,
    set_serial_vip,
    add_vip_user,
    remove_vip_user,
    get_vip_users,
    get_vip_user,
    set_setting,
    get_setting,
    mark_vip_reminder,
    is_admin,
    serial_part_exists,
    save_serial_session,
    clear_serial_session,
    get_users,
    has_admin_permission,
    has_join_request,
    set_admin_permissions,
    record_serial_view,
    get_serial_day_stats,
    get_serial_recent_days,
)
from app.keyboards import (
    admin_back_keyboard,
    admin_panel_keyboard,
    admin_permissions_keyboard,
    admin_edit_list_keyboard,
    log_cancel_keyboard,
    post_link_keyboard,
    post_media_keyboard,
    serial_cancel_keyboard,
    serial_flow_keyboard,
    serial_parts_keyboard,
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
)

SERIAL_PARTS_PER_PAGE = 20
SERIALS_PER_PAGE = 20
USERS_PER_PAGE = 20
ADMINS_PER_PAGE = 20
USER_SERIALS_PER_PAGE = 20
LOG_QUERY_ADMINS: set[int] = set()
ADMIN_ADD_SESSIONS: dict[int, dict[str, object]] = {}
RESTORE_DB_SESSIONS: dict[int, dict[str, object]] = {}
POST_SESSIONS: dict[int, dict[str, object]] = {}
USER_SEARCH_SESSIONS: set[int] = set()
USER_SEARCH_RESULTS: dict[int, list[dict]] = {}
USER_SERIALS_LIST: dict[int, dict[str, object]] = {}
VIP_ADD_SESSIONS: dict[int, int] = {}
VIP_PRICE_KEY = "vip_monthly_price"
VIP_PRICE_SESSIONS: set[int] = set()
VIP_LISTS_PER_PAGE = 20
VIP_MESSAGE_KEY = "vip_message"
VIP_MESSAGE_SESSIONS: set[int] = set()
VIP_CARD_NUMBER_KEY = "vip_card_number"
VIP_CARD_OWNER_KEY = "vip_card_owner"
VIP_CARD_SESSIONS: set[int] = set()
VIP_PAYMENT_SESSIONS: set[int] = set()
VIP_REJECT_SESSIONS: dict[int, int] = {}
CONTACT_ADMIN_SESSIONS: set[int] = set()
BROADCAST_SESSIONS: dict[int, dict[str, object]] = {}
BROADCAST_TEXT_SESSIONS: set[int] = set()
VIP_RECEIPT_APPROVED: dict[int, int] = {}
VIP_RECEIPT_REJECTED: dict[int, int] = {}
VIP_RECEIPT_MESSAGES: dict[int, list[tuple[int, int]]] = {}
SERIAL_UPLOAD_LOCKS: dict[int, asyncio.Lock] = {}
SERIAL_UPLOAD_QUEUES: dict[int, asyncio.PriorityQueue] = {}
SERIAL_UPLOAD_TASKS: dict[int, asyncio.Task] = {}
SERIAL_UPLOAD_COUNTERS: dict[int, int] = {}
SERIAL_UPLOAD_NEXT_PART: dict[tuple[int, int], int] = {}
ADMIN_PERMISSION_LABELS = {
    "can_manage_admins": "Adminlarni boshqarish",
    "can_manage_channels": "Kanallarni boshqarish",
    "can_manage_vip": "VIP boshqarish",
    "can_add_serial": "Drama qo'shish",
    "can_add_part": "Qism qo'shish",
    "can_broadcast": "E'lon yuborish",
    "can_view_lists": "Ro'yxatlarni ko'rish",
    "can_view_logs": "Loglarni ko'rish",
    "can_view_stats": "Statistikani ko'rish",
    "can_backup": "Backup olish",
}

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


def _format_perm_inline(perms: dict[str, int]) -> str:
    parts = []
    for key in ADMIN_PERMISSION_KEYS:
        icon = "✅" if perms.get(key) else "❌"
        label = ADMIN_PERMISSION_LABELS.get(key, key)
        parts.append(f"{label}:{icon}")
    return ", ".join(parts)


def _get_vip_price() -> Optional[int]:
    raw = get_setting(VIP_PRICE_KEY)
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _get_vip_message() -> Optional[str]:
    return get_setting(VIP_MESSAGE_KEY)


def _get_vip_card_details() -> tuple[str, str]:
    number = get_setting(VIP_CARD_NUMBER_KEY) or ""
    owner = get_setting(VIP_CARD_OWNER_KEY) or ""
    return number, owner


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


def _vip_receipt_keyboard(user_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="Tasdiqlash", callback_data=f"vipreceipt:approve:{user_id}")
    kb.button(text="Rad etish", callback_data=f"vipreceipt:reject:{user_id}")
    kb.adjust(2)
    return kb.as_markup()


async def _update_receipt_status(bot, user_id: int, text: str) -> None:
    entries = VIP_RECEIPT_MESSAGES.pop(user_id, [])
    for admin_id, message_id in entries:
        try:
            await bot.edit_message_text(
                text=text,
                chat_id=admin_id,
                message_id=message_id,
            )
        except Exception:
            continue


def _is_vip_user(user_id: int) -> bool:
    info = get_vip_user(user_id)
    if not info:
        return False
    try:
        expires_at = dt.datetime.fromisoformat(info["expires_at"])
    except Exception:
        return False
    return expires_at > dt.datetime.utcnow()


def _filter_serials_for_user(user_id: int, serials: list[dict]) -> list[dict]:
    if is_admin(user_id) or _is_vip_user(user_id):
        return serials
    return [item for item in serials if not item.get("is_vip")]


def _include_vip_serials(user_id: int) -> bool:
    return is_admin(user_id) or _is_vip_user(user_id)


async def _send_vip_info(message: Message, user_id: int) -> None:
    info = get_vip_user(user_id)
    price = _get_vip_price()
    if not info:
        text = "Sizda VIP yo'q."
        if price:
            text += f" Oylik narx: {price} so'm."
        await message.answer(text, reply_markup=vip_info_keyboard())
        return
    try:
        expires_at = dt.datetime.fromisoformat(info["expires_at"])
    except Exception:
        await message.answer("VIP holatini aniqlab bo'lmadi.")
        return
    days_left = max(0, (expires_at.date() - dt.datetime.utcnow().date()).days)
    text = f"VIP aktiv. Tugash sanasi: {expires_at.date()} ({days_left} kun qoldi)."
    await message.answer(text, reply_markup=vip_info_keyboard())


def _normalize_search_text(text: str) -> str:
    value = text.lower().strip()
    value = value.replace("o'", "o").replace("g'", "g")
    value = value.replace("o‘", "o").replace("g‘", "g")
    value = value.replace("o’", "o").replace("g’", "g")
    value = value.replace("x", "h")
    value = re.sub(r"[^a-z0-9]+", "", value)
    return value


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
    custom = _get_vip_message()
    if custom:
        await message.answer(custom)
        return False
    price = _get_vip_price()
    if price:
        await message.answer(
            f"Bu drama VIP. Oylik narx: {price} so'm. Admin bilan bog'laning."
        )
    else:
        await message.answer("Bu drama VIP. Admin bilan bog'laning.")
    return False


async def _ensure_serial_access(
    message: Message,
    serial: dict,
    user_id: Optional[int] = None,
) -> bool:
    if serial.get("is_vip"):
        return await _ensure_vip_access(message, serial, user_id=user_id)
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
LOG_TAIL_LINES = 40
LOG_MAX_BYTES = 10 * 1024 * 1024
LOG_BACKUP_COUNT = 3


async def _check_subscriptions(bot, user_id: int, channels: list) -> bool:
    for channel in channels:
        chat_id = int(channel["chat_id"])
        try:
            member = await bot.get_chat_member(chat_id, user_id)
        except Exception:
            if has_join_request(chat_id, user_id):
                continue
            return False
        if member.status in {ChatMemberStatus.LEFT, ChatMemberStatus.KICKED}:
            if has_join_request(chat_id, user_id):
                continue
            return False
    return True


async def ensure_subscribed(message: Message, user_id: Optional[int] = None) -> bool:
    if user_id is None:
        user_id = message.from_user.id
    if _is_admin_user(user_id):
        return True
    if _is_vip_user(user_id):
        return True
    channels = get_channels()
    if not channels:
        return True
    ok = await _check_subscriptions(message.bot, user_id, channels)
    if not ok:
        await message.answer(
            "Iltimos, quyidagi kanallarga obuna bo'ling.",
            reply_markup=subscribe_keyboard(channels),
        )
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
    ok = await _check_subscriptions(callback.bot, callback.from_user.id, channels)
    if not ok:
        await callback.message.answer(
            "Iltimos, quyidagi kanallarga obuna bo'ling.",
            reply_markup=subscribe_keyboard(channels),
        )
        return False
    return True


@router.callback_query(F.data == "check_subs")
async def check_subs_callback(callback: CallbackQuery):
    channels = get_channels()
    ok = await _check_subscriptions(callback.bot, callback.from_user.id, channels)
    if ok:
        await callback.message.edit_text("Obuna tasdiqlandi. Drama kodini yuboring.")
    else:
        await callback.answer("Hali obuna emassiz.", show_alert=True)


@router.callback_query(F.data == "user:sendcode")
async def user_send_code_callback(callback: CallbackQuery):
    if is_admin(callback.from_user.id) and get_serial_session(callback.from_user.id):
        clear_serial_session(callback.from_user.id)
    await callback.message.edit_text("Drama kodini yuboring.")


@router.callback_query(F.data == "user:vipinfo")
async def user_vipinfo_callback(callback: CallbackQuery):
    await _send_vip_info(callback.message, callback.from_user.id)


@router.callback_query(F.data == "user:contact")
async def user_contact_callback(callback: CallbackQuery):
    if not await ensure_subscribed_callback(callback):
        return
    CONTACT_ADMIN_SESSIONS.add(callback.from_user.id)
    await callback.message.answer(
        "Adminlarga yuboriladigan xabarni yozing. Bekor qilish: Bekor",
        reply_markup=contact_admin_keyboard(),
    )


@router.callback_query(F.data.startswith("vipjoin:"))
async def vip_join_callback(callback: CallbackQuery):
    parts = callback.data.split(":")
    if len(parts) != 2:
        await callback.answer("Xatolik.", show_alert=True)
        return
    action = parts[1]
    if action == "cancel":
        VIP_PAYMENT_SESSIONS.discard(callback.from_user.id)
        await callback.message.edit_text("Bekor qilindi.")
        return
    if action != "start":
        await callback.answer("Xatolik.", show_alert=True)
        return
    number, owner = _get_vip_card_details()
    if not number or not owner:
        await callback.message.edit_text("Rekvizitlar belgilanmagan. Admin bilan bog'laning.")
        return
    VIP_PAYMENT_SESSIONS.add(callback.from_user.id)
    text = (
        f"To'lov uchun karta: {number}\n"
        f"Karta egasi: {owner}\n\n"
        "To'lov qilgandan so'ng chekni shu yerga yuboring."
    )
    await callback.message.edit_text(text)


@router.callback_query(F.data == "user:serials")
async def user_serials_callback(callback: CallbackQuery):
    if not await ensure_subscribed_callback(callback):
        return
    await _send_user_serials_menu(callback.message, page=0)


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
    if len(parts) != 3:
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
    if len(parts) != 3:
        await callback.answer("Xatolik.", show_alert=True)
        return
    try:
        page = int(parts[2])
    except ValueError:
        await callback.answer("Xatolik.", show_alert=True)
        return
    await _render_user_serials_page(callback, page=page)


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
    ok = await _send_serial_part(callback.message, serial_id, part)
    if not ok:
        await callback.answer("Qism topilmadi.", show_alert=True)
        return
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
    serial_parts = get_serial_parts(serial_id)
    part_numbers = [int(item["part"]) for item in serial_parts if item.get("part") is not None]
    if not part_numbers:
        await callback.answer("Dramada qismlar yo'q.", show_alert=True)
        return
    await _safe_edit_or_answer(
        callback.message,
        f"{serial['title']} qismlari:",
        reply_markup=serial_parts_keyboard(
            serial_id,
            part_numbers,
            page=page,
            per_page=SERIAL_PARTS_PER_PAGE,
        ),
    )


def _today() -> str:
    return dt.datetime.utcnow().date().isoformat()


def _parse_code(raw: str) -> Optional[str]:
    value = raw.strip()
    if not value.isdigit():
        return None
    return str(int(value))


def _parse_part(raw: str) -> Optional[int]:
    value = raw.strip()
    if not value.isdigit():
        return None
    part = int(value)
    return part if part > 0 else None


def _now() -> str:
    return dt.datetime.utcnow().isoformat()


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
) -> bool:
    while True:
        try:
            await message.answer_video(
                file_id,
                caption=caption,
                protect_content=True,
                reply_markup=reply_markup,
                reply_to_message_id=reply_to_message_id,
            )
            return True
        except TelegramRetryAfter as err:
            await _wait_retry(err)
        except TelegramAPIError:
            _log_event(
                "send_video_error",
                message.from_user.id if message.from_user else None,
                f"file_id={file_id}",
            )
            return False


async def _safe_send_document(
    message: Message,
    file_id: str,
    caption: Optional[str],
    reply_markup=None,
    reply_to_message_id: Optional[int] = None,
) -> bool:
    while True:
        try:
            await message.answer_document(
                file_id,
                caption=caption,
                protect_content=True,
                reply_markup=reply_markup,
                reply_to_message_id=reply_to_message_id,
            )
            return True
        except TelegramRetryAfter as err:
            await _wait_retry(err)
        except TelegramAPIError:
            _log_event(
                "send_document_error",
                message.from_user.id if message.from_user else None,
                f"file_id={file_id}",
            )
            return False


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
    add_user(message.from_user.id, message.from_user.username)
    _log_event("user_start", message.from_user.id)
    if not await ensure_subscribed(message):
        return
    if command.args:
        code = _parse_code(command.args)
        if code:
            serial = get_serial_by_code(int(code))
            if serial and await _show_serial_parts(message, serial["id"]):
                return
            await message.answer("Drama topilmadi.")
            return
    banner = (
        "====================\n"
        " D R A M A L A R U Z B E K B O T\n"
        "====================\n"
        "Drama kodini yuboring."
    )
    await message.answer(banner, reply_markup=user_keyboard())


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
        if _has_perm(message.from_user.id, "can_manage_vip"):
            lines.extend(
                [
                    "/addvip <user_id> - VIP qo'shish",
                    "/delvip <user_id> - VIP olib tashlash",
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
        lines.append("/vip - VIP holatini ko'rish")
        text = "\n".join(lines)
    else:
        text = (
            "Buyruqlar:\n"
            "/serial <nom|kod> - dramani yuborish\n"
            "/vip - VIP holatini ko'rish\n"
        )
    await message.answer(text)
    _log_event("admins_list", message.from_user.id)


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


@router.message(Command("addvip"))
async def add_vip_handler(message: Message, command: CommandObject):
    if not _has_perm(message.from_user.id, "can_manage_vip"):
        await message.answer("Bu buyruq uchun ruxsat yo'q.")
        return
    if not command.args:
        await message.answer("Foydalanish: /addvip <user_id>")
        return
    try:
        user_id = int(command.args.strip())
    except ValueError:
        await message.answer("user_id raqam bo'lishi kerak.")
        return
    VIP_ADD_SESSIONS[message.from_user.id] = user_id
    await message.answer(
        "VIP muddatini tanlang:",
        reply_markup=vip_duration_keyboard(user_id),
    )


@router.message(Command("delvip"))
async def del_vip_handler(message: Message, command: CommandObject):
    if not _has_perm(message.from_user.id, "can_manage_vip"):
        await message.answer("Bu buyruq uchun ruxsat yo'q.")
        return
    if not command.args:
        await message.answer("Foydalanish: /delvip <user_id>")
        return
    try:
        user_id = int(command.args.strip())
    except ValueError:
        await message.answer("user_id raqam bo'lishi kerak.")
        return
    remove_vip_user(user_id)
    await message.answer("VIP olib tashlandi.")


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


@router.message(Command("viplist"))
async def vip_list_handler(message: Message):
    if not _has_perm(message.from_user.id, "can_manage_vip"):
        await message.answer("Bu buyruq uchun ruxsat yo'q.")
        return
    await _render_vip_list(message, page=0)


@router.message(Command("setvipprice"))
async def set_vip_price_handler(message: Message, command: CommandObject):
    if not _has_perm(message.from_user.id, "can_manage_vip"):
        await message.answer("Bu buyruq uchun ruxsat yo'q.")
        return
    if not command.args:
        await message.answer("Foydalanish: /setvipprice <sum>")
        return
    raw = command.args.strip().replace(" ", "")
    if not raw.isdigit():
        await message.answer("Narx raqam bo'lishi kerak.")
        return
    set_setting(VIP_PRICE_KEY, raw)
    await message.answer(f"VIP oylik narx: {raw} so'm")


@router.message(Command("vipprice"))
async def vip_price_handler(message: Message):
    if not _has_perm(message.from_user.id, "can_manage_vip"):
        await message.answer("Bu buyruq uchun ruxsat yo'q.")
        return
    price = _get_vip_price()
    text = f"VIP oylik narx: {price} so'm" if price else "VIP oylik narx belgilanmagan."
    await message.answer(text)


@router.message(Command("vipmsg"))
async def vip_message_handler(message: Message):
    if not _has_perm(message.from_user.id, "can_manage_vip"):
        await message.answer("Bu buyruq uchun ruxsat yo'q.")
        return
    current = _get_vip_message()
    text = "VIP xabari belgilanmagan."
    if current:
        text = f"Joriy VIP xabari:\n{current}"
    VIP_MESSAGE_SESSIONS.add(message.from_user.id)
    await message.answer(f"{text}\n\nYangi xabarni yuboring.")


@router.message(Command("vipcard"))
async def vip_card_handler(message: Message):
    if not _has_perm(message.from_user.id, "can_manage_vip"):
        await message.answer("Bu buyruq uchun ruxsat yo'q.")
        return
    number, owner = _get_vip_card_details()
    current = "VIP rekvizit belgilanmagan."
    if number or owner:
        current = f"Joriy rekvizit:\nKarta: {number or '-'}\nEgasi: {owner or '-'}"
    VIP_CARD_SESSIONS.add(message.from_user.id)
    await message.answer(
        f"{current}\n\n"
        "Yangi rekvizit yuboring.\n"
        "Format: 8600 0000 0000 0000 | FIO",
        reply_markup=admin_back_keyboard(),
    )


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
    await callback.message.edit_text(
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


@router.callback_query(F.data == "admin:viplist")
async def admin_viplist_callback(callback: CallbackQuery):
    if not _has_perm(callback.from_user.id, "can_manage_vip"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    await _render_vip_list(callback.message, page=0)


@router.callback_query(F.data.startswith("admin:viplist:"))
async def admin_viplist_page_callback(callback: CallbackQuery):
    if not _has_perm(callback.from_user.id, "can_manage_vip"):
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
    await _render_vip_list(callback.message, page=page)


@router.callback_query(F.data == "admin:vipprice")
async def admin_vipprice_callback(callback: CallbackQuery):
    if not _has_perm(callback.from_user.id, "can_manage_vip"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    price = _get_vip_price()
    text = f"VIP oylik narx: {price} so'm" if price else "VIP oylik narx belgilanmagan."
    await callback.message.edit_text(text, reply_markup=vip_price_keyboard())


@router.callback_query(F.data == "admin:vipmsg")
async def admin_vipmsg_callback(callback: CallbackQuery):
    if not _has_perm(callback.from_user.id, "can_manage_vip"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    current = _get_vip_message()
    text = "VIP xabari belgilanmagan."
    if current:
        text = f"Joriy VIP xabari:\n{current}"
    VIP_MESSAGE_SESSIONS.add(callback.from_user.id)
    await callback.message.edit_text(f"{text}\n\nYangi xabarni yuboring.")


@router.callback_query(F.data == "admin:vipcard")
async def admin_vipcard_callback(callback: CallbackQuery):
    if not _has_perm(callback.from_user.id, "can_manage_vip"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    number, owner = _get_vip_card_details()
    current = "VIP rekvizit belgilanmagan."
    if number or owner:
        current = f"Joriy rekvizit:\nKarta: {number or '-'}\nEgasi: {owner or '-'}"
    VIP_CARD_SESSIONS.add(callback.from_user.id)
    await callback.message.edit_text(
        f"{current}\n\n"
        "Yangi rekvizit yuboring.\n"
        "Format: 8600 0000 0000 0000 | FIO",
        reply_markup=admin_back_keyboard(),
    )

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
    users = get_users()
    if not users:
        await callback.message.edit_text("Foydalanuvchilar yo'q.", reply_markup=admin_back_keyboard())
        return
    total = len(users)
    total_pages = max(1, (total + USERS_PER_PAGE - 1) // USERS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * USERS_PER_PAGE
    end = start + USERS_PER_PAGE
    page_users = users[start:end]
    header = f"Foydalanuvchilar: {total} ta"
    body = "\n".join(
        f"@{user.get('username')}" if user.get("username") else str(user.get("user_id"))
        for user in page_users
    )
    text = f"{header}\n{body}"
    await callback.message.edit_text(
        text,
        reply_markup=users_keyboard(page, total_pages),
    )


async def _render_serials_page(callback: CallbackQuery, page: int) -> None:
    if not _has_perm(callback.from_user.id, "can_view_lists"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    serials = get_serials()
    if not serials:
        await callback.message.edit_text("Dramalar yo'q.", reply_markup=admin_back_keyboard())
        return
    total = len(serials)
    total_pages = max(1, (total + SERIALS_PER_PAGE - 1) // SERIALS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * SERIALS_PER_PAGE
    end = start + SERIALS_PER_PAGE
    page_serials = serials[start:end]
    header = f"Dramalar: {total} ta"
    body = "\n".join(
        f"{item.get('code')} - {'VIP ' if item.get('is_vip') else ''}{item.get('title')}"
        for item in page_serials
    )
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


async def _render_vip_list(message: Message, page: int) -> None:
    users = get_vip_users()
    if not users:
        await message.answer("VIP foydalanuvchilar yo'q.")
        return
    total = len(users)
    total_pages = max(1, (total + VIP_LISTS_PER_PAGE - 1) // VIP_LISTS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * VIP_LISTS_PER_PAGE
    end = start + VIP_LISTS_PER_PAGE
    page_users = users[start:end]
    user_map = {user["user_id"]: user.get("username") for user in get_users()}
    lines = [f"VIP foydalanuvchilar: {total} ta"]
    now = dt.datetime.utcnow()
    for item in page_users:
        try:
            expires_at = dt.datetime.fromisoformat(item["expires_at"])
        except Exception:
            expires_at = None
        remaining = ""
        if expires_at:
            delta = (expires_at - now).days
            remaining = f" ({delta} kun)"
        username = user_map.get(item["user_id"])
        label = f"@{username}" if username else str(item["user_id"])
        expires_text = item["expires_at"].split("T")[0]
        lines.append(f"{label} - {expires_text}{remaining}")
    await message.answer("\n".join(lines), reply_markup=vip_list_keyboard(page, total_pages))


async def _render_user_serials_page(callback: CallbackQuery, page: int) -> None:
    serials = get_serials()
    if not serials:
        await _safe_edit_or_answer(callback.message, "Dramalar yo'q.")
        return
    total = len(serials)
    total_pages = max(1, (total + USER_SERIALS_PER_PAGE - 1) // USER_SERIALS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * USER_SERIALS_PER_PAGE
    end = start + USER_SERIALS_PER_PAGE
    page_serials = serials[start:end]
    text = f"Dramalar: {total} ta"
    await _safe_edit_or_answer(
        callback.message,
        text,
        reply_markup=user_serials_keyboard(page_serials, page, total_pages),
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
        "/post <drama_kod>\n"
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


@router.callback_query(F.data.startswith("vip:"))
async def vip_callback(callback: CallbackQuery):
    if not _has_perm(callback.from_user.id, "can_manage_vip"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    parts = callback.data.split(":")
    if len(parts) < 2:
        await callback.answer("Xatolik.", show_alert=True)
        return
    action = parts[1]
    if action == "cancel":
        VIP_ADD_SESSIONS.pop(callback.from_user.id, None)
        await callback.message.edit_text("Bekor qilindi.", reply_markup=admin_back_keyboard())
        return
    if action != "add" or len(parts) != 4:
        await callback.answer("Xatolik.", show_alert=True)
        return
    try:
        user_id = int(parts[2])
        days = int(parts[3])
    except ValueError:
        await callback.answer("Xatolik.", show_alert=True)
        return
    if VIP_ADD_SESSIONS.get(callback.from_user.id) != user_id:
        await callback.answer("Sessiya topilmadi.", show_alert=True)
        return
    expires_at = (dt.datetime.utcnow() + dt.timedelta(days=days)).isoformat()
    add_vip_user(user_id, expires_at)
    VIP_ADD_SESSIONS.pop(callback.from_user.id, None)
    await callback.message.edit_text(
        f"VIP qo'shildi. Muddati: {days} kun.",
        reply_markup=admin_back_keyboard(),
    )


@router.callback_query(F.data.startswith("vipprice:"))
async def vipprice_callback(callback: CallbackQuery):
    if not _has_perm(callback.from_user.id, "can_manage_vip"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    parts = callback.data.split(":")
    if len(parts) < 2:
        await callback.answer("Xatolik.", show_alert=True)
        return
    action = parts[1]
    if action == "cancel":
        VIP_PRICE_SESSIONS.discard(callback.from_user.id)
        await callback.message.edit_text("Bekor qilindi.", reply_markup=admin_back_keyboard())
        return
    if action == "custom":
        VIP_PRICE_SESSIONS.add(callback.from_user.id)
        await callback.message.edit_text("Yangi narxni yuboring.")
        return
    if action == "set" and len(parts) == 3:
        raw = parts[2]
        if not raw.isdigit():
            await callback.answer("Xatolik.", show_alert=True)
            return
        set_setting(VIP_PRICE_KEY, raw)
        VIP_PRICE_SESSIONS.discard(callback.from_user.id)
        await callback.message.edit_text(
            f"VIP oylik narx: {raw} so'm",
            reply_markup=admin_back_keyboard(),
        )
        return
    await callback.answer("Xatolik.", show_alert=True)


@router.callback_query(F.data.startswith("vipreceipt:"))
async def vipreceipt_callback(callback: CallbackQuery):
    if not _has_perm(callback.from_user.id, "can_manage_vip"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Xatolik.", show_alert=True)
        return
    action = parts[1]
    try:
        user_id = int(parts[2])
    except ValueError:
        await callback.answer("Xatolik.", show_alert=True)
        return
    if action == "approve":
        if user_id in VIP_RECEIPT_REJECTED:
            rejector_id = VIP_RECEIPT_REJECTED.get(user_id)
            rejector = f"@{callback.from_user.username}" if callback.from_user.username else str(callback.from_user.id)
            if rejector_id and rejector_id != callback.from_user.id:
                await callback.message.edit_text(
                    f"Chek rad etilgan. Rad qilgan: {rejector}",
                )
                await callback.answer("Bu chek rad etilgan.", show_alert=True)
                return
        if user_id in VIP_RECEIPT_APPROVED:
            approver_id = VIP_RECEIPT_APPROVED.get(user_id)
            approver = f"@{callback.from_user.username}" if callback.from_user.username else str(callback.from_user.id)
            if approver_id and approver_id != callback.from_user.id:
                await callback.message.edit_text(
                    f"Chek tasdiqlangan. Tasdiqlagan: {approver}",
                )
                await callback.answer("Bu chek allaqachon tasdiqlangan.", show_alert=True)
                return
        VIP_ADD_SESSIONS[callback.from_user.id] = user_id
        VIP_RECEIPT_APPROVED[user_id] = callback.from_user.id
        admin_label = (
            f"@{callback.from_user.username}"
            if callback.from_user.username
            else str(callback.from_user.id)
        )
        admins = [admin_id for admin_id in get_admins() if has_admin_permission(admin_id, "can_manage_vip")]
        if OWNER_ID and OWNER_ID not in admins:
            admins.append(OWNER_ID)
        notify_text = (
            "VIP cheki tasdiqlandi.\n"
            f"user_id: {user_id}\n"
            f"Tasdiqlagan: {admin_label}"
        )
        for admin_id in admins:
            if admin_id == callback.from_user.id:
                continue
            try:
                await callback.bot.send_message(admin_id, notify_text)
            except Exception:
                continue
        await _update_receipt_status(
            callback.bot,
            user_id,
            f"Chek tasdiqlangan. Tasdiqlagan: {admin_label}",
        )
        await callback.message.edit_text(
            f"VIP tasdiqlash: {user_id}. Muddatni tanlang:",
            reply_markup=vip_duration_keyboard(user_id),
        )
        return
    if action == "reject":
        if user_id in VIP_RECEIPT_APPROVED:
            approver_id = VIP_RECEIPT_APPROVED.get(user_id)
            approver = (
                f"@{callback.from_user.username}"
                if callback.from_user.username
                else str(callback.from_user.id)
            )
            if approver_id and approver_id != callback.from_user.id:
                await callback.message.edit_text(
                    f"Chek tasdiqlangan. Tasdiqlagan: {approver}",
                )
                await callback.answer("Bu chek tasdiqlangan.", show_alert=True)
                return
        if user_id in VIP_RECEIPT_REJECTED:
            rejector_id = VIP_RECEIPT_REJECTED.get(user_id)
            rejector = (
                f"@{callback.from_user.username}"
                if callback.from_user.username
                else str(callback.from_user.id)
            )
            if rejector_id and rejector_id != callback.from_user.id:
                await callback.message.edit_text(
                    f"Chek rad etilgan. Rad qilgan: {rejector}",
                )
                await callback.answer("Bu chek rad etilgan.", show_alert=True)
                return
        VIP_RECEIPT_REJECTED[user_id] = callback.from_user.id
        VIP_REJECT_SESSIONS[callback.from_user.id] = user_id
        await callback.message.edit_text("Rad etish sababini yuboring.")
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
    if not _has_perm(message.from_user.id, "can_view_lists"):
        await message.answer("Bu buyruq uchun ruxsat yo'q.")
        return
    if not command.args:
        await message.answer("Foydalanish: /post <drama_kod>")
        return
    code = _parse_code(command.args)
    if not code:
        await message.answer("Kod faqat raqam bo'lishi kerak.")
        return
    serial = get_serial_by_code(int(code))
    if not serial:
        await message.answer("Drama topilmadi.")
        return
    parts_count = len(get_serial_parts(serial["id"]))
    POST_SESSIONS[message.from_user.id] = {
        "serial_id": serial["id"],
        "title": serial["title"],
        "code": serial["code"],
        "parts_count": parts_count,
    }
    await message.answer(
        "Rasm yuboring yoki \"Rasmsiz\" tugmasini bosing.",
        reply_markup=post_media_keyboard(),
    )
    _log_event("post_start", message.from_user.id, f"serial_id={serial['id']}")


@router.callback_query(F.data.startswith("post:"))
async def post_callback(callback: CallbackQuery):
    if not _has_perm(callback.from_user.id, "can_view_lists"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    session = POST_SESSIONS.get(callback.from_user.id)
    if not session:
        await callback.answer("Sessiya topilmadi.", show_alert=True)
        return
    action = callback.data.split(":")[-1]
    if action == "cancel":
        POST_SESSIONS.pop(callback.from_user.id, None)
        await callback.message.edit_text("Post yaratish bekor qilindi.")
        _log_event("post_cancel", callback.from_user.id)
        return
    if action != "skip":
        await callback.answer("Xatolik.", show_alert=True)
        return
    link = await _get_start_link(callback.bot, int(session["code"]))
    if not link:
        await callback.message.edit_text("Bot linkini olishda xatolik.")
        return
    text = _build_serial_post_text(session["title"], session["parts_count"], link)
    POST_SESSIONS.pop(callback.from_user.id, None)
    await callback.message.edit_text(text, reply_markup=post_link_keyboard(link))
    _log_event("post_created", callback.from_user.id, f"serial_id={session['serial_id']}")


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
    parts = get_serial_parts(serial["id"])
    next_part = (max((p["part"] for p in parts), default=0) + 1) if parts else 1
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
        BROADCAST_SESSIONS[message.from_user.id] = {
            "mode": "reply",
            "from_chat_id": message.chat.id,
            "reply_message_id": message.message_id,
        }
        await message.answer("Kimlarga yuborilsin?", reply_markup=broadcast_target_keyboard())
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
        f"name: {name_text}"
    )
    for admin_id in admins:
        try:
            await message.bot.send_message(admin_id, header)
            await message.copy_to(admin_id)
        except Exception:
            continue
    CONTACT_ADMIN_SESSIONS.discard(message.from_user.id)
    await message.answer("Xabaringiz adminlarga yuborildi.", reply_markup=ReplyKeyboardRemove())
    await message.answer("Menyu:", reply_markup=user_keyboard())


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
    BROADCAST_SESSIONS[message.from_user.id] = {
        "mode": "reply",
        "from_chat_id": message.chat.id,
        "reply_message_id": message.message_id,
    }
    await message.answer("Kimlarga yuborilsin?", reply_markup=broadcast_target_keyboard())


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


@router.message(F.photo)
async def post_photo_handler(message: Message):
    if not _has_perm(message.from_user.id, "can_view_lists"):
        return
    session = POST_SESSIONS.get(message.from_user.id)
    if not session:
        return
    link = await _get_start_link(message.bot, int(session["code"]))
    if not link:
        await message.answer("Bot linkini olishda xatolik.")
        return
    text = _build_serial_post_text(session["title"], session["parts_count"], link)
    photo = message.photo[-1]
    await message.answer_photo(
        photo.file_id,
        caption=text,
        reply_markup=post_link_keyboard(link),
    )
    POST_SESSIONS.pop(message.from_user.id, None)
    _log_event("post_created", message.from_user.id, f"serial_id={session['serial_id']}")
async def _show_serial_parts(message: Message, serial_id: int) -> bool:
    parts = get_serial_parts(serial_id)
    if not parts:
        return False
    part_numbers = [int(item["part"]) for item in parts if item.get("part") is not None]
    if not part_numbers:
        return False
    first_part = min(part_numbers)
    return await _send_serial_part(
        message,
        serial_id,
        first_part,
        part_numbers=part_numbers,
    )


async def _send_serial_part(
    message: Message,
    serial_id: int,
    part: int,
    part_numbers: Optional[list[int]] = None,
) -> bool:
    item = get_serial_part(serial_id, part)
    if not item:
        return False
    caption = item.get("caption") or None
    serial = get_serial_by_id(serial_id)
    if serial:
        record_serial_view(_today(), int(serial["code"]))
    if part_numbers is None:
        parts = get_serial_parts(serial_id)
        part_numbers = [int(row["part"]) for row in parts if row.get("part") is not None]
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
    reply_markup = serial_parts_keyboard(
        serial_id,
        part_numbers_sorted or [part],
        page=page,
        per_page=SERIAL_PARTS_PER_PAGE,
        share_link=share_link,
    )
    source_chat_id = item.get("source_chat_id")
    source_message_id = item.get("source_message_id")
    if source_chat_id and source_message_id:
        copied = await _safe_copy_message(
            message.bot,
            message.chat.id,
            source_chat_id,
            source_message_id,
        )
        if copied:
            if reply_markup:
                await _safe_edit_reply_markup(
                    message.bot,
                    message.chat.id,
                    copied.message_id,
                    reply_markup,
                )
            return True
    if item.get("file_type") == "document":
        ok = await _safe_send_document(
            message,
            item["file_id"],
            caption,
            reply_markup=reply_markup,
        )
    else:
        ok = await _safe_send_video(
            message,
            item["file_id"],
            caption,
            reply_markup=reply_markup,
        )
    if ok:
        return True
    if not ok:
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


@router.message(Command("serial"))
async def serial_command_handler(message: Message, command: CommandObject):
    if not command.args:
        await message.answer("Foydalanish: /serial <drama_nomi|kod>")
        return
    raw = command.args.strip()
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


@router.message(F.text & ~F.text.startswith("/"))
async def movie_text_handler(message: Message):
    if not await ensure_subscribed(message):
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
        USER_SEARCH_SESSIONS.add(message.from_user.id)
        USER_SEARCH_RESULTS.pop(message.from_user.id, None)
        await message.answer("Drama nomini yozing:", reply_markup=user_search_keyboard())
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
    while True:
        try:
            await _run_vip_reminders(bot)
        except Exception:
            pass
        await asyncio.sleep(3600)


async def _run_vip_reminders(bot) -> None:
    users = get_vip_users()
    if not users:
        return
    now = dt.datetime.utcnow()
    price = _get_vip_price()
    for item in users:
        try:
            expires_at = dt.datetime.fromisoformat(item["expires_at"])
        except Exception:
            continue
        days_left = (expires_at.date() - now.date()).days
        if days_left < 0:
            remove_vip_user(item["user_id"])
            try:
                await bot.send_message(item["user_id"], "VIP obuna muddati tugadi.")
            except Exception:
                pass
            continue
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


async def _process_serial_part_message(message: Message, serial_id: int) -> None:
    if not _has_perm(message.from_user.id, "can_add_part"):
        await message.answer("Bu buyruq uchun ruxsat yo'q.")
        return
    key = (message.from_user.id, serial_id)
    part = SERIAL_UPLOAD_NEXT_PART.get(key)
    if part is None:
        session = get_serial_session(message.from_user.id)
        part = session.get("next_part") if session else None
        part = part or 1
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
    msg = await _safe_send_to_channel(
        message.bot,
        SOURCE_CHANNEL_ID,
        file_id,
        file_type,
        caption,
    )
    if not msg:
        await message.answer("Kanalga yuklab bo'lmadi.")
        return
    add_serial_part(
        serial_id,
        part,
        file_id,
        file_type,
        caption or "",
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
    next_part = part + 1
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
    return ok, failed


async def _broadcast_to_user_ids(
    message: Message,
    user_ids: list[int],
    text: Optional[str],
    from_chat_id: Optional[int] = None,
    reply_message_id: Optional[int] = None,
) -> tuple[int, int]:
    ok = 0
    failed = 0
    for user_id in user_ids:
        try:
            if reply_message_id and from_chat_id:
                await message.bot.copy_message(
                    chat_id=user_id,
                    from_chat_id=from_chat_id,
                    message_id=reply_message_id,
                    protect_content=True,
                )
            else:
                await message.bot.send_message(chat_id=user_id, text=text or "")
            ok += 1
        except TelegramAPIError as exc:
            _log_event("broadcast_failed", message.from_user.id, f"user_id={user_id} error={exc}")
            failed += 1
        except Exception:
            _log_event("broadcast_failed", message.from_user.id, f"user_id={user_id} error=unknown")
            failed += 1
    return ok, failed


def _collect_broadcast_targets(kind: str) -> list[int]:
    if kind == "admins":
        return list({int(admin_id) for admin_id in get_admins()})
    users = [user.get("user_id") for user in get_users() if user.get("user_id")]
    users_set = {int(uid) for uid in users}
    if kind == "all":
        return list(users_set)
    vip_ids = {
        int(item["user_id"])
        for item in get_vip_users()
        if item.get("user_id") and _is_vip_user(int(item["user_id"]))
    }
    if kind == "vip":
        return list(vip_ids)
    if kind == "regular":
        admin_ids = {int(admin_id) for admin_id in get_admins()}
        return list(users_set - vip_ids - admin_ids)
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
        BROADCAST_SESSIONS[message.from_user.id] = {
            "mode": "reply",
            "from_chat_id": message.chat.id,
            "reply_message_id": message.reply_to_message.message_id,
        }
    else:
        text = command.args.strip()
        BROADCAST_SESSIONS[message.from_user.id] = {
            "mode": "text",
            "text": text,
        }
    await message.answer("Kimlarga yuborilsin?", reply_markup=broadcast_target_keyboard())


@router.message(Command("cancel"))
async def cancel_handler(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Bekor qilindi.")
        return
    if message.from_user.id in BROADCAST_TEXT_SESSIONS or message.from_user.id in BROADCAST_SESSIONS:
        BROADCAST_TEXT_SESSIONS.discard(message.from_user.id)
        BROADCAST_SESSIONS.pop(message.from_user.id, None)
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
        BROADCAST_SESSIONS[message.from_user.id] = {
            "mode": "reply",
            "from_chat_id": message.chat.id,
            "reply_message_id": message.reply_to_message.message_id,
        }
        await message.answer("Kimlarga yuborilsin?", reply_markup=broadcast_target_keyboard())
        return
    text = (message.text or "").strip()
    if not text:
        await message.answer("E'lon matnini yuboring.")
        return
    BROADCAST_TEXT_SESSIONS.discard(message.from_user.id)
    BROADCAST_SESSIONS[message.from_user.id] = {
        "mode": "text",
        "text": text,
    }
    await message.answer("Kimlarga yuborilsin?", reply_markup=broadcast_target_keyboard())


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
    targets = _collect_broadcast_targets(action)
    if not targets:
        await callback.message.edit_text("Foydalanuvchilar topilmadi.", reply_markup=admin_back_keyboard())
        BROADCAST_SESSIONS.pop(callback.from_user.id, None)
        return
    if session.get("mode") == "reply":
        ok, failed = await _broadcast_to_user_ids(
            callback.message,
            targets,
            text=None,
            from_chat_id=session.get("from_chat_id"),
            reply_message_id=session.get("reply_message_id"),
        )
    else:
        ok, failed = await _broadcast_to_user_ids(
            callback.message,
            targets,
            text=session.get("text"),
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
    ok, failed = await _broadcast_to_user_ids(
        callback.message,
        targets,
        text=text,
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
    ok, failed = await _broadcast_to_user_ids(
        callback.message,
        targets,
        text=text,
    )
    await callback.message.edit_text(f"Yuborildi: {ok}, xatolik: {failed}")
    _log_event(
        "broadcast_new_part",
        callback.from_user.id,
        f"serial_id={serial_id} part={part} target={target} ok={ok} failed={failed}",
    )
