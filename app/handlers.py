import datetime as dt
import random

from typing import Optional

from aiogram import F, Router
from aiogram.enums import ChatMemberStatus
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from app.config import OWNER_ID, SOURCE_CHANNEL_ID
from app.db import (
    add_admin,
    add_channel,
    add_movie,
    add_user,
    del_admin,
    del_channel,
    del_movie,
    get_admins,
    get_channels,
    get_day_stats,
    get_movie,
    get_recent_days,
    is_admin,
    get_users,
    movie_exists,
    record_view,
)
from app.keyboards import (
    admin_back_keyboard,
    admin_panel_keyboard,
    main_keyboard,
    subscribe_keyboard,
)

router = Router()


async def _check_subscriptions(bot, user_id: int, channels: list) -> bool:
    for channel in channels:
        chat_id = int(channel["chat_id"])
        try:
            member = await bot.get_chat_member(chat_id, user_id)
        except Exception:
            return False
        if member.status in {ChatMemberStatus.LEFT, ChatMemberStatus.KICKED}:
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


def _today() -> str:
    return dt.datetime.utcnow().date().isoformat()


def _generate_code() -> str:
    for _ in range(20):
        code = f"{random.randint(0, 999999):06d}"
        if not movie_exists(code):
            return code
    return f"{random.randint(0, 999999):06d}"


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
    await message.answer(banner, reply_markup=main_keyboard())


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
        "/addchannel <@username> - majburiy kanal qo'shish\n"
        "/delchannel <@username> - kanalni chiqarish\n"
        "/channels - kanallar ro'yxati\n"
        "/addmovie [code] - video/document ustidan reply\n"
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
            f"{item.get('title')} (@{item.get('username')})" for item in channels
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
        "/addchannel <@username>\n"
        "/delchannel <@username>\n"
        "/addmovie [code] (reply)\n"
        "/delmovie <code>\n"
        "/stats\n"
    )
    await callback.message.edit_text(text, reply_markup=admin_back_keyboard())


@router.message(Command("addchannel"))
async def add_channel_handler(message: Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        await message.answer("Bu buyruq faqat adminlar uchun.")
        return
    if not command.args:
        await message.answer("Foydalanish: /addchannel <@username>")
        return
    target = command.args.strip()
    try:
        chat = await message.bot.get_chat(target)
    except Exception:
        await message.answer("Kanal topilmadi.")
        return
    if not chat.username:
        await message.answer("Kanalda username bo'lishi kerak.")
        return
    add_channel(chat.id, chat.username, chat.title or chat.username)
    await message.answer("Kanal qo'shildi.")


@router.message(Command("delchannel"))
async def del_channel_handler(message: Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        await message.answer("Bu buyruq faqat adminlar uchun.")
        return
    if not command.args:
        await message.answer("Foydalanish: /delchannel <@username>")
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
        f"{item.get('title')} (@{item.get('username')})" for item in channels
    )
    await message.answer(text)


@router.message(Command("addmovie"))
async def add_movie_handler(message: Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        await message.answer("Bu buyruq faqat adminlar uchun.")
        return
    if not message.reply_to_message:
        await message.answer("Video/document ustidan reply qiling.")
        return

    reply = message.reply_to_message
    if SOURCE_CHANNEL_ID:
        source_ok = False
        if reply.forward_from_chat and reply.forward_from_chat.id == SOURCE_CHANNEL_ID:
            source_ok = True
        if reply.sender_chat and reply.sender_chat.id == SOURCE_CHANNEL_ID:
            source_ok = True
        if not source_ok:
            await message.answer("Bu video ruxsat etilgan kanaldan emas.")
            return

    file_id = None
    file_type = None
    caption = reply.caption
    if reply.video:
        file_id = reply.video.file_id
        file_type = "video"
    elif reply.document:
        file_id = reply.document.file_id
        file_type = "document"

    if not file_id:
        await message.answer("Faqat video yoki document qabul qilinadi.")
        return

    if command.args:
        code = command.args.strip()
        if movie_exists(code):
            await message.answer("Bu kod band. Boshqa kod kiriting.")
            return
    else:
        code = _generate_code()
    add_movie(code, file_id, file_type, caption or "")
    await message.answer(f"Kino saqlandi. Kod: {code}")


@router.message(Command("delmovie"))
async def del_movie_handler(message: Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        await message.answer("Bu buyruq faqat adminlar uchun.")
        return
    if not command.args:
        await message.answer("Foydalanish: /delmovie <code>")
        return
    code = command.args.strip()
    del_movie(code)
    await message.answer("Kino o'chirildi.")


async def _send_movie(message: Message, code: str) -> bool:
    movie = get_movie(code)
    if not movie:
        return False
    caption = movie.get("caption") or None
    if movie.get("file_type") == "document":
        await message.answer_document(movie["file_id"], caption=caption)
    else:
        await message.answer_video(movie["file_id"], caption=caption)
    record_view(_today(), code)
    return True


@router.message(Command("movie"))
async def movie_command_handler(message: Message, command: CommandObject):
    if not await ensure_subscribed(message):
        return
    if not command.args:
        await message.answer("Foydalanish: /movie <code>")
        return
    code = command.args.strip()
    if not await _send_movie(message, code):
        await message.answer("Kino topilmadi.")


@router.message(F.text & ~F.text.startswith("/"))
async def movie_text_handler(message: Message):
    if not await ensure_subscribed(message):
        return
    code = message.text.strip()
    if code == "Kino kodini yuborish":
        await message.answer("Kino kodini yuboring.")
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
