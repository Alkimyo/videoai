import asyncio
import contextlib
import datetime as dt


from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.exceptions import TelegramForbiddenError
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeChat,
    BotCommandScopeDefault,
    CallbackQuery,
    Message,
)
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from app.config import (
    BOT_TOKEN,
    WEBAPP_ENABLED,
    WEBHOOK_PATH,
    WEBHOOK_URL,
    WEBAPP_HOST,
    WEBAPP_PORT,
)
from app.config import OWNER_ID
from app.db import (
    auto_restore_db_from_latest_backup,
    block_user,
    ensure_owner,
    get_admins,
    init_db,
    is_blocked_user,
    set_setting,
)
from app.handlers import (
    _log_event,
    router,
    vip_reminder_loop,
    backup_schedule_loop,
    cache_cleanup_loop,
    daily_recommendation_loop,
    daily_recommendation_prepare_loop,
)
from app.restore import auto_restore_latest_backup


def _safe_text(value: str | None, limit: int = 500) -> str:
    if not value:
        return ""
    text = value.strip()
    if len(text) > limit:
        return f"{text[:limit]}..."
    return text


class UserMessageLogMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: Message, data: dict):
        if event and event.from_user:
            set_setting("last_activity_at", dt.datetime.utcnow().isoformat())
            username = event.from_user.username or ""
            text = _safe_text(event.text or event.caption)
            detail = (
                f"chat_id={event.chat.id} chat_type={event.chat.type} "
                f"username={username} msg_type={event.content_type} "
                f"message_id={event.message_id} text={text}"
            )
            _log_event("user_message", event.from_user.id, detail)
        return await handler(event, data)


class UserCallbackLogMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: CallbackQuery, data: dict):
        if event and event.from_user:
            set_setting("last_activity_at", dt.datetime.utcnow().isoformat())
            username = event.from_user.username or ""
            data_text = _safe_text(event.data, limit=200)
            message_id = event.message.message_id if event.message else "-"
            detail = (
                f"chat_id={event.message.chat.id if event.message else '-'} "
                f"username={username} data={data_text} message_id={message_id}"
            )
            _log_event("user_action", event.from_user.id, detail)
        return await handler(event, data)


class BlockedUserMessageMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: Message, data: dict):
        if event and event.from_user and is_blocked_user(event.from_user.id):
            return
        return await handler(event, data)


class BlockedUserCallbackMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: CallbackQuery, data: dict):
        if event and event.from_user and is_blocked_user(event.from_user.id):
            return
        return await handler(event, data)


class TelegramForbiddenGuardMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data: dict):
        try:
            return await handler(event, data)
        except TelegramForbiddenError:
            user_id = getattr(getattr(event, "from_user", None), "id", None)
            if isinstance(user_id, int) and user_id > 0:
                block_user(user_id, dt.datetime.utcnow().isoformat())
                _log_event("bot_blocked", user_id, "forbidden_guard")
            return


class OverloadGuardMiddleware(BaseMiddleware):
    def __init__(self, capacity: int, heavy_capacity: int) -> None:
        self._capacity = capacity
        self._heavy_capacity = heavy_capacity
        self._semaphore = asyncio.Semaphore(capacity)
        self._heavy_semaphore = asyncio.Semaphore(heavy_capacity)

    @staticmethod
    def _is_heavy_message(event: Message) -> bool:
        text = (event.text or "").strip().lower()
        if not text.startswith("/"):
            return False
        cmd = text.split()[0].lstrip("/")
        return cmd in {"import", "broadcast", "reconow"}

    @staticmethod
    def _is_heavy_callback(event: CallbackQuery) -> bool:
        data = (event.data or "").lower()
        return data.startswith(("import:", "broadcast:", "newdrama:", "newpart:"))

    async def _respond_busy(self, event, delay_seconds: int) -> None:
        if isinstance(event, Message):
            await event.answer(
                "Hozircha so'rovlarga navbat bor. "
                "2 daqiqadan keyin yana urinib ko'ring. "
                "Agar baribir bo'lmasa 5 daqiqadan so'ng qayta yuboring."
            )
            return
        if isinstance(event, CallbackQuery):
            await event.answer(
                "Hozircha navbat bor. 2 daqiqadan keyin urinib ko'ring.",
                show_alert=True,
            )

    async def __call__(self, handler, event, data: dict):
        is_heavy = False
        if isinstance(event, Message):
            is_heavy = self._is_heavy_message(event)
        elif isinstance(event, CallbackQuery):
            is_heavy = self._is_heavy_callback(event)

        try:
            await asyncio.wait_for(self._semaphore.acquire(), timeout=120)
        except asyncio.TimeoutError:
            await self._respond_busy(event, 120)
            return

        heavy_acquired = False
        if is_heavy:
            try:
                await asyncio.wait_for(self._heavy_semaphore.acquire(), timeout=120)
                heavy_acquired = True
            except asyncio.TimeoutError:
                self._semaphore.release()
                await self._respond_busy(event, 120)
                return
        try:
            return await handler(event, data)
        finally:
            if heavy_acquired:
                self._heavy_semaphore.release()
            self._semaphore.release()


def _health(_: web.Request) -> web.Response:
    return web.Response(text="ok")


def _home(_: web.Request) -> web.Response:
    return web.Response(text="Ishlamoqda")


from aiogram import Bot

async def on_startup(bot: Bot) -> None:

    try:
        await auto_restore_latest_backup(bot)
    except Exception as e:
        print(e)

    init_db()
    ensure_owner()




async def set_bot_commands(bot: Bot) -> None:
    default_commands = [
        BotCommand(command="start", description="Botni ishga tushirish"),
        BotCommand(command="help", description="Yordam (yordam)"),
        BotCommand(command="contact", description="Adminlarga yozish"),
        BotCommand(command="serial", description="Drama yuborish"),
        BotCommand(command="search", description="Drama qidirish"),
        BotCommand(command="new", description="Yangi dramalar"),
        BotCommand(command="top", description="Top dramalar"),
        BotCommand(command="settings", description="Sozlamalar"),
        BotCommand(command="myvip", description="VIP holati"),
        BotCommand(command="drama", description="Drama yuborish (guruh)"),
    ]
    admin_commands = [
        BotCommand(command="start", description="Botni ishga tushirish"),
        BotCommand(command="help", description="Yordam (yordam)"),
        BotCommand(command="admin", description="Admin panel"),
        BotCommand(command="admins", description="Adminlar ro'yxati"),
        BotCommand(command="addadmin", description="Admin qo'shish"),
        BotCommand(command="deladmin", description="Admin chiqarish"),
        BotCommand(command="editadmin", description="Admin tahrirlash"),
        BotCommand(command="addchannel", description="Kanal qo'shish"),
        BotCommand(command="delchannel", description="Kanalni chiqarish"),
        BotCommand(command="channels", description="Kanallar ro'yxati"),
        BotCommand(command="addserial", description="Drama qo'shish"),
        BotCommand(command="serial", description="Drama yuborish"),
        BotCommand(command="drama", description="Drama yuborish (guruh)"),
        BotCommand(command="renameserial", description="Drama nomini o'zgartirish"),
        BotCommand(command="delserial", description="Drama o'chirish"),
        BotCommand(command="serialcancel", description="Drama qo'shishni bekor qilish"),
        BotCommand(command="addpart", description="Qism qo'shish"),
        BotCommand(command="delpart", description="Qism o'chirish"),
        BotCommand(command="part", description="Qism yuborish"),
        BotCommand(command="import", description="Drama import"),
        BotCommand(command="importcancel", description="Importni bekor qilish"),
        BotCommand(command="importstop", description="Importni to'xtatish"),
        BotCommand(command="post", description="Kanalga post"),
        BotCommand(command="broadcast", description="E'lon yuborish"),
        BotCommand(command="reconow", description="Tavsiya yuborish"),
        BotCommand(command="usend", description="Userbot bilan yuborish"),
        BotCommand(command="vip", description="VIP info"),
        BotCommand(command="addvip", description="VIP qo'shish"),
        BotCommand(command="delvip", description="VIP olib tashlash"),
        BotCommand(command="viplist", description="VIP ro'yxati"),
        BotCommand(command="vipprice", description="VIP narx"),
        BotCommand(command="setvipprice", description="VIP narx belgilash"),
        BotCommand(command="vipmsg", description="VIP xabarini o'zgartirish"),
        BotCommand(command="vipcard", description="VIP rekvizit"),
        BotCommand(command="stats", description="Statistika"),
        BotCommand(command="log", description="Log ko'rish"),
        BotCommand(command="logfile", description="Log fayli"),
        BotCommand(command="backup", description="Backup olish"),
        BotCommand(command="cleanup", description="Bo'sh dramalarni tozalash"),
        BotCommand(command="cancel", description="Bekor qilish"),
    ]
    group_commands = [
        BotCommand(command="start", description="Botni ishga tushirish"),
        BotCommand(command="help", description="Yordam (yordam)"),
        BotCommand(command="drama", description="Drama yuborish"),
        BotCommand(command="new", description="Yangi dramalar"),
        BotCommand(command="top", description="Top dramalar"),
    ]
    try:
        await bot.set_my_commands(default_commands, scope=BotCommandScopeDefault())
        await bot.set_my_commands(group_commands, scope=BotCommandScopeAllGroupChats())
        admin_ids = set(get_admins())
        if OWNER_ID:
            admin_ids.add(OWNER_ID)
        for admin_id in admin_ids:
            await bot.set_my_commands(
                admin_commands,
                scope=BotCommandScopeChat(chat_id=int(admin_id)),
            )
    except Exception:
        pass


def run_webapp(bot: Bot, dp: Dispatcher) -> None:
    app = web.Application()
    app.router.add_get("/", _home)
    app.router.add_get("/health", _health)
    if WEBHOOK_URL:
        SimpleRequestHandler(dp, bot).register(app, path=WEBHOOK_PATH)
        setup_application(app, dp, bot=bot)

        async def webhook_startup(_: web.Application) -> None:
            await bot.set_webhook(
                f"{WEBHOOK_URL}{WEBHOOK_PATH}",
                drop_pending_updates=True,
            )

        async def webhook_cleanup(_: web.Application) -> None:
            await bot.delete_webhook()

        app.on_startup.append(webhook_startup)
        app.on_cleanup.append(webhook_cleanup)
    else:

        async def polling_startup(_: web.Application) -> None:
            app["polling_task"] = asyncio.create_task(
                dp.start_polling(bot, handle_signals=False)
            )

        async def polling_cleanup(_: web.Application) -> None:
            task = app.get("polling_task")
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

        app.on_startup.append(polling_startup)
        app.on_cleanup.append(polling_cleanup)
    web.run_app(app, host=WEBAPP_HOST, port=WEBAPP_PORT)


def run_polling(bot: Bot, dp: Dispatcher) -> None:
    asyncio.run(dp.start_polling(bot))


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is required")

    bot = Bot(BOT_TOKEN)
    dp = Dispatcher()
    dp.message.middleware(TelegramForbiddenGuardMiddleware())
    dp.callback_query.middleware(TelegramForbiddenGuardMiddleware())
    dp.message.middleware(BlockedUserMessageMiddleware())
    dp.callback_query.middleware(BlockedUserCallbackMiddleware())
    dp.message.middleware(UserMessageLogMiddleware())
    dp.callback_query.middleware(UserCallbackLogMiddleware())
    dp.message.middleware(OverloadGuardMiddleware(capacity=3, heavy_capacity=1))
    dp.callback_query.middleware(OverloadGuardMiddleware(capacity=3, heavy_capacity=1))
    dp.include_router(router)
    dp.startup.register(on_startup)

    async def start_reminders(bot: Bot) -> None:
        dp["vip_task"] = asyncio.create_task(vip_reminder_loop(bot))
        dp["backup_task"] = asyncio.create_task(backup_schedule_loop(bot))
        dp["cache_task"] = asyncio.create_task(cache_cleanup_loop())
        # dp["reco_task"] = asyncio.create_task(daily_recommendation_loop(bot))
        # dp["reco_prepare_task"] = asyncio.create_task(
        #   daily_recommendation_prepare_loop(bot))

    dp.startup.register(start_reminders)
    dp.startup.register(set_bot_commands)

    if WEBAPP_ENABLED or WEBHOOK_URL:
        run_webapp(bot, dp)
    else:
        run_polling(bot, dp)


if __name__ == "__main__":
    main()
