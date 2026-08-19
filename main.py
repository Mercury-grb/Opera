import os
import asyncio
import logging
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

import config
from clients import assistant, call_py

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bot")

WEBHOOK_PATH = "/webhook"
# Render sets RENDER_EXTERNAL_URL automatically; fall back to your known URL.
PUBLIC_URL = os.environ.get("RENDER_EXTERNAL_URL", "https://opera-4vt5.onrender.com")

bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
dp = Dispatcher()

# --- Register plugin routers ---
from plugins.start import router as start_router
from plugins.admin import router as admin_router
from plugins.tools.ping import router as ping_router

dp.include_router(start_router)
dp.include_router(admin_router)
dp.include_router(ping_router)


async def on_startup(bot: Bot):
    webhook_url = f"{PUBLIC_URL}{WEBHOOK_PATH}"
    await bot.set_webhook(webhook_url, drop_pending_updates=True)
    log.info(f"[INFO] Webhook set to {webhook_url}")

    log.info("[INFO] Starting assistant client...")
    await assistant.start()
    log.info("[INFO] Starting PyTgCalls...")
    await call_py.start()
    assistant_info = await assistant.get_me()
    log.info(f"[INFO] Assistant online as @{assistant_info.username}")

    bot_info = await bot.get_me()
    log.info(f"[INFO] Bot online as @{bot_info.username}")


async def on_shutdown(bot: Bot):
    log.info("[INFO] Shutting down...")
    try:
        await bot.delete_webhook()
    except Exception as e:
        log.warning(f"[SHUTDOWN] Error deleting webhook: {e}")
    try:
        if assistant.is_connected:
            await assistant.stop()
    except Exception as e:
        log.warning(f"[SHUTDOWN] Error stopping assistant (likely harmless): {e}")
    log.info("[INFO] Shutdown complete.")


dp.startup.register(on_startup)
dp.shutdown.register(on_shutdown)


async def handle_health(request):
    return web.Response(text="Bot is alive!")


# --- Entrypoint ---
# IMPORTANT: we manage the event loop ourselves with a single asyncio.run()
# call at the bottom of this file, instead of using aiohttp's web.run_app()
# helper. web.run_app() manages its own event loop lifecycle internally,
# which is a DIFFERENT loop than whatever was active when `assistant =
# Client(...)` was constructed at import time in clients.py. That mismatch
# is exactly the "attached to a different loop" bug we've hit before with
# pyrogram — the fix is the same: one explicit, persistent loop for the
# whole process, set up manually with AppRunner/TCPSite instead of a
# high-level sync wrapper that hides its own loop creation.
async def main():
    app = web.Application()
    app.router.add_get("/", handle_health)

    webhook_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_handler.register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info(f"[INFO] Web app listening on port {port}")

    # Keep the process alive; aiogram's on_startup already ran via
    # setup_application's aiohttp on_startup hook, on this same loop.
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
