from pyrogram import Client
from pytgcalls import PyTgCalls
import config

# Assistant Account Client — still Pyrogram/MTProto, since PyTgCalls (voice
# chats) has no Bot API / webhook equivalent. This is the only remaining
# piece using the long-poll MTProto connection that Render can't deliver
# updates over — but that's fine here, because the assistant client never
# needs to RECEIVE messages, only join/stream into voice chats.
assistant = Client(
    "assistant_session",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    session_string=config.ASSISTANT_SESSION,
    ipv6=False,
)

call_py = PyTgCalls(assistant)
