import os
import asyncio
import logging
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

import config
from clients import build_clients

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


async def handle_health(request):
    return web.Response(text="Bot is alive!")


# --- Entrypoint ---
# IMPORTANT: assistant/call_py are built INSIDE main(), after asyncio.run()
# has already created the real running loop — not at module import time.
# Pyrogram's Client.__init__ caches whatever event loop is "current" the
# moment it's constructed; building it too early binds it to a throwaway
# loop instead of the one that actually runs everything, which is exactly
# what caused the "attached to a different loop" errors. on_startup/
# on_shutdown are defined here too (as closures) so they can reference
# these same objects without relying on module-level globals.
async def main():
    assistant, call_py = build_clients()

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

    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
