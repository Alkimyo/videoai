from typing import Iterable

from aiogram.utils.keyboard import InlineKeyboardBuilder


def subscribe_keyboard(channels: Iterable[dict]):
    kb = InlineKeyboardBuilder()
    for channel in channels:
        username = channel.get("username")
        invite_link = channel.get("invite_link")
        if not username and not invite_link:
            continue
        title = channel.get("title") or f"@{username}"
        if invite_link:
            kb.button(text=title, url=invite_link)
        else:
            kb.button(text=title, url=f"https://t.me/{username}")
    kb.button(text="Tekshirish", callback_data="check_subs")
    kb.adjust(1)
    return kb.as_markup()


def admin_panel_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="Adminlar", callback_data="admin:admins")
    kb.button(text="Kanallar", callback_data="admin:channels")
    kb.button(text="Admin qo'shish", callback_data="admin:addadmin")
    kb.button(text="Admin o'chirish", callback_data="admin:deladmin")
    kb.button(text="Kanal qo'shish", callback_data="admin:addchannel")
    kb.button(text="Kanal o'chirish", callback_data="admin:delchannel")
    kb.button(text="Kino qo'shish", callback_data="admin:addmovie")
    kb.button(text="Kino o'chirish", callback_data="admin:delmovie")
    kb.button(text="Serial qo'shish", callback_data="admin:addserial")
    kb.button(text="Qism qo'shish", callback_data="admin:addpart")
    kb.button(text="E'lon yuborish", callback_data="admin:broadcast")
    kb.button(text="Statistika", callback_data="admin:stats")
    kb.button(text="Yordam", callback_data="admin:help")
    kb.adjust(2)
    return kb.as_markup()


def admin_back_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="Ortga", callback_data="admin:back")
    return kb.as_markup()


def user_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="Kod yuborish", callback_data="user:sendcode")
    kb.adjust(1)
    return kb.as_markup()


def serial_cancel_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="Bekor qilish", callback_data="serial:cancel")
    return kb.as_markup()


def serial_flow_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="Keyingi qism", callback_data="serial:continue")
    kb.button(text="Bekor qilish", callback_data="serial:cancel")
    kb.adjust(2)
    return kb.as_markup()
