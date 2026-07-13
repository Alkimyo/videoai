from typing import Iterable, Optional

from aiogram.types import InlineKeyboardButton, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def _pretty_title(title: str) -> str:
    clean = (title or "").strip()
    if not clean:
        return "🎬 DRAMA 🎬"
    return f"🎬 {clean.upper()} 🎬"


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
    kb.button(text="Dramalar", callback_data="admin:serials")
    kb.button(text="Admin qo'shish", callback_data="admin:addadmin")
    kb.button(text="Admin tahrirlash", callback_data="admin:editadmin")
    kb.button(text="Admin o'chirish", callback_data="admin:deladmin")
    kb.button(text="Kanal qo'shish", callback_data="admin:addchannel")
    kb.button(text="Kanal o'chirish", callback_data="admin:delchannel")
    kb.button(text="Drama qo'shish", callback_data="admin:addserial")
    kb.button(text="Qism qo'shish", callback_data="admin:addpart")
    kb.button(text="Drama o'chirish", callback_data="admin:delserial")
    kb.button(text="Qism o'chirish", callback_data="admin:delpart")
    kb.button(text="VIPlar", callback_data="admin:viplist")
    kb.button(text="VIP narx", callback_data="admin:vipprice")
    kb.button(text="VIP xabar", callback_data="admin:vipmsg")
    kb.button(text="VIP rekvizit", callback_data="admin:vipcard")
    kb.button(text="E'lon yuborish", callback_data="admin:broadcast")
    kb.button(text="Loglar", callback_data="admin:logs")
    kb.button(text="Log fayli", callback_data="admin:logfile")
    kb.button(text="Foydalanuvchilar", callback_data="admin:users")
    kb.button(text="Statistika", callback_data="admin:stats")
    kb.button(text="Backup", callback_data="admin:backup")
    kb.button(text="Yordam", callback_data="admin:help")
    kb.adjust(2)
    return kb.as_markup()


def admin_back_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="Ortga", callback_data="admin:back")
    return kb.as_markup()


def admin_permissions_keyboard(permissions: dict[str, int], labels: dict[str, str]):
    kb = InlineKeyboardBuilder()
    for key, value in permissions.items():
        icon = "✅" if value else "❌"
        label = labels.get(key, key)
        kb.button(text=f"{icon} {label}", callback_data=f"perm:toggle:{key}")
    kb.button(text="Saqlash", callback_data="perm:save")
    kb.button(text="Bekor qilish", callback_data="perm:cancel")
    kb.adjust(1)
    return kb.as_markup()


def admin_edit_list_keyboard(admins: Iterable[dict], page: int, total_pages: int):
    kb = InlineKeyboardBuilder()
    for item in admins:
        label = item.get("label") or str(item.get("user_id"))
        kb.button(text=label, callback_data=f"admin:edit:{item.get('user_id')}")
    kb.adjust(1)
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="<", callback_data=f"admin:editadmin:{page - 1}"))
    nav_buttons.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
    if page + 1 < total_pages:
        nav_buttons.append(InlineKeyboardButton(text=">", callback_data=f"admin:editadmin:{page + 1}"))
    if nav_buttons:
        kb.row(*nav_buttons)
    kb.row(InlineKeyboardButton(text="Ortga", callback_data="admin:back"))
    return kb.as_markup()


def user_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="Dramalar ro'yxati", callback_data="user:serials")
    kb.button(text="Drama qidirish", callback_data="user:search")
    kb.button(text="Admin bilan bog'lanish", callback_data="user:contact")
    kb.button(text="VIP haqida", callback_data="user:vipinfo")
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


def log_cancel_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="Bekor qilish", callback_data="log:cancel")
    return kb.as_markup()


def serial_parts_keyboard(
    serial_id: int,
    parts: Iterable[int],
    page: int,
    per_page: int,
    vip_parts: Optional[set[int]] = None,
    share_link: Optional[str] = None,
    part_link_prefix: Optional[str] = None,
    show_rating: bool = True,
    notify_enabled: bool = True,
    rating: int = 0,
    likes_count: int = 0,
    dislikes_count: int = 0,
):
    kb = InlineKeyboardBuilder()
    parts_list = list(parts)
    start = page * per_page
    end = start + per_page
    page_parts = parts_list[start:end]
    vip_parts = vip_parts or set()
    for part in page_parts:
        label = f"{part} 💎" if int(part) in vip_parts else str(part)
        if part_link_prefix:
            kb.button(text=label, url=f"{part_link_prefix}{part}")
        else:
            kb.button(
                text=label,
                callback_data=f"serialpart:{serial_id}:{part}",
            )
    kb.adjust(5)
    nav_buttons = []
    if len(parts_list) > per_page:
       

        if page > 0:
            if part_link_prefix:
                nav_buttons.append(
                    InlineKeyboardButton(
                        text="<",
                        url=f"{part_link_prefix}1",
                    )
                    )
            else:
                nav_buttons.append(
                    InlineKeyboardButton(
                        text="<",
                        callback_data=f"serialpage:{serial_id}:{page - 1}",
                    )
                )

        nav_buttons.append(
            InlineKeyboardButton(
                text=f"{page + 1}",
                callback_data="noop"
            )
        )

        if end < len(parts_list):
            if part_link_prefix:
                nav_buttons.append(
                    InlineKeyboardButton(
                        text=">",
                        url=f"{part_link_prefix}1",
                    )
                )
            else:
                nav_buttons.append(
                    InlineKeyboardButton(
                        text=">",
                        callback_data=f"serialpage:{serial_id}:{page + 1}",
                    )
                )

    if nav_buttons:
        kb.row(*nav_buttons)
    if show_rating:
        if likes_count < 0:
            likes_count = 0
        if likes_count < 0:
            likes_count = 0
        if dislikes_count < 0:
            dislikes_count = 0
        like_label = "👍✅" if rating == 1 else "👍"
        dislike_label = "👎✅" if rating == -1 else "👎"
        notify_label = "🔔" if notify_enabled else "🔕"
        kb.row(
            InlineKeyboardButton(
                text=f"{like_label} {likes_count}",
                callback_data=f"user:rate:1:{serial_id}",
            ),
            InlineKeyboardButton(
                text=notify_label,
                callback_data=f"serialnotify:toggle:{serial_id}:{page}",
            ),
            InlineKeyboardButton(
                text=f"{dislike_label} {dislikes_count}",
                callback_data=f"user:rate:-1:{serial_id}",
            ),
        )
        kb.row(
            InlineKeyboardButton(
                text="Nima uchun kerak?",
                callback_data=f"serialnotify:info:{serial_id}",
            )
        )
    if share_link:
        kb.row(InlineKeyboardButton(text="Ulashish", url=share_link))
    return kb.as_markup()


def serial_nav_keyboard(
    serial_id: int,
    parts: Iterable[int],
    current_part: int,
    part_link_prefix: Optional[str] = None,
    show_rating: bool = True,
    notify_enabled: bool = True,
    rating: int = 0,
    likes_count: int = 0,
    dislikes_count: int = 0,
):
    kb = InlineKeyboardBuilder()
    parts_sorted = sorted({int(p) for p in parts})
    prev_part = None
    next_part = None
    try:
        idx = parts_sorted.index(int(current_part))
    except ValueError:
        idx = -1
    if idx > 0:
        prev_part = parts_sorted[idx - 1]
    if idx >= 0 and idx + 1 < len(parts_sorted):
        next_part = parts_sorted[idx + 1]
    nav_buttons: list[InlineKeyboardButton] = []
    if prev_part is not None:
        if part_link_prefix:
            nav_buttons.append(
                InlineKeyboardButton(text="⬅️ Oldingi", url=f"{part_link_prefix}{prev_part}")
            )
        else:
            nav_buttons.append(
                InlineKeyboardButton(
                    text="⬅️ Oldingi",
                    callback_data=f"serialpart:{serial_id}:{prev_part}",
                )
            )
    if next_part is not None:
        if part_link_prefix:
            nav_buttons.append(
                InlineKeyboardButton(text="➡️ Keyingi", url=f"{part_link_prefix}{next_part}")
            )
        else:
            nav_buttons.append(
                InlineKeyboardButton(
                    text="➡️ Keyingi",
                    callback_data=f"serialpart:{serial_id}:{next_part}",
                )
            )
    if nav_buttons:
        kb.row(*nav_buttons)
    if show_rating:
        likes_count = max(0, int(likes_count or 0))
        dislikes_count = max(0, int(dislikes_count or 0))
        like_label = "👍✅" if rating == 1 else "👍"
        dislike_label = "👎✅" if rating == -1 else "👎"
        notify_label = "🔔" if notify_enabled else "🔕"
        kb.row(
            InlineKeyboardButton(
                text=f"{like_label} {likes_count}",
                callback_data=f"user:rate:1:{serial_id}:{int(current_part)}",
            ),
            InlineKeyboardButton(
                text=notify_label,
                callback_data="noop"
                if part_link_prefix
                else f"serialnotify:togglep:{serial_id}:{int(current_part)}",
            ),
            InlineKeyboardButton(
                text=f"{dislike_label} {dislikes_count}",
                callback_data=f"user:rate:-1:{serial_id}:{int(current_part)}",
            ),
        )
        kb.row(
            InlineKeyboardButton(
                text="Nima uchun kerak?",
                callback_data="noop" if part_link_prefix else f"serialnotify:info:{serial_id}",
            )
        )
    return kb.as_markup()


def users_keyboard(page: int, total_pages: int):
    kb = InlineKeyboardBuilder()
    if page > 0:
        kb.button(text="<", callback_data=f"admin:users:{page - 1}")
    kb.button(text=f"{page + 1}/{total_pages}", callback_data="noop")
    if page + 1 < total_pages:
        kb.button(text=">", callback_data=f"admin:users:{page + 1}")
    kb.adjust(3)
    kb.button(text="Ortga", callback_data="admin:back")
    return kb.as_markup()


def users_manage_keyboard(users: Iterable[dict], blocked_ids: set[int], page: int, total_pages: int):
    kb = InlineKeyboardBuilder()
    for user in users:
        user_id = int(user.get("user_id") or 0)
        label = f"@{user.get('username')}" if user.get("username") else str(user_id)
        is_blocked = user_id in blocked_ids
        action_text = "Blokdan chiqarish" if is_blocked else "Bloklash"
        action = "unblock" if is_blocked else "block"
        kb.row(
            InlineKeyboardButton(text=label, callback_data="noop"),
            InlineKeyboardButton(text="Xabar", callback_data=f"admin:user:msg:{user_id}:{page}"),
            InlineKeyboardButton(
                text=action_text,
                callback_data=f"admin:user:{action}:{user_id}:{page}",
            ),
        )
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="<", callback_data=f"admin:users:{page - 1}"))
    nav_buttons.append(
        InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop")
    )
    if page + 1 < total_pages:
        nav_buttons.append(InlineKeyboardButton(text=">", callback_data=f"admin:users:{page + 1}"))
    if nav_buttons:
        kb.row(*nav_buttons)
    kb.row(InlineKeyboardButton(text="Ortga", callback_data="admin:back"))
    return kb.as_markup()


def serials_list_keyboard(serials: Iterable[dict], page: int, total_pages: int):
    kb = InlineKeyboardBuilder()
    for item in serials:
        title = item.get("title") or ""
        short_title = title if len(title) <= 32 else f"{title[:29]}..."
        vip_mark = "⭐ " if item.get("is_vip") else ""
        text = f"{item.get('code')} - {vip_mark}{short_title}"
        kb.row(
            InlineKeyboardButton(
                text=text,
                callback_data=f"admin:serial:{item.get('id')}",
            ),
            InlineKeyboardButton(
                text="VIP" if not item.get("is_vip") else "Oddiy",
                callback_data=f"admin:serialvip:{item.get('id')}:{page}",
            ),
        )
    nav_buttons = []
    if page > 0:
        nav_buttons.append(
            InlineKeyboardButton(
                text="<",
                callback_data=f"admin:serials:{page - 1}",
            )
        )
    nav_buttons.append(
        InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop")
    )
    if page + 1 < total_pages:
        nav_buttons.append(
            InlineKeyboardButton(
                text=">",
                callback_data=f"admin:serials:{page + 1}",
            )
        )
    if nav_buttons:
        kb.row(*nav_buttons)
    kb.row(InlineKeyboardButton(text="Ortga", callback_data="admin:back"))
    return kb.as_markup()


def user_serials_keyboard(serials: Iterable[dict], page: int, total_pages: int, sort_key: str = "az"):
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="A-Z", callback_data=f"user:serials:az:0"),
        InlineKeyboardButton(text="Kod", callback_data=f"user:serials:code:0"),
        InlineKeyboardButton(text="Yangi", callback_data=f"user:serials:new:0"),
        InlineKeyboardButton(text="Top", callback_data=f"user:serials:top:0"),
    )
    for item in serials:
        title = item.get("title") or ""
        short_title = title if len(title) <= 28 else f"{title[:25]}..."
        text = _pretty_title(short_title)
        kb.button(text=text, callback_data=f"user:serial:{item.get('id')}")
    kb.adjust(2)
    nav_buttons = []
    if page > 0:
        nav_buttons.append(
            InlineKeyboardButton(
                text="<",
                callback_data=f"user:serials:{sort_key}:{page - 1}",
            )
        )
    nav_buttons.append(
        InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop")
    )
    if page + 1 < total_pages:
        nav_buttons.append(
            InlineKeyboardButton(
                text=">",
                callback_data=f"user:serials:{sort_key}:{page + 1}",
            )
        )
    if nav_buttons:
        kb.row(*nav_buttons)
    return kb.as_markup()


def user_search_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Bekor")]],
        resize_keyboard=True,
    )


def contact_admin_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Bekor")]],
        resize_keyboard=True,
    )


def user_serials_menu_keyboard(
    serials: Iterable[dict],
    page: int,
    total_pages: int,
):
    rows = []
    current_row = []
    current_len = 0
    max_row_len = 50
    for item in serials:
        title = item.get("title") or ""
        vip_mark = "⭐ " if item.get("is_vip") else ""
        label = _pretty_title(f"{vip_mark}{title.strip()}".strip())
        if not label:
            continue
        add_len = len(label) + (1 if current_row else 0)
        if current_row and current_len + add_len > max_row_len:
            rows.append(current_row)
            current_row = []
            current_len = 0
        current_row.append(KeyboardButton(text=label))
        current_len += add_len
    if current_row:
        rows.append(current_row)
    nav_row = []
    if page > 0:
        nav_row.append(KeyboardButton(text="⬅️ Oldingi"))
    if page + 1 < total_pages:
        nav_row.append(KeyboardButton(text="➡️ Keyingi"))
    if nav_row:
        rows.append(nav_row)
    rows.append([KeyboardButton(text="Ortga")])
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
    )


def user_search_results_keyboard(serials: Iterable[dict], page: int, total_pages: int):
    kb = InlineKeyboardBuilder()
    for item in serials:
        title = item.get("title") or ""
        short_title = title if len(title) <= 32 else f"{title[:29]}..."
        text = f"{item.get('code')} - {short_title}"
        kb.button(text=text, callback_data=f"user:searchserial:{item.get('id')}")
    kb.adjust(1)
    nav_buttons = []
    if page > 0:
        nav_buttons.append(
            InlineKeyboardButton(
                text="<",
                callback_data=f"user:searchpage:{page - 1}",
            )
        )
    nav_buttons.append(
        InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop")
    )
    if page + 1 < total_pages:
        nav_buttons.append(
            InlineKeyboardButton(
                text=">",
                callback_data=f"user:searchpage:{page + 1}",
            )
        )
    if nav_buttons:
        kb.row(*nav_buttons)
    return kb.as_markup()


def post_media_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="Bekor", callback_data="post:cancel")
    kb.adjust(1)
    return kb.as_markup()


def post_link_keyboard(link: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="Dramani ko'rish", url=link)
    kb.adjust(1)
    return kb.as_markup()




def post_channel_keyboard(channels: Iterable[dict]):
    kb = InlineKeyboardBuilder()
    for channel in channels:
        title = channel.get("title") or channel.get("username") or str(channel.get("chat_id"))
        kb.button(text=title, callback_data=f"post:channel:{channel.get('chat_id')}")
    kb.adjust(1)
    kb.button(text="Bekor", callback_data="post:cancel")
    return kb.as_markup()


def vip_duration_keyboard(user_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="1 oy", callback_data=f"vip:add:{user_id}:30")
    kb.button(text="3 oy", callback_data=f"vip:add:{user_id}:90")
    kb.button(text="6 oy", callback_data=f"vip:add:{user_id}:180")
    kb.button(text="Bekor", callback_data="vip:cancel")
    kb.adjust(2)
    return kb.as_markup()


def vip_list_keyboard(page: int, total_pages: int):
    kb = InlineKeyboardBuilder()
    if page > 0:
        kb.button(text="<", callback_data=f"admin:viplist:{page - 1}")
    kb.button(text=f"{page + 1}/{total_pages}", callback_data="noop")
    if page + 1 < total_pages:
        kb.button(text=">", callback_data=f"admin:viplist:{page + 1}")
    kb.adjust(3)
    kb.row(InlineKeyboardButton(text="Ortga", callback_data="admin:back"))
    return kb.as_markup()


def vip_price_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="30 000", callback_data="vipprice:set:30000")
    kb.button(text="50 000", callback_data="vipprice:set:50000")
    kb.button(text="100 000", callback_data="vipprice:set:100000")
    kb.button(text="Boshqa narx", callback_data="vipprice:custom")
    kb.button(text="Bekor", callback_data="vipprice:cancel")
    kb.adjust(2)
    return kb.as_markup()


def vip_info_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="VIPga qo'shilish", callback_data="vipjoin:start")
    kb.button(text="Bekor", callback_data="vipjoin:cancel")
    kb.adjust(2)
    return kb.as_markup()


def broadcast_target_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="Hammaga", callback_data="broadcast:all")
    kb.button(text="VIP", callback_data="broadcast:vip")
    kb.button(text="Oddiy", callback_data="broadcast:regular")
    kb.button(text="Admin", callback_data="broadcast:admins")
    kb.button(text="Bekor", callback_data="broadcast:cancel")
    kb.adjust(2)
    return kb.as_markup()
