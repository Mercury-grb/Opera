from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
import config

router = Router()


@router.message(Command("start"), F.chat.type == "private")
async def start_command(message: Message):
    user = message.from_user
    await message.reply(f"Hello, {user.first_name}!")

    username_str = f"@{user.username}" if user.username else "No Username"
    log_text = (
        f"<b>New User Started Bot!</b>\n\n"
        f"<b>Name:</b> {user.first_name} {user.last_name or ''}\n"
        f"<b>Username:</b> {username_str}\n"
        f"<b>User ID:</b> <code>{user.id}</code>\n"
        f"<b>Mention:</b> {user.mention_html()}"
    )
    try:
        await message.bot.send_message(
            chat_id=config.LOG_CHANNEL_ID,
            text=log_text,
            parse_mode="HTML",
        )
    except Exception as e:
        print(f"[ERROR] Failed to send log: {e}")
