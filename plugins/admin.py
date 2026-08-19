from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, ChatPermissions
from config import ADMIN_USERS

router = Router()


def _mention(user) -> str:
    name = getattr(user, "first_name", None) or getattr(user, "username", None) or str(user.id)
    return f'<a href="tg://user?id={user.id}">{name}</a>'


async def extract_target_user(message: Message, command: CommandObject):
    if message.reply_to_message:
        return message.reply_to_message.from_user

    if command.args:
        user_input = command.args.split()[0]
        try:
            if user_input.lstrip("-").isdigit():
                member = await message.bot.get_chat_member(message.chat.id, int(user_input))
                return member.user
            else:
                chat = await message.bot.get_chat(user_input)
                return chat
        except Exception:
            return None
    return None


@router.message(Command("ban"))
async def ban_user(message: Message, command: CommandObject):
    if message.from_user.id not in ADMIN_USERS:
        return
    target_user = await extract_target_user(message, command)
    if not target_user:
        await message.reply("Reply to a user's message or specify `@username` or id to ban.")
        return
    try:
        await message.bot.ban_chat_member(message.chat.id, target_user.id)
        await message.reply(f"*Banned* {_mention(target_user)}, hope to not see you again.", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"cannot be banned: {e}")


@router.message(Command("unban"))
async def unban_user(message: Message, command: CommandObject):
    if message.from_user.id not in ADMIN_USERS:
        return
    target_user = await extract_target_user(message, command)
    if not target_user:
        await message.reply("Reply to a message or specify `@username` / `user_id` to unban.")
        return
    try:
        await message.bot.unban_chat_member(message.chat.id, target_user.id)
        await message.reply(f"*Unbanned* {_mention(target_user)}. sigh", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"looks like god doesnt want to unban: {e}")


@router.message(Command("mute"))
async def mute_user(message: Message, command: CommandObject):
    if message.from_user.id not in ADMIN_USERS:
        return
    target_user = await extract_target_user(message, command)
    if not target_user:
        await message.reply("Reply to a message or specify `@username` / `user_id` to mute.")
        return
    try:
        await message.bot.restrict_chat_member(
            message.chat.id, target_user.id, permissions=ChatPermissions(can_send_messages=False)
        )
        await message.reply(f"*Muted* {_mention(target_user)}. lowly pest shut up", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"Failed to mute user: {e}")


@router.message(Command("unmute"))
async def unmute_user(message: Message, command: CommandObject):
    if message.from_user.id not in ADMIN_USERS:
        return
    target_user = await extract_target_user(message, command)
    if not target_user:
        await message.reply("Reply to a message or specify `@username` / `user_id` to unmute.")
        return
    try:
        await message.bot.restrict_chat_member(
            message.chat.id,
            target_user.id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_audios=True,
                can_send_documents=True,
                can_send_photos=True,
                can_send_videos=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
            ),
        )
        await message.reply(f"*Unmuted* {_mention(target_user)}. your free now", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"Failed to unmute user: {e}")


@router.message(Command("kick"))
async def kick_user(message: Message, command: CommandObject):
    if message.from_user.id not in ADMIN_USERS:
        return
    target_user = await extract_target_user(message, command)
    if not target_user:
        await message.reply("Reply to a message or specify `@username` / `user_id` to kick.")
        return
    try:
        await message.bot.ban_chat_member(message.chat.id, target_user.id)
        await message.bot.unban_chat_member(message.chat.id, target_user.id)
        await message.reply(f"*Kicked* {_mention(target_user)} from the chat. deserved", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"Failed to kick user: {e}")


@router.message(Command("promote"))
async def promote_admin(message: Message, command: CommandObject):
    if message.from_user.id not in ADMIN_USERS:
        return
    target_user = await extract_target_user(message, command)
    if not target_user:
        await message.reply("Reply to a message or specify `@username` / `user_id` to promote to admin.")
        return
    try:
        await message.bot.promote_chat_member(
            message.chat.id,
            target_user.id,
            can_change_info=True,
            can_delete_messages=True,
            can_restrict_members=True,
            can_invite_users=True,
            can_pin_messages=True,
            can_promote_members=True,
        )
        await message.reply(f"*Promoted* {_mention(target_user)} to group Admin!", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"Failed to promote user: {e}")


@router.message(Command("demote"))
async def demote_admin(message: Message, command: CommandObject):
    if message.from_user.id not in ADMIN_USERS:
        return
    target_user = await extract_target_user(message, command)
    if not target_user:
        await message.reply("Reply to a message or specify `@username` / `user_id` to demote.")
        return
    try:
        await message.bot.promote_chat_member(
            message.chat.id,
            target_user.id,
            can_change_info=False,
            can_post_messages=False,
            can_edit_messages=False,
            can_delete_messages=False,
            can_restrict_members=False,
            can_invite_users=False,
            can_pin_messages=False,
            can_promote_members=False,
            can_manage_video_chats=False,
        )
        await message.reply(f"*Demoted* {_mention(target_user)} to a regular member.", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"Failed to demote user: {e}")
