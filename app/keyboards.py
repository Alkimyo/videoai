from typing import Iterable

from aiogram.types import KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder


def subscribe_keyboard(channels: Iterable[dict]):
    kb = InlineKeyboardBuilder()
    for channel in channels:
        username = channel.get("username")
        if not username:
            continue
        title = channel.get("title") or f"@{username}"
        kb.button(text=title, url=f"https://t.me/{username}")
    kb.button(text="Tekshirish", callback_data="check_subs")
    kb.adjust(1)
    return kb.as_markup()


def admin_panel_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="Adminlar", callback_data="admin:admins")
    kb.button(text="Kanallar", callback_data="admin:channels")
    kb.button(text="Statistika", callback_data="admin:stats")
    kb.button(text="Yordam", callback_data="admin:help")
    kb.adjust(2)
    return kb.as_markup()


def admin_back_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="Ortga", callback_data="admin:back")
    return kb.as_markup()


def main_keyboard():
    kb = ReplyKeyboardBuilder()
    kb.add(KeyboardButton(text="Kino kodini yuborish"))
    kb.adjust(1)
    return kb.as_markup(resize_keyboard=True, one_time_keyboard=False)
