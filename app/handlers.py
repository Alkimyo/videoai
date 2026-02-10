import asyncio
import datetime as dt
import os
from collections import deque
from typing import Optional

from aiogram import F, Router
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, ChatJoinRequest, Message

from app.config import LOG_PATH, MAX_MOVIES_PER_CODE, OWNER_ID, SOURCE_CHANNEL_ID
from app.db import (
    add_admin,
    add_channel,
    add_movie,
    add_serial,
    add_serial_part,
    add_join_request,
    add_user,
    count_movies_for_code,
    del_admin,
    del_channel,
    del_movie,
    get_admins,
    get_channels,
    get_day_stats,
    get_movie_items,
    get_next_code,
    get_recent_days,
    get_serial_by_code,
    get_serial_by_id,
    get_serial_by_title,
    get_serial_part,
    get_serial_parts,
    get_serial_session,
    is_admin,
    serial_part_exists,
    save_serial_session,
    clear_serial_session,
    get_users,
    has_join_request,
    record_view,
)
from app.keyboards import (
    admin_back_keyboard,
    admin_panel_keyboard,
    log_cancel_keyboard,
    serial_cancel_keyboard,
    serial_flow_keyboard,
    serial_parts_keyboard,
    subscribe_keyboard,
    users_keyboard,
    user_keyboard,
)

SERIAL_PARTS_PER_PAGE = 20
USERS_PER_PAGE = 20
LOG_QUERY_ADMINS: set[int] = set()

router = Router()
SEND_DELAY_SECONDS = 0.7
LOG_TAIL_LINES = 40


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
        await callback.message.edit_text("Obuna tasdiqlandi. Kino kodini yuboring.")
    else:
        await callback.answer("Hali obuna emassiz.", show_alert=True)


@router.callback_query(F.data == "user:sendcode")
async def user_send_code_callback(callback: CallbackQuery):
    await callback.message.edit_text("Kino kodini yuboring.")


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


def _generate_code() -> str:
    return str(get_next_code())


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
    with open(LOG_PATH, "a", encoding="utf-8") as handle:
        handle.write(f"{line}\n")


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


async def _safe_copy_message(
    bot, chat_id: int, from_chat_id: int, message_id: int
) -> None:
    while True:
        try:
            await bot.copy_message(
                chat_id=chat_id,
                from_chat_id=from_chat_id,
                message_id=message_id,
                protect_content=True,
            )
            return
        except TelegramRetryAfter as err:
            await _wait_retry(err)
        except TelegramAPIError:
            return


async def _safe_send_video(message: Message, file_id: str, caption: Optional[str]) -> None:
    while True:
        try:
            await message.answer_video(
                file_id,
                caption=caption,
                protect_content=True,
            )
            return
        except TelegramRetryAfter as err:
            await _wait_retry(err)
        except TelegramAPIError:
            return


async def _safe_send_document(message: Message, file_id: str, caption: Optional[str]) -> None:
    while True:
        try:
            await message.answer_document(
                file_id,
                caption=caption,
                protect_content=True,
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


@router.message(Command("start"))
async def start_handler(message: Message):
    add_user(message.from_user.id)
    _log_event("user_start", message.from_user.id)
    if not await ensure_subscribed(message):
        return
    banner = (
        "====================\n"
        "   K I N O  B O T\n"
        "====================\n"
        "Kino kodini yuboring."
    )
    await message.answer(banner, reply_markup=user_keyboard())


@router.message(Command("help"))
async def help_handler(message: Message):
    if not await ensure_subscribed(message):
        return
    text = (
        "Buyruqlar:\n"
        "/admin - admin panel\n"
        "/addadmin <user_id> - admin qo'shish (faqat owner)\n"
        "/deladmin <user_id> - admin chiqarish (faqat owner)\n"
        "/admins - adminlar ro'yxati\n"
        "/addchannel <@username|chat_id> [invite_link] - majburiy kanal qo'shish\n"
        "/delchannel <@username|chat_id> - kanalni chiqarish\n"
        "/channels - kanallar ro'yxati\n"
        "/addmovie [code] - video ustidan reply qilib qo'shish\n"
        "/delmovie <code> - kino o'chirish\n"
        "/movie <code> - kinoni yuborish\n"
        "/serial <nom|kod> - serialni yuborish\n"
        "/stats - kunlik ko'rishlar\n"
        "/broadcast <text> - barchaga xabar (admin)\n"
        "/broadcast - reply bilan rasm/video yuborish\n"
    )
    await message.answer(text)


@router.message(Command("addadmin"))
async def add_admin_handler(message: Message, command: CommandObject):
    if message.from_user.id != OWNER_ID:
        await message.answer("Bu buyruq faqat owner uchun.")
        return
    if not command.args:
        await message.answer("Foydalanish: /addadmin <user_id>")
        return
    try:
        user_id = int(command.args.strip())
    except ValueError:
        await message.answer("user_id raqam bo'lishi kerak.")
        return
    add_admin(user_id)
    await message.answer("Admin qo'shildi.")


@router.message(Command("deladmin"))
async def del_admin_handler(message: Message, command: CommandObject):
    if message.from_user.id != OWNER_ID:
        await message.answer("Bu buyruq faqat owner uchun.")
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
    await message.answer("Admin chiqarildi.")


@router.message(Command("admins"))
async def list_admins_handler(message: Message):
    if message.from_user.id != OWNER_ID:
        await message.answer("Bu buyruq faqat owner uchun.")
        return
    admins = get_admins()
    if not admins:
        await message.answer("Adminlar yo'q.")
        return
    text = "Adminlar:\n" + "\n".join(str(admin_id) for admin_id in admins)
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
    session = get_serial_session(callback.from_user.id)
    if not session or session.get("state") != "await_part":
        await callback.answer("Serial sessiya topilmadi.", show_alert=True)
        return
    next_part = session.get("next_part") or 1
    await callback.message.edit_text(f"{next_part}-qismni yuboring.")


@router.callback_query(F.data == "admin:admins")
async def admin_list_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    admins = get_admins()
    text = "Adminlar:\n" + "\n".join(str(admin_id) for admin_id in admins) if admins else "Adminlar yo'q."
    await callback.message.edit_text(text, reply_markup=admin_back_keyboard())


@router.callback_query(F.data == "admin:channels")
async def admin_channels_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
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
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    day = _today()
    total, top = get_day_stats(day)
    lines = [f"Bugungi ko'rishlar: {total}"]
    if top:
        lines.append("Top kino kodlari:")
        lines.extend([f"{code} - {count}" for code, count in top])
    recent = get_recent_days()
    if recent:
        lines.append("So'nggi kunlar:")
        lines.extend([f"{d}: {c}" for d, c in recent])
    await callback.message.edit_text("\n".join(lines), reply_markup=admin_back_keyboard())


@router.callback_query(F.data == "admin:users")
async def admin_users_callback(callback: CallbackQuery):
    await _render_users_page(callback, page=0)


@router.callback_query(F.data.startswith("admin:users:"))
async def admin_users_page_callback(callback: CallbackQuery):
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
    if not is_admin(callback.from_user.id):
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
    body = "\n".join(str(user_id) for user_id in page_users)
    text = f"{header}\n{body}"
    await callback.message.edit_text(
        text,
        reply_markup=users_keyboard(page, total_pages),
    )


@router.callback_query(F.data == "admin:logs")
async def admin_logs_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    LOG_QUERY_ADMINS.add(callback.from_user.id)
    await callback.message.edit_text(
        "Foydalanuvchi ID yoki @username yuboring.",
        reply_markup=log_cancel_keyboard(),
    )


@router.callback_query(F.data == "admin:help")
async def admin_help_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    text = (
        "Admin buyruqlar:\n"
        "/addadmin <user_id>\n"
        "/deladmin <user_id>\n"
        "/addchannel <@username|chat_id> [invite_link]\n"
        "/delchannel <@username|chat_id>\n"
        "/addmovie [code] (reply)\n"
        "/addserial (inline)\n"
        "/addpart <serial_nomi|kod>\n"
        "/part <qism_raqami>\n"
        "/delmovie <code>\n"
        "Admin panel -> Loglar\n"
        "Admin panel -> Foydalanuvchilar\n"
        "/log <user_id|@username>\n"
        "/stats\n"
    )
    await callback.message.edit_text(text, reply_markup=admin_back_keyboard())


@router.callback_query(F.data == "admin:addadmin")
async def admin_addadmin_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    await callback.message.edit_text(
        "Foydalanish: /addadmin <user_id>",
        reply_markup=admin_back_keyboard(),
    )


@router.callback_query(F.data == "admin:deladmin")
async def admin_deladmin_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    await callback.message.edit_text(
        "Foydalanish: /deladmin <user_id>",
        reply_markup=admin_back_keyboard(),
    )


@router.callback_query(F.data == "admin:addchannel")
async def admin_addchannel_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    await callback.message.edit_text(
        "Foydalanish: /addchannel <@username|chat_id> [invite_link]",
        reply_markup=admin_back_keyboard(),
    )


@router.callback_query(F.data == "admin:delchannel")
async def admin_delchannel_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
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
        "Reply qiling va yuboring: /addmovie [code]",
        reply_markup=admin_back_keyboard(),
    )


@router.callback_query(F.data == "admin:addserial")
async def admin_addserial_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    save_serial_session(
        callback.from_user.id,
        state="await_title",
        created_at=_now(),
    )
    await callback.message.edit_text(
        "Serial nomini yuboring.",
        reply_markup=serial_cancel_keyboard(),
    )


@router.callback_query(F.data == "admin:addpart")
async def admin_addpart_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
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
        "Foydalanish: /delmovie <code>",
        reply_markup=admin_back_keyboard(),
    )


@router.callback_query(F.data == "admin:broadcast")
async def admin_broadcast_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    await callback.message.edit_text(
        "Foydalanish: /broadcast <text> yoki reply bilan yuboring.",
        reply_markup=admin_back_keyboard(),
    )


@router.message(Command("addchannel"))
async def add_channel_handler(message: Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        await message.answer("Bu buyruq faqat adminlar uchun.")
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
    await message.answer("Kanal qo'shildi.")


@router.message(Command("delchannel"))
async def del_channel_handler(message: Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        await message.answer("Bu buyruq faqat adminlar uchun.")
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
    await message.answer("Kanal chiqarildi.")


@router.message(Command("channels"))
async def list_channels_handler(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Bu buyruq faqat adminlar uchun.")
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


@router.message(Command("addmovie"))
async def add_movie_handler(message: Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        await message.answer("Bu buyruq faqat adminlar uchun.")
        return
    if not SOURCE_CHANNEL_ID:
        await message.answer("SOURCE_CHANNEL_ID sozlanmagan.")
        return
    if command.args:
        code = _parse_code(command.args)
        if not code:
            await message.answer("Kod faqat raqam bo'lishi kerak.")
            return
    else:
        code = _generate_code()

    if not message.reply_to_message:
        await message.answer("Video/document ustidan reply qiling.")
        return

    if count_movies_for_code(code) >= MAX_MOVIES_PER_CODE:
        await message.answer("Bu kod band.")
        return

    reply = message.reply_to_message
    file_id, file_type, caption = _extract_media(reply)

    if not file_id:
        await message.answer("Faqat video yoki document qabul qilinadi.")
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
    add_movie(
        code,
        file_id,
        file_type,
        caption or "",
        source_chat_id=msg.chat.id,
        source_message_id=msg.message_id,
    )
    await message.answer(f"Kino saqlandi. Kod: {code}")


@router.message(Command("addpart"))
async def add_part_handler(message: Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        await message.answer("Bu buyruq faqat adminlar uchun.")
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


@router.message(Command("part"))
async def set_part_handler(message: Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        await message.answer("Bu buyruq faqat adminlar uchun.")
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


@router.message(Command("delmovie"))
async def del_movie_handler(message: Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        await message.answer("Bu buyruq faqat adminlar uchun.")
        return
    if not command.args:
        await message.answer("Foydalanish: /delmovie <code>")
        return
    code = _parse_code(command.args)
    if not code:
        await message.answer("Kod faqat raqam bo'lishi kerak.")
        return
    del_movie(code)
    await message.answer("Kino o'chirildi.")


@router.message(F.text & ~F.text.startswith("/"))
async def admin_log_text_handler(message: Message):
    if not is_admin(message.from_user.id):
        return
    if message.from_user.id not in LOG_QUERY_ADMINS:
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
    session = get_serial_session(message.from_user.id)
    if not session or session.get("state") != "await_part":
        return
    serial_id = session.get("serial_id")
    if not serial_id:
        await message.answer("Serial topilmadi. /addserial yoki /addpart ishlating.")
        return
    part = session.get("next_part") or 1
    if serial_part_exists(serial_id, part):
        await message.answer("Bu qism allaqachon mavjud. /part <raqam> bilan tanlang.")
        return
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


async def _send_movie(message: Message, code: str) -> bool:
    items = get_movie_items(code)
    if not items:
        return False
    progress = None
    if len(items) > 1:
        progress = await message.answer(f"Yuborilmoqda: 0/{len(items)}")
    for idx, item in enumerate(items, start=1):
        caption = item.get("caption") or None
        source_chat_id = item.get("source_chat_id")
        source_message_id = item.get("source_message_id")
        if source_chat_id and source_message_id:
            await _safe_copy_message(
                message.bot,
                message.chat.id,
                source_chat_id,
                source_message_id,
            )
        elif item.get("file_type") == "document":
            await _safe_send_document(message, item["file_id"], caption)
        else:
            await _safe_send_video(message, item["file_id"], caption)
        await asyncio.sleep(SEND_DELAY_SECONDS)
        if progress:
            try:
                await progress.edit_text(f"Yuborilmoqda: {idx}/{len(items)}")
            except Exception:
                pass
    record_view(_today(), str(code))
    _log_event("movie_sent", message.from_user.id, f"code={code}")
    if progress:
        try:
            await progress.edit_text("Yuborildi.")
        except Exception:
            pass
    return True


async def _show_serial_parts(message: Message, serial_id: int, title: str) -> bool:
    parts = get_serial_parts(serial_id)
    if not parts:
        return False
    part_numbers = [int(item["part"]) for item in parts if item.get("part") is not None]
    if not part_numbers:
        return False
    await message.answer(
        f"{title} qismlari:",
        reply_markup=serial_parts_keyboard(
            serial_id,
            part_numbers,
            page=0,
            per_page=SERIAL_PARTS_PER_PAGE,
        ),
    )
    return True


async def _send_serial_part(message: Message, serial_id: int, part: int) -> bool:
    item = get_serial_part(serial_id, part)
    if not item:
        return False
    caption = item.get("caption") or None
    source_chat_id = item.get("source_chat_id")
    source_message_id = item.get("source_message_id")
    if source_chat_id and source_message_id:
        await _safe_copy_message(
            message.bot,
            message.chat.id,
            source_chat_id,
            source_message_id,
        )
    elif item.get("file_type") == "document":
        await _safe_send_document(message, item["file_id"], caption)
    else:
        await _safe_send_video(message, item["file_id"], caption)
    return True


@router.message(Command("movie"))
async def movie_command_handler(message: Message, command: CommandObject):
    if not await ensure_subscribed(message):
        return
    if not command.args:
        await message.answer("Foydalanish: /movie <code>")
        return
    code = _parse_code(command.args)
    if not code:
        await message.answer("Kod faqat raqam bo'lishi kerak.")
        return
    if not await _send_movie(message, code):
        await message.answer("Kino topilmadi.")


@router.message(Command("serial"))
async def serial_command_handler(message: Message, command: CommandObject):
    if not await ensure_subscribed(message):
        return
    if not command.args:
        await message.answer("Foydalanish: /serial <nom|kod>")
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
    if not await _show_serial_parts(message, serial["id"], serial["title"]):
        await message.answer("Serialda qismlar yo'q.")


@router.message(F.text & ~F.text.startswith("/"))
async def movie_text_handler(message: Message):
    if not await ensure_subscribed(message):
        return
    if is_admin(message.from_user.id) and get_serial_session(message.from_user.id):
        return
    raw = message.text.strip()
    if raw == "Kino kodini yuborish":
        await message.answer("Kino kodini yuboring.")
        return
    code = _parse_code(raw)
    if code:
        if await _send_movie(message, code):
            return
        serial = get_serial_by_code(int(code))
        if serial and await _show_serial_parts(message, serial["id"], serial["title"]):
            return
        await message.answer("Kino yoki serial topilmadi.")
        return
    serial = get_serial_by_title(raw)
    if serial and await _show_serial_parts(message, serial["id"], serial["title"]):
        return
    await message.answer("Kino yoki serial topilmadi.")


@router.message(Command("stats"))
async def stats_handler(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Bu buyruq faqat adminlar uchun.")
        return
    day = _today()
    total, top = get_day_stats(day)
    lines = [f"Bugungi ko'rishlar: {total}"]
    if top:
        lines.append("Top kino kodlari:")
        lines.extend([f"{code} - {count}" for code, count in top])
    recent = get_recent_days()
    if recent:
        lines.append("So'nggi kunlar:")
        lines.extend([f"{d}: {c}" for d, c in recent])
    await message.answer("\n".join(lines))


@router.message(Command("log"))
async def log_handler(message: Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        await message.answer("Bu buyruq faqat adminlar uchun.")
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
    for user_id in get_users():
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
    if not is_admin(message.from_user.id):
        await message.answer("Bu buyruq faqat adminlar uchun.")
        return
    if not command.args and not message.reply_to_message:
        await message.answer("Foydalanish: /broadcast <text> yoki reply bilan yuboring.")
        return
    text = command.args.strip() if command.args else None
    ok, failed = await _broadcast_to_users(message, text)
    await message.answer(f"Yuborildi: {ok}, xatolik: {failed}")
