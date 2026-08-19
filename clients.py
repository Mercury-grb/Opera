from pyrogram import Client
from pytgcalls import PyTgCalls
import config

# Populated by init_clients(), called once inside main()'s running loop.
# Stays None until then. Plugins should `import clients` and reference
# clients.assistant / clients.call_py at CALL TIME inside handler
# functions (not at import time) — by the time any command actually runs,
# startup has already completed and these are populated.
assistant: Client | None = None
call_py: PyTgCalls | None = None


def init_clients():
    global assistant, call_py
    assistant = Client(
        "assistant_session",
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        session_string=config.ASSISTANT_SESSION,
        ipv6=False,
    )
    call_py = PyTgCalls(assistant)
    return assistant, call_py
    
