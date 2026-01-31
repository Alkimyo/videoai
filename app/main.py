import asyncio

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from app.config import BOT_TOKEN, WEBHOOK_PATH, WEBHOOK_URL, WEBAPP_HOST, WEBAPP_PORT
from app.db import ensure_owner, init_db
from app.handlers import router


def _health(_: web.Request) -> web.Response:
    return web.Response(text="ok")


async def on_startup(bot: Bot) -> None:
    init_db()
    ensure_owner()
    if WEBHOOK_URL:
        await bot.set_webhook(
            f"{WEBHOOK_URL}{WEBHOOK_PATH}",
            drop_pending_updates=True,
        )


async def on_shutdown(bot: Bot) -> None:
    if WEBHOOK_URL:
        await bot.delete_webhook()


def run_webhook(bot: Bot, dp: Dispatcher) -> None:
    app = web.Application()
    SimpleRequestHandler(dp, bot).register(app, path=WEBHOOK_PATH)
    app.router.add_get("/health", _health)
    setup_application(app, dp, bot=bot)
    web.run_app(app, host=WEBAPP_HOST, port=WEBAPP_PORT)


def run_polling(bot: Bot, dp: Dispatcher) -> None:
    asyncio.run(dp.start_polling(bot))


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is required")

    bot = Bot(BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    if WEBHOOK_URL:
        run_webhook(bot, dp)
    else:
        run_polling(bot, dp)


if __name__ == "__main__":
    main()
