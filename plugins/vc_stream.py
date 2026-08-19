import logging
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from pytgcalls.types import MediaStream

import clients
from utils import stream_manager as sm

log = logging.getLogger("bot")
router = Router()


def _controls_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⏸ Pause", callback_data="vc:pause"),
                InlineKeyboardButton(text="▶️ Resume", callback_data="vc:resume"),
            ],
            [
                InlineKeyboardButton(text="🔁 Repeat", callback_data="vc:repeat"),
                InlineKeyboardButton(text="⏹ Stop", callback_data="vc:stop"),
            ],
        ]
    )


def _now_playing_text(chat_id: int) -> str:
    np = sm.now_playing.get(chat_id)
    if not np:
        return "Nothing is playing."
    repeat_on = sm.repeat_flags.get(chat_id, False)
    return (
        f"❝ **Streaming** ❞\n\n"
        f"❝ **Title :** {np['title']}\n"
        f"**Duration :** {sm.format_duration(np['duration'])} Minutes\n"
        f"**Requested By :** {np['requested_by']}\n"
        f"**Repeat :** {'On' if repeat_on else 'Off'} ❞"
    )


async def _start_track(chat_id: int, track: dict):
    """Actually start playing a resolved track dict via PyTgCalls, and
    record it as now_playing."""
    await clients.call_py.play(chat_id, MediaStream(track["url"]))
    sm.now_playing[chat_id] = track


async def _play_next_or_leave(chat_id: int):
    """Called when a track finishes (or is skipped). Pulls the next item
    off the queue, resolving it if it's still a raw query string, and
    starts it — or leaves the call if the queue is empty."""
    if sm.repeat_flags.get(chat_id) and chat_id in sm.now_playing:
        # Replay the current track instead of advancing.
        current = sm.now_playing[chat_id]
        await _start_track(chat_id, current)
        return

    # Song finished — per your requirement, its data is dropped now.
    sm.now_playing.pop(chat_id, None)

    next_item = sm.pop_next(chat_id)
    if next_item is None:
        try:
            await clients.call_py.leave_call(chat_id)
        except Exception as e:
            log.warning(f"[VC] leave_call error (likely already left): {e}")
        return

    if isinstance(next_item, str):
        # Raw query from a playlist — resolve now, right before it plays.
        try:
            next_item = await sm.resolve_track(next_item, "Playlist")
        except Exception as e:
            log.error(f"[VC] Failed to resolve queued track '{next_item}': {e}")
            await _play_next_or_leave(chat_id)
            return

    await _start_track(chat_id, next_item)


@router.message(Command("play"))
async def play_handler(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("Usage: `/play <song name>`")
        return

    chat_id = message.chat.id
    requester = message.from_user.first_name if message.from_user else "someone"

    status = await message.reply("Searching...")
    try:
        track = await sm.resolve_track(command.args, requester)
    except Exception as e:
        await status.edit_text(f"Couldn't find that: {e}")
        return

    if chat_id in sm.now_playing:
        position = sm.enqueue(chat_id, track)
        await status.edit_text(f"Added to queue at position {position}: **{track['title']}**")
        return

    try:
        await _start_track(chat_id, track)
    except Exception as e:
        await status.edit_text(f"Couldn't join/stream in the voice chat: {e}")
        return

    await status.delete()
    await message.answer(_now_playing_text(chat_id), reply_markup=_controls_keyboard())


@router.message(Command("pause"))
async def pause_handler(message: Message):
    chat_id = message.chat.id
    try:
        await clients.call_py.pause(chat_id)
        await message.reply("Paused.")
    except Exception as e:
        await message.reply(f"Nothing to pause: {e}")


@router.message(Command("resume"))
async def resume_handler(message: Message):
    chat_id = message.chat.id
    try:
        await clients.call_py.resume(chat_id)
        await message.reply("Resumed.")
    except Exception as e:
        await message.reply(f"Nothing to resume: {e}")


@router.message(Command("stop"))
async def stop_handler(message: Message):
    chat_id = message.chat.id
    try:
        await clients.call_py.leave_call(chat_id)
    except Exception as e:
        log.warning(f"[VC] leave_call error on /stop: {e}")
    sm.clear_chat(chat_id)
    await message.reply("Stopped streaming and left the voice chat. Queue cleared.")


@router.message(Command("skip"))
async def skip_handler(message: Message):
    chat_id = message.chat.id
    if chat_id not in sm.now_playing:
        await message.reply("Nothing is playing.")
        return
    # Force-advance regardless of the repeat flag for an explicit /skip.
    was_repeat = sm.repeat_flags.get(chat_id, False)
    sm.repeat_flags[chat_id] = False
    await _play_next_or_leave(chat_id)
    sm.repeat_flags[chat_id] = was_repeat
    if chat_id in sm.now_playing:
        await message.answer(_now_playing_text(chat_id), reply_markup=_controls_keyboard())
    else:
        await message.reply("Queue is empty — left the voice chat.")


@router.message(Command("repeat"))
async def repeat_handler(message: Message):
    chat_id = message.chat.id
    sm.repeat_flags[chat_id] = not sm.repeat_flags.get(chat_id, False)
    state = "on" if sm.repeat_flags[chat_id] else "off"
    await message.reply(f"Repeat turned **{state}**.")


@router.message(Command("saveplaylist"))
async def save_playlist_handler(message: Message, command: CommandObject):
    if not command.args or len(command.args.split()) < 2:
        await message.reply("Usage: `/saveplaylist <spotify_playlist_url> <name>`")
        return

    parts = command.args.split()
    playlist_url = parts[0]
    name = " ".join(parts[1:])

    status = await message.reply("Fetching playlist from Spotify...")
    try:
        tracks = await sm.fetch_spotify_tracks(playlist_url)
    except Exception as e:
        await status.edit_text(f"Couldn't fetch that playlist: {e}")
        return

    if not tracks:
        await status.edit_text("That playlist appears to be empty.")
        return

    sm.save_playlist(message.from_user.id, name, tracks)
    await status.edit_text(f"Saved playlist **{name}** with {len(tracks)} tracks.")


@router.message(Command("playlist"))
async def play_playlist_handler(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("Usage: `/playlist <name>`")
        return

    name = command.args.strip()
    tracks = sm.get_playlist(message.from_user.id, name)
    if not tracks:
        await message.reply(f"No saved playlist named **{name}**.")
        return

    chat_id = message.chat.id
    requester = message.from_user.first_name if message.from_user else "someone"

    if chat_id in sm.now_playing:
        for t in tracks:
            sm.enqueue(chat_id, t)
        await message.reply(f"Queued {len(tracks)} tracks from **{name}**.")
        return

    status = await message.reply("Starting playlist...")
    try:
        first_track = await sm.resolve_track(tracks[0], requester)
    except Exception as e:
        await status.edit_text(f"Couldn't start playlist: {e}")
        return

    for t in tracks[1:]:
        sm.enqueue(chat_id, t)

    try:
        await _start_track(chat_id, first_track)
    except Exception as e:
        await status.edit_text(f"Couldn't join/stream in the voice chat: {e}")
        return

    await status.delete()
    await message.answer(_now_playing_text(chat_id), reply_markup=_controls_keyboard())


@router.message(Command("playlists"))
async def list_playlists_handler(message: Message):
    names = sm.list_playlists(message.from_user.id)
    if not names:
        await message.reply("You don't have any saved playlists yet.")
        return
    listing = "\n".join(f"• {n}" for n in names)
    await message.reply(f"**Your saved playlists:**\n{listing}")


@router.message(Command("deleteplaylist"))
async def delete_playlist_handler(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("Usage: `/deleteplaylist <name>`")
        return
    name = command.args.strip()
    if sm.delete_playlist(message.from_user.id, name):
        await message.reply(f"Deleted playlist **{name}**.")
    else:
        await message.reply(f"No saved playlist named **{name}**.")


# --- Inline button controls (Pause / Resume / Repeat / Stop) ---
@router.callback_query(lambda c: c.data and c.data.startswith("vc:"))
async def stream_controls(callback: CallbackQuery):
    action = callback.data.split(":", 1)[1]
    chat_id = callback.message.chat.id

    if action == "pause":
        try:
            await clients.call_py.pause(chat_id)
            await callback.answer("Paused")
        except Exception as e:
            await callback.answer(f"Nothing to pause: {e}", show_alert=True)

    elif action == "resume":
        try:
            await clients.call_py.resume(chat_id)
            await callback.answer("Resumed")
        except Exception as e:
            await callback.answer(f"Nothing to resume: {e}", show_alert=True)

    elif action == "repeat":
        sm.repeat_flags[chat_id] = not sm.repeat_flags.get(chat_id, False)
        state = "on" if sm.repeat_flags[chat_id] else "off"
        await callback.answer(f"Repeat {state}")
        try:
            await callback.message.edit_text(_now_playing_text(chat_id), reply_markup=_controls_keyboard())
        except Exception:
            pass

    elif action == "stop":
        try:
            await clients.call_py.leave_call(chat_id)
        except Exception as e:
            log.warning(f"[VC] leave_call error on stop button: {e}")
        sm.clear_chat(chat_id)
        await callback.answer("Stopped")
        try:
            await callback.message.edit_text("Stopped streaming and left the voice chat. Queue cleared.")
        except Exception:
            pass


# --- PyTgCalls stream-end event ---
# Registered from main.py after clients.call_py exists (see register_stream_end_handler
# below), since call_py isn't constructed until inside the running loop.
def register_stream_end_handler():
    from pytgcalls import filters as pfilters

    @clients.call_py.on_update(pfilters.stream_end())
    async def _on_stream_end(_, update):
        chat_id = update.chat_id
        log.info(f"[VC] Stream ended in {chat_id}, advancing queue...")
        await _play_next_or_leave(chat_id)
