import asyncio
import contextlib

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.types import CallbackQuery, Message
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from app.config import (
    BOT_TOKEN,
    WEBAPP_ENABLED,
    WEBHOOK_PATH,
    WEBHOOK_URL,
    WEBAPP_HOST,
    WEBAPP_PORT,
)
from app.db import ensure_owner, init_db
from app.handlers import _log_event, router, vip_reminder_loop


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
            username = event.from_user.username or ""
            data_text = _safe_text(event.data, limit=200)
            message_id = event.message.message_id if event.message else "-"
            detail = (
                f"chat_id={event.message.chat.id if event.message else '-'} "
                f"username={username} data={data_text} message_id={message_id}"
            )
            _log_event("user_action", event.from_user.id, detail)
        return await handler(event, data)


def _health(_: web.Request) -> web.Response:
    return web.Response(text="ok")


def _home(_: web.Request) -> web.Response:
    return web.Response(text="Ishlamoqda")


async def on_startup(*_: object) -> None:
    init_db()
    ensure_owner()


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
    dp.message.middleware(UserMessageLogMiddleware())
    dp.callback_query.middleware(UserCallbackLogMiddleware())
    dp.include_router(router)
    dp.startup.register(on_startup)

    async def start_reminders(bot: Bot) -> None:
        dp["vip_task"] = asyncio.create_task(vip_reminder_loop(bot))

    dp.startup.register(start_reminders)

    if WEBAPP_ENABLED or WEBHOOK_URL:
        run_webapp(bot, dp)
    else:
        run_polling(bot, dp)


if __name__ == "__main__":
    main()
