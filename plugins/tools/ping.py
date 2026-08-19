import time
import logging
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

log = logging.getLogger("bot")
router = Router()


@router.message(Command("ping"))
async def ping_cmd(message: Message):
    log.info(f"[PING] Handler triggered by user {message.from_user.id if message.from_user else 'unknown'}")
    try:
        start_time = time.time()
        sent_msg = await message.reply("Pinging...")
        end_time = time.time()

        latency = round((end_time - start_time) * 1000)
        await sent_msg.edit_text(f"🏓 *Pong!* `{latency}ms`")
        log.info("[PING] Reply sent successfully")
    except Exception as e:
        log.error(f"[PING] Handler raised an exception: {e}")
