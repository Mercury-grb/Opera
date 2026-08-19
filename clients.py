from pyrogram import Client
from pytgcalls import PyTgCalls
import config


# IMPORTANT: don't construct Client()/PyTgCalls() at module import time.
# Pyrogram's Client.__init__ caches whatever event loop is "current" at
# construction — but module-level code runs BEFORE asyncio.run(main())
# ever creates the actual running loop, so it binds to a throwaway loop
# instead of the real one. That mismatch is exactly the "attached to a
# different loop" error. Fix: build these lazily, from inside the running
# loop (called once, early, in main()).
def build_clients():
    assistant = Client(
        "assistant_session",
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        session_string=config.ASSISTANT_SESSION,
        ipv6=False,
    )
    call_py = PyTgCalls(assistant)
    return assistant, call_py
