import datetime as dt
from typing import Optional

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import OWNER_ID
from app.db import (
    add_vip_user,
    count_vip_users,
    get_admin_permissions,
    get_admins,
    get_serial_by_code,
    get_serial_part,
    get_setting,
    get_users,
    get_vip_user,
    get_vip_users_page,
    has_admin_permission,
    is_admin,
    remove_vip_user,
    set_serial_part_vip,
    set_setting,
)
from app.handlers_sessions import (
    VIP_ADD_SESSIONS,
    VIP_CARD_SESSIONS,
    VIP_MESSAGE_SESSIONS,
    VIP_PAYMENT_SESSIONS,
    VIP_PRICE_SESSIONS,
    VIP_RECEIPT_APPROVED,
    VIP_RECEIPT_MESSAGES,
    VIP_RECEIPT_REJECTED,
    VIP_REJECT_SESSIONS,
)
from app.keyboards import (
    admin_back_keyboard,
    vip_duration_keyboard,
    vip_info_keyboard,
    vip_list_keyboard,
    vip_price_keyboard,
)


VIP_PRICE_KEY = "vip_monthly_price"
VIP_MESSAGE_KEY = "vip_message"
VIP_CARD_NUMBER_KEY = "vip_card_number"
VIP_CARD_OWNER_KEY = "vip_card_owner"

VIP_LISTS_PER_PAGE = 20

router = Router()


def get_vip_price() -> Optional[int]:
    raw = get_setting(VIP_PRICE_KEY)
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def get_vip_message() -> Optional[str]:
    return get_setting(VIP_MESSAGE_KEY)


def get_vip_card_details() -> tuple[str, str]:
    number = get_setting(VIP_CARD_NUMBER_KEY) or ""
    owner = get_setting(VIP_CARD_OWNER_KEY) or ""
    return number, owner


def vip_receipt_keyboard(user_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="Tasdiqlash", callback_data=f"vipreceipt:approve:{user_id}")
    kb.button(text="Rad etish", callback_data=f"vipreceipt:reject:{user_id}")
    kb.adjust(2)
    return kb.as_markup()


async def update_receipt_status(bot, user_id: int, text: str) -> None:
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


def is_vip_user(user_id: int) -> bool:
    info = get_vip_user(user_id)
    if not info:
        return False
    try:
        expires_at = dt.datetime.fromisoformat(info["expires_at"])
    except Exception:
        return False
    return expires_at > dt.datetime.utcnow()


def _is_admin_user(user_id: int) -> bool:
    if is_admin(user_id):
        return True
    perms = get_admin_permissions(user_id)
    return bool(perms)


async def send_vip_info(message: Message, user_id: int) -> None:
    info = get_vip_user(user_id)
    price = get_vip_price()
    if not info:
        text = "❌ Sizda faol VIP obuna mavjud emas."
        if price:
            text += f"\n\n💎 VIP TARIFLAR\n\n🥉 1 OYLIK VIP — {price} so'm\n\n🥈 3 OYLIK VIP — {3*price-11000} so'm\n💰 11 000 so'm tejaysiz.\n\n👑 6 OYLIK VIP — {6*price-41000} ⭐\n🔥 Eng foydali tarif!\n💰 41 000 so'm tejaysiz.\n\n"
        text += (
            
            "💎 VIP afzalliklari:\n\n"
            "✅ Yangi dramalarni hammadan oldin tomosha qilish.\n"
            "✅ Eksklyuziv VIP dramalarga kirish.\n"
            "✅ Bot tezroq va navbatsiz ishlaydi.\n"
            "✅ Doimiy texnik qo'llab-quvvatlash.\n"
            "✅ Yangi qo'shilayotgan dramalardan birinchi bo'lib foydalanish.\n\n"
            "📌 VIP obuna olish uchun:\n\n"
            "1️⃣ "VIPga qo'shilish" tugmasini bosing.\n"
            "2️⃣ Ko'rsatilgan karta raqamiga to'lovni amalga oshiring.\n"
            "3️⃣ To'lov chekini yuboring.\n"
            "4️⃣ Admin VIP obunangizni tez orada faollashtiradi. ✅"
        )
        await message.answer(text, reply_markup=vip_info_keyboard())
        return
    try:
        expires_at = dt.datetime.fromisoformat(info["expires_at"])
    except Exception:
        await message.answer("VIP holatini aniqlab bo'lmadi.")
        return
    days_left = max(0, (expires_at.date() - dt.datetime.utcnow().date()).days)
    text = f"Sizda VIP bor.\nTugash sanasi: {expires_at.date()}\nQolgan kun: {days_left}"
    await message.answer(text, reply_markup=vip_info_keyboard())


def include_vip_serials(user_id: int) -> bool:
    return is_admin(user_id) or is_vip_user(user_id)


def visible_serial_parts_for_user(user_id: int, serial_parts: list[dict]) -> list[dict]:
    if _is_admin_user(user_id) or is_vip_user(user_id):
        return serial_parts
    return [p for p in serial_parts if not int(p.get("is_vip") or 0)]


def _has_perm(user_id: int, perm: str) -> bool:
    return has_admin_permission(user_id, perm)


async def send_vip_required(message: Message, headline: str = "Bu bo'lim VIP.") -> None:
    custom = get_vip_message()
    price = get_vip_price()
    if custom and price:
        text = f"{headline}\n\n💎 VIP TARIFLAR\n\n🥉 1 OYLIK VIP — {price} so'm\n\n🥈 3 OYLIK VIP — {3*price-11000} so'm\n💰 11 000 so'm tejaysiz.\n\n👑 6 OYLIK VIP — {6*price-41000} ⭐\n🔥 Eng foydali tarif!\n💰 41 000 so'm tejaysiz.\n\n{custom}\n\nVIPga qo'shilish uchun pastdagi tugmani bosing."
        await message.answer(text, reply_markup=vip_info_keyboard())
        return
    text = (
        f"{headline}\n\n"
        f"Qo'shimcha ma'lumot uchun adminga yozing /contact\n\n"
        "VIPga qo'shilish uchun:\n"
        "1. Pastdagi VIPga qo'shilish tugmasini bosing.\n"
        "2. Ko'rsatilgan kartaga to'lov qiling.\n"
        "3. Chekni shu yerga yuboring."
    )
    await message.answer(text, reply_markup=vip_info_keyboard())


async def _render_vip_list(message: Message, page: int) -> None:
    total = count_vip_users()
    if total == 0:
        await message.answer("VIP foydalanuvchilar yo'q.")
        return
    total_pages = max(1, (total + VIP_LISTS_PER_PAGE - 1) // VIP_LISTS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * VIP_LISTS_PER_PAGE
    page_users = get_vip_users_page(VIP_LISTS_PER_PAGE, start)
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


@router.callback_query(F.data == "user:vipinfo")
async def user_vipinfo_callback(callback: CallbackQuery):
    await send_vip_info(callback.message, callback.from_user.id)


@router.callback_query(F.data.startswith("vipjoin:"))
async def vip_join_callback(callback: CallbackQuery):
    parts = callback.data.split(":")
    price = get_vip_price()
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
    number, owner = get_vip_card_details()
    if not number or not owner:
        await callback.message.edit_text("Rekvizitlar belgilanmagan. Admin bilan bog'laning.")
        return
    VIP_PAYMENT_SESSIONS.add(callback.from_user.id)
    text = (
        f"To'lov uchun karta: {number}\n"
        f"Karta egasi: {owner}\n"
        f"\n💎 VIP TARIFLAR\n\n"
        f"🥉 1 OYLIK VIP — {price} so'm\n\n"
        f"🥈 3 OYLIK VIP — {3*price-11000} so'm\n"
        f"💰 11 000 so'm tejaysiz.\n\n"
        f"👑 6 OYLIK VIP — {6*price-41000} ⭐\n"
        f"🔥 Eng foydali tarif!\n"
        f"💰 41 000 so'm tejaysiz.\n\n"
        "To'lov qilgandan so'ng chekni shu yerga yuboring."
    )
    await callback.message.edit_text(text)


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


@router.message(Command("vippart"))
async def vip_part_toggle_handler(message: Message, command: CommandObject):
    if not _has_perm(message.from_user.id, "can_manage_vip"):
        await message.answer("Bu buyruq uchun ruxsat yo'q.")
        return
    args = (command.args or "").split()
    if len(args) != 3:
        await message.answer("Foydalanish: /vippart <drama_kod> <qism> <on|off>")
        return
    code = args[0].strip()
    try:
        part = int(args[1])
    except ValueError:
        part = None
    flag = args[2].strip().lower()
    if not code.isdigit() or part is None:
        await message.answer("Kod va qism raqami raqam bo'lishi kerak.")
        return
    is_vip = 1 if flag in {"on", "1", "vip", "ha", "yes", "true"} else 0
    if flag not in {"on", "1", "vip", "ha", "yes", "true", "off", "0", "no", "yoq", "false"}:
        await message.answer("Uchinchi argument: on yoki off.")
        return
    serial = get_serial_by_code(int(code))
    if not serial:
        await message.answer("Drama topilmadi.")
        return
    item = get_serial_part(serial["id"], part)
    if not item:
        await message.answer("Qism topilmadi.")
        return
    set_serial_part_vip(serial["id"], part, is_vip)
    await message.answer("VIP qism belgilandi." if is_vip else "VIP qism o'chirildi.")


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
    price = get_vip_price()
    text = f"VIP oylik narx: {price} so'm" if price else "VIP oylik narx belgilanmagan."
    await message.answer(text)


@router.message(Command("vipmsg"))
async def vip_message_handler(message: Message):
    if not _has_perm(message.from_user.id, "can_manage_vip"):
        await message.answer("Bu buyruq uchun ruxsat yo'q.")
        return
    current = get_vip_message()
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
    number, owner = get_vip_card_details()
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
    price = get_vip_price()
    text = f"VIP oylik narx: {price} so'm" if price else "VIP oylik narx belgilanmagan."
    await callback.message.edit_text(text, reply_markup=vip_price_keyboard())


@router.callback_query(F.data == "admin:vipmsg")
async def admin_vipmsg_callback(callback: CallbackQuery):
    if not _has_perm(callback.from_user.id, "can_manage_vip"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    current = get_vip_message()
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
    number, owner = get_vip_card_details()
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
                await callback.answer("Bu chek allaqachon tasdiqlangan.", show_alert=True)
                return
        VIP_ADD_SESSIONS[callback.from_user.id] = user_id
        VIP_RECEIPT_APPROVED[user_id] = callback.from_user.id
        admin_label = (
            f"@{callback.from_user.username}"
            if callback.from_user.username
            else str(callback.from_user.id)
        )
        admins = [
            admin_id
            for admin_id in get_admins()
            if has_admin_permission(admin_id, "can_manage_vip")
        ]
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
        await update_receipt_status(
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
