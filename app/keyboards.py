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
    kb.button(text="Add admin", callback_data="admin:addadmin")
    kb.button(text="Del admin", callback_data="admin:deladmin")
    kb.button(text="Add channel", callback_data="admin:addchannel")
    kb.button(text="Del channel", callback_data="admin:delchannel")
    kb.button(text="Add movie", callback_data="admin:addmovie")
    kb.button(text="Del movie", callback_data="admin:delmovie")
    kb.button(text="Broadcast", callback_data="admin:broadcast")
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
    kb.button(text="Kino kodini yuborish", callback_data="user:sendcode")
    kb.adjust(1)
    return kb.as_markup()
