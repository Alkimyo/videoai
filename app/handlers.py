import asyncio
import datetime as dt
import os
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
from aiogram.types import CallbackQuery, ChatJoinRequest, FSInputFile, Message
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
    init_db,
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
    log_cancel_keyboard,
    post_media_keyboard,
    serial_cancel_keyboard,
    serial_flow_keyboard,
    serial_parts_keyboard,
    serials_list_keyboard,
    subscribe_keyboard,
    users_keyboard,
    user_keyboard,
)

SERIAL_PARTS_PER_PAGE = 20
SERIALS_PER_PAGE = 20
USERS_PER_PAGE = 20
LOG_QUERY_ADMINS: set[int] = set()
ADMIN_ADD_SESSIONS: dict[int, dict[str, object]] = {}
RESTORE_DB_SESSIONS: dict[int, dict[str, object]] = {}
POST_SESSIONS: dict[int, dict[str, object]] = {}
ADMIN_PERMISSION_LABELS = {
    "can_manage_admins": "Adminlarni boshqarish",
    "can_manage_channels": "Kanallarni boshqarish",
    "can_add_serial": "Serial qo'shish",
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


async def ensure_subscribed(message: Message) -> bool:
    user_id = message.from_user.id
    if is_admin(user_id):
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


@router.callback_query(F.data == "check_subs")
async def check_subs_callback(callback: CallbackQuery):
    channels = get_channels()
    ok = await _check_subscriptions(callback.bot, callback.from_user.id, channels)
    if ok:
        await callback.message.edit_text("Obuna tasdiqlandi. Serial kodini yuboring.")
    else:
        await callback.answer("Hali obuna emassiz.", show_alert=True)


@router.callback_query(F.data == "user:sendcode")
async def user_send_code_callback(callback: CallbackQuery):
    await callback.message.edit_text("Serial kodini yuboring.")


@router.callback_query(F.data == "noop")
async def noop_callback(callback: CallbackQuery):
    await callback.answer()


@router.callback_query(F.data.startswith("serialpart:"))
async def serial_part_callback(callback: CallbackQuery):
    channels = get_channels()
    if channels:
        ok = await _check_subscriptions(callback.bot, callback.from_user.id, channels)
        if not ok:
            await callback.answer("Avval obuna bo'ling.", show_alert=True)
            return
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
    ok = await _send_serial_part(callback.message, serial_id, part)
    if not ok:
        await callback.answer("Qism topilmadi.", show_alert=True)
        return
    _log_event("serial_part_sent", callback.from_user.id, f"serial_id={serial_id} part={part}")


@router.callback_query(F.data.startswith("serialpage:"))
async def serial_page_callback(callback: CallbackQuery):
    channels = get_channels()
    if channels:
        ok = await _check_subscriptions(callback.bot, callback.from_user.id, channels)
        if not ok:
            await callback.answer("Avval obuna bo'ling.", show_alert=True)
            return
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
        await callback.answer("Serial topilmadi.", show_alert=True)
        return
    serial_parts = get_serial_parts(serial_id)
    part_numbers = [int(item["part"]) for item in serial_parts if item.get("part") is not None]
    if not part_numbers:
        await callback.answer("Serialda qismlar yo'q.", show_alert=True)
        return
    await callback.message.edit_text(
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


async def _get_share_link(bot, serial_code: int) -> Optional[str]:
    try:
        me = await bot.get_me()
    except Exception:
        return None
    if not me.username:
        return None
    target_url = f"https://t.me/{me.username}?start={serial_code}"
    share_url = (
        "https://t.me/share/url?"
        f"url={urllib.parse.quote(target_url)}"
        f"&text={urllib.parse.quote('Serialni ochish uchun link')}"
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
        f"Qismlar soni: {parts_count}\n"
        f"Dramani ko'rish: {link}"
    )


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


async def _safe_send_video(
    message: Message,
    file_id: str,
    caption: Optional[str],
    reply_markup=None,
) -> None:
    while True:
        try:
            await message.answer_video(
                file_id,
                caption=caption,
                protect_content=True,
                reply_markup=reply_markup,
            )
            return
        except TelegramRetryAfter as err:
            await _wait_retry(err)
        except TelegramAPIError:
            return


async def _safe_send_document(
    message: Message,
    file_id: str,
    caption: Optional[str],
    reply_markup=None,
) -> None:
    while True:
        try:
            await message.answer_document(
                file_id,
                caption=caption,
                protect_content=True,
                reply_markup=reply_markup,
            )
            return
        except TelegramRetryAfter as err:
            await _wait_retry(err)
        except TelegramAPIError:
            return


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
            await message.answer("Serial topilmadi.")
            return
    banner = (
        "====================\n"
        "   S E R I A L  B O T\n"
        "====================\n"
        "Serial kodini yuboring."
    )
    await message.answer(banner, reply_markup=user_keyboard())


@router.message(Command("help"))
async def help_handler(message: Message):
    if not await ensure_subscribed(message):
        return
    text = (
        "Buyruqlar:\n"
        "/admin - admin panel\n"
        "/addadmin <user_id> - admin qo'shish\n"
        "/deladmin <user_id> - admin chiqarish\n"
        "/admins - adminlar ro'yxati\n"
        "/addchannel <@username|chat_id> [invite_link] - majburiy kanal qo'shish\n"
        "/delchannel <@username|chat_id> - kanalni chiqarish\n"
        "/channels - kanallar ro'yxati\n"
        "/serial <nom|kod> - serialni yuborish\n"
        "/broadcast <text> - barchaga xabar (admin)\n"
        "/broadcast - reply bilan rasm/video yuborish\n"
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


@router.message(Command("admins"))
async def list_admins_handler(message: Message):
    if not _has_perm(message.from_user.id, "can_view_lists"):
        await message.answer("Bu buyruq uchun ruxsat yo'q.")
        return
    admins = get_admins()
    if not admins:
        await message.answer("Adminlar yo'q.")
        return
    lines = ["Adminlar:"]
    for admin_id in admins:
        perms = get_admin_permissions(admin_id) or _default_admin_permissions()
        lines.append(f"{admin_id} | {_format_perm_inline(perms)}")
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
    await callback.message.edit_text("Admin panel:", reply_markup=admin_panel_keyboard())


@router.callback_query(F.data == "serial:cancel")
async def serial_cancel_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    clear_serial_session(callback.from_user.id)
    await callback.message.edit_text(
        "Serial qo'shish bekor qilindi.",
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
        await callback.answer("Serial sessiya topilmadi.", show_alert=True)
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
        lines = ["Adminlar:"]
        for admin_id in admins:
            perms = get_admin_permissions(admin_id) or _default_admin_permissions()
            lines.append(f"{admin_id} | {_format_perm_inline(perms)}")
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
        lines.append("Top serial kodlari:")
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
        await callback.answer("Serial topilmadi.", show_alert=True)
        return
    ok = await _show_serial_parts(callback.message, serial["id"])
    if not ok:
        await callback.answer("Serialda qismlar yo'q.", show_alert=True)


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
        user.get("username") or str(user.get("user_id"))
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
        await callback.message.edit_text("Seriallar yo'q.", reply_markup=admin_back_keyboard())
        return
    total = len(serials)
    total_pages = max(1, (total + SERIALS_PER_PAGE - 1) // SERIALS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * SERIALS_PER_PAGE
    end = start + SERIALS_PER_PAGE
    page_serials = serials[start:end]
    header = f"Seriallar: {total} ta"
    body = "\n".join(
        f"{item.get('code')} - {item.get('title')}"
        for item in page_serials
    )
    text = f"{header}\n{body}"
    await callback.message.edit_text(
        text,
        reply_markup=serials_list_keyboard(page_serials, page, total_pages),
    )


@router.callback_query(F.data == "admin:logs")
async def admin_logs_callback(callback: CallbackQuery):
    if not _has_perm(callback.from_user.id, "can_view_logs"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    LOG_QUERY_ADMINS.add(callback.from_user.id)
    await callback.message.edit_text(
        "Foydalanuvchi ID yoki @username yuboring.",
        reply_markup=log_cancel_keyboard(),
    )


@router.callback_query(F.data == "admin:logfile")
async def admin_logfile_callback(callback: CallbackQuery):
    if not _has_perm(callback.from_user.id, "can_view_logs"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    await callback.message.edit_text("Log fayl yuborilmoqda...")
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
        "/addchannel <@username|chat_id> [invite_link]\n"
        "/delchannel <@username|chat_id>\n"
        "/addserial (inline)\n"
        "/addpart <serial_nomi|kod>\n"
        "/part <qism_raqami>\n"
        "Admin panel -> Loglar\n"
        "Admin panel -> Log fayl\n"
        "Admin panel -> Seriallar\n"
        "Admin panel -> Statistika\n"
        "Admin panel -> Backup\n"
        "Admin panel -> Foydalanuvchilar\n"
        "/log <user_id|@username>\n"
        "/logfile\n"
        "/stats\n"
        "/backup\n"
        "/restoredb\n"
        "/cancelrestore\n"
        "/post <serial_kod>\n"
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
        "Serial nomini yuboring.",
        reply_markup=serial_cancel_keyboard(),
    )


@router.callback_query(F.data == "admin:addpart")
async def admin_addpart_callback(callback: CallbackQuery):
    if not _has_perm(callback.from_user.id, "can_add_part"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    await callback.message.edit_text(
        "Foydalanish: /addpart <serial_nomi|kod>",
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
    await callback.message.edit_text(
        "Foydalanish: /broadcast <text> yoki reply bilan yuboring.",
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
    await message.answer("Backup zip yoki bot.db faylni yuboring. Bekor qilish: /cancelrestore")
    _log_event("restore_db_start", message.from_user.id)


@router.message(Command("post"))
async def post_handler(message: Message, command: CommandObject):
    if not _has_perm(message.from_user.id, "can_view_lists"):
        await message.answer("Bu buyruq uchun ruxsat yo'q.")
        return
    if not command.args:
        await message.answer("Foydalanish: /post <serial_kod>")
        return
    code = _parse_code(command.args)
    if not code:
        await message.answer("Kod faqat raqam bo'lishi kerak.")
        return
    serial = get_serial_by_code(int(code))
    if not serial:
        await message.answer("Serial topilmadi.")
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
    link = await _get_share_link(callback.bot, int(session["code"]))
    if not link:
        await callback.message.edit_text("Bot linkini olishda xatolik.")
        return
    text = _build_serial_post_text(session["title"], session["parts_count"], link)
    POST_SESSIONS.pop(callback.from_user.id, None)
    await callback.message.edit_text(text)
    _log_event("post_created", callback.from_user.id, f"serial_id={session['serial_id']}")


@router.message(Command("cancelrestore"))
async def cancel_restore_handler(message: Message):
    if message.from_user.id != OWNER_ID:
        await message.answer("Bu buyruq faqat owner uchun.")
        return
    _cleanup_restore_session(message.from_user.id)
    await message.answer("DB tiklash bekor qilindi.")
    _log_event("restore_db_cancel", message.from_user.id)


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
        await message.answer("Foydalanish: /addpart <serial_nomi|kod>")
        return
    raw = command.args.strip()
    serial = None
    if raw.isdigit():
        serial = get_serial_by_code(int(raw))
    if not serial:
        serial = get_serial_by_title(raw)
    if not serial:
        await message.answer("Serial topilmadi.")
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
        await message.answer("Serial sessiya topilmadi. /addserial yoki /addpart ishlating.")
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


@router.message(F.text & ~F.text.startswith("/"))
async def admin_serial_text_handler(message: Message):
    if not is_admin(message.from_user.id):
        return
    session = get_serial_session(message.from_user.id)
    if not session:
        return
    state = session.get("state")
    if state == "await_title":
        if not _has_perm(message.from_user.id, "can_add_serial"):
            await message.answer("Bu buyruq uchun ruxsat yo'q.")
            return
        title = message.text.strip()
        if not title:
            await message.answer("Serial nomi bo'sh bo'lmasin.")
            return
        existing = get_serial_by_title(title)
        if existing:
            await message.answer(
                f"Serial mavjud. Kod: {existing['code']}. /addpart <serial_nomi|kod> bilan davom ettiring."
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
            f"Serial yaratildi: {serial['title']}. Kod: {serial['code']}. 1-qismni yuboring.",
            reply_markup=serial_flow_keyboard(),
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


@router.message(F.video | F.document)
async def admin_serial_media_handler(message: Message):
    if not is_admin(message.from_user.id):
        return
    if message.from_user.id in RESTORE_DB_SESSIONS:
        return
    if message.from_user.id in POST_SESSIONS:
        return
    if not _has_perm(message.from_user.id, "can_add_part"):
        await message.answer("Bu buyruq uchun ruxsat yo'q.")
        return
    session = get_serial_session(message.from_user.id)
    if not session or session.get("state") != "await_part":
        return
    serial_id = session.get("serial_id")
    if not serial_id:
        await message.answer("Serial topilmadi. /addserial yoki /addpart ishlating.")
        return
    part = session.get("next_part") or 1
    while serial_part_exists(serial_id, part):
        part += 1
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
        f"serial_id={serial_id} part={part}",
    )
    next_part = part + 1
    save_serial_session(
        message.from_user.id,
        state="await_part",
        serial_id=serial_id,
        next_part=next_part,
        created_at=session.get("created_at") or _now(),
    )
    await message.answer(
        f"{part}-qism qabul qilindi. Davom ettirasizmi?",
        reply_markup=serial_flow_keyboard(),
    )


@router.message(F.document)
async def restore_db_document_handler(message: Message):
    if message.from_user.id != OWNER_ID:
        return
    session = RESTORE_DB_SESSIONS.get(message.from_user.id)
    if not session or session.get("state") != "await_file":
        return
    document = message.document
    if not document:
        return
    filename = (document.file_name or "").lower()
    if not (filename.endswith(".db") or filename.endswith(".zip")):
        await message.answer("Faqat .db yoki .zip fayl yuboring.")
        return
    temp_dir = tempfile.mkdtemp(prefix="serialbot-restore-")
    RESTORE_DB_SESSIONS[message.from_user.id]["cleanup"].append(temp_dir)
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
        os.replace(db_path, DB_PATH)
        init_db()
    except Exception:
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
    link = await _get_share_link(message.bot, int(session["code"]))
    if not link:
        await message.answer("Bot linkini olishda xatolik.")
        return
    text = _build_serial_post_text(session["title"], session["parts_count"], link)
    photo = message.photo[-1]
    await message.answer_photo(photo.file_id, caption=text)
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
    share_link = await _get_share_link(message.bot, serial["code"]) if serial else None
    if part_numbers is None:
        parts = get_serial_parts(serial_id)
        part_numbers = [int(row["part"]) for row in parts if row.get("part") is not None]
    part_numbers_sorted = sorted(part_numbers) if part_numbers else []
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
    if item.get("file_type") == "document":
        await _safe_send_document(message, item["file_id"], caption, reply_markup=reply_markup)
    else:
        await _safe_send_video(message, item["file_id"], caption, reply_markup=reply_markup)
    return True


@router.message(Command("movie"))
async def movie_command_disabled(message: Message, command: CommandObject):
    await message.answer("Kino funksiyalari o'chirilgan.")


@router.message(Command("serial"))
async def serial_command_handler(message: Message, command: CommandObject):
    if not await ensure_subscribed(message):
        return
    if not command.args:
        await message.answer("Foydalanish: /serial <nom|kod>")
        return
    raw = command.args.strip()
    _log_event("serial_request", message.from_user.id, f"query={raw}")
    serial = None
    if raw.isdigit():
        serial = get_serial_by_code(int(raw))
    if not serial:
        serial = get_serial_by_title(raw)
    if not serial:
        await message.answer("Serial topilmadi.")
        return
    if not await _show_serial_parts(message, serial["id"]):
        await message.answer("Serialda qismlar yo'q.")


@router.message(F.text & ~F.text.startswith("/"))
async def movie_text_handler(message: Message):
    if not await ensure_subscribed(message):
        return
    if is_admin(message.from_user.id) and get_serial_session(message.from_user.id):
        return
    raw = message.text.strip()
    if raw == "Serial kodini yuborish":
        await message.answer("Serial kodini yuboring.")
        return
    code = _parse_code(raw)
    if code:
        _log_event("serial_request", message.from_user.id, f"query={code}")
        serial = get_serial_by_code(int(code))
        if serial and await _show_serial_parts(message, serial["id"]):
            return
        await message.answer("Serial topilmadi.")
        return
    serial = get_serial_by_title(raw)
    _log_event("serial_request", message.from_user.id, f"query={raw}")
    if serial and await _show_serial_parts(message, serial["id"]):
        return
    await message.answer("Serial topilmadi.")


@router.message(Command("stats"))
async def stats_handler(message: Message):
    if not _has_perm(message.from_user.id, "can_view_stats"):
        await message.answer("Bu buyruq uchun ruxsat yo'q.")
        return
    day = _today()
    total, top = get_serial_day_stats(day)
    lines = [f"Bugungi ko'rishlar: {total}"]
    if top:
        lines.append("Top serial kodlari:")
        lines.extend([f"{code} - {count}" for code, count in top])
    recent = get_serial_recent_days()
    if recent:
        lines.append("So'nggi kunlar:")
        lines.extend([f"{d}: {c}" for d, c in recent])
    await message.answer("\n".join(lines))
    _log_event("stats_view", message.from_user.id)


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
    await message.answer_document(FSInputFile(LOG_PATH), caption="Log fayl")


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
        except Exception:
            failed += 1
    return ok, failed


@router.message(Command("broadcast"))
async def broadcast_handler(message: Message, command: CommandObject):
    if not _has_perm(message.from_user.id, "can_broadcast"):
        await message.answer("Bu buyruq uchun ruxsat yo'q.")
        return
    if not command.args and not message.reply_to_message:
        await message.answer("Foydalanish: /broadcast <text> yoki reply bilan yuboring.")
        return
    text = command.args.strip() if command.args else None
    ok, failed = await _broadcast_to_users(message, text)
    await message.answer(f"Yuborildi: {ok}, xatolik: {failed}")
    _log_event("broadcast", message.from_user.id, f"ok={ok} failed={failed}")
