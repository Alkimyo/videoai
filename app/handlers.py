import asyncio
import datetime as dt
from typing import Optional

from aiogram import F, Router
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, ChatJoinRequest, Message

from app.config import MAX_MOVIES_PER_CODE, OWNER_ID, SOURCE_CHANNEL_ID
from app.db import (
    add_admin,
    add_channel,
    add_movie,
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
    is_admin,
    get_users,
    has_join_request,
    record_view,
)
from app.keyboards import (
    admin_back_keyboard,
    admin_panel_keyboard,
    subscribe_keyboard,
    user_keyboard,
)

router = Router()
SEND_DELAY_SECONDS = 0.7


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


def _today() -> str:
    return dt.datetime.utcnow().date().isoformat()


def _generate_code() -> str:
    return str(get_next_code())


def _parse_code(raw: str) -> Optional[str]:
    value = raw.strip()
    if not value.isdigit():
        return None
    return str(int(value))


def _now() -> str:
    return dt.datetime.utcnow().isoformat()


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
    await callback.message.edit_text("Admin panel:", reply_markup=admin_panel_keyboard())


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
        "/delmovie <code>\n"
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
    if progress:
        try:
            await progress.edit_text("Yuborildi.")
        except Exception:
            pass
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


@router.message(F.text & ~F.text.startswith("/"))
async def movie_text_handler(message: Message):
    if not await ensure_subscribed(message):
        return
    raw = message.text.strip()
    if raw == "Kino kodini yuborish":
        await message.answer("Kino kodini yuboring.")
        return
    code = _parse_code(raw)
    if not code:
        await message.answer("Kino kodi faqat raqam bo'lishi kerak.")
        return
    if not await _send_movie(message, code):
        await message.answer("Kino topilmadi.")


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
