"""
Core state + logic for voice-chat streaming: search, queue, playlists.
Kept separate from plugins/vc_stream.py (the command handlers) so the
handlers stay focused on Telegram-facing concerns.
"""
import asyncio
import json
import os
import shutil
import logging
import re
import yt_dlp
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from jiosaavn import JioSaavn
import config

log = logging.getLogger("bot")

_saavn = JioSaavn()

PLAYLISTS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "playlists.json")
_WRITABLE_COOKIES_PATH = "/tmp/cookies.txt"


def _get_writable_cookies_path() -> str | None:
    """Render's Secret Files are mounted read-only, but yt-dlp can try to
    write updated cookies back to the file it reads from — which fails on
    a read-only mount. Copy it to /tmp once (re-copies if the source
    changes) and hand yt-dlp that writable copy instead."""
    source = os.environ.get("COOKIES_FILE", "/etc/secrets/cookies.txt")
    if not os.path.exists(source):
        return None
    try:
        if (
            not os.path.exists(_WRITABLE_COOKIES_PATH)
            or os.path.getmtime(source) > os.path.getmtime(_WRITABLE_COOKIES_PATH)
        ):
            shutil.copyfile(source, _WRITABLE_COOKIES_PATH)
        return _WRITABLE_COOKIES_PATH
    except Exception as e:
        log.error(f"[YTDLP] Failed to copy cookies file to writable path: {e}")
        return None

# --- Per-chat state, all in memory ---
# queues[chat_id]      -> list of track dicts OR raw search-query strings,
#                         waiting to play. Resolved (yt-dlp searched) lazily,
#                         right before each one plays — not all upfront.
# now_playing[chat_id] -> dict describing the currently playing track, or
#                         absent if nothing is playing. Deleted entirely once
#                         the track finishes (per your requirement — no
#                         leftover data for a finished song).
# repeat[chat_id]      -> bool, whether to replay the current track on end
queues: dict[int, list] = {}
now_playing: dict[int, dict] = {}
repeat_flags: dict[int, bool] = {}


async def _resolve_via_jiosaavn(query: str) -> dict | None:
    """Try JioSaavn first — it has none of YouTube's anti-scraping/SABR/
    datacenter-IP-blocking issues, since it's a much less aggressively
    protected catalog. Returns None (not an exception) if not found, so
    the caller can fall back to YouTube.

    NOTE: JioSaavn's API isn't officially documented, and different forks
    of the unofficial wrapper libraries use slightly different field
    names for the direct media URL. This defensively checks a few common
    field names and logs the raw result if none match, so a mismatch is
    a one-line fix instead of a mystery.
    """
    try:
        results = await _saavn.search_songs(query)
    except Exception as e:
        log.warning(f"[JIOSAAVN] Search failed for '{query}': {e}")
        return None

    songs = results.get("results") if isinstance(results, dict) else results
    if not songs:
        return None

    song = songs[0]

    # Different field names show up across JioSaavn wrapper versions —
    # try the common ones in order.
    url = None
    if isinstance(song.get("downloadUrl"), list) and song["downloadUrl"]:
        # Usually a list of {quality, link} sorted low->high quality.
        url = song["downloadUrl"][-1].get("link") or song["downloadUrl"][-1].get("url")
    elif isinstance(song.get("download_url"), list) and song["download_url"]:
        url = song["download_url"][-1].get("link") or song["download_url"][-1].get("url")
    else:
        url = song.get("media_url") or song.get("media_preview_url") or song.get("url")

    if not url:
        log.warning(f"[JIOSAAVN] Found a result but couldn't locate a media URL field. Raw result: {json.dumps(song)[:500]}")
        return None

    title = song.get("song") or song.get("name") or song.get("title") or query
    duration = song.get("duration") or 0
    try:
        duration = int(duration)
    except (TypeError, ValueError):
        duration = 0

    return {"title": title, "duration": duration, "url": url}


def _ytdlp_extract(query: str) -> dict:
    ydl_opts = {
        "format": "bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "default_search": "scsearch",
        "extractor_args": {
            "youtube": {
                # Prioritize 'web' or use 'default'. 
                # 'android' often hides 'bestaudio' formats now.
                "player_client": ["web", "default"], 
            },
            "youtubepot-bgutilscript": {
                "script_path": ["auto"],
            },
        },
    }
    # ... rest of your code ...
    
    # Cookies fallback for YouTube's bot detection — see
    # _get_writable_cookies_path() for why we copy it to /tmp first.
    cookies_file = _get_writable_cookies_path()
    if cookies_file:
        ydl_opts["cookiefile"] = cookies_file

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(query, download=False)
        if "entries" in info:
            info = info["entries"][0]
        return {
            "title": info.get("title") or query,
            "duration": info.get("duration") or 0,
            "url": info.get("url"),
            "webpage_url": info.get("webpage_url"),
        }


async def resolve_track(query: str, requested_by: str) -> dict:
    saavn_track = await _resolve_via_jiosaavn(query)
    if saavn_track:
        saavn_track["requested_by"] = requested_by
        saavn_track["source"] = "jiosaavn"
        return saavn_track

    log.info(f"[STREAM] '{query}' not found on JioSaavn, falling back to YouTube")
    info = await asyncio.to_thread(_ytdlp_extract, query)
    return {
        "title": info["title"],
        "duration": info["duration"],
        "url": info["url"],
        "requested_by": requested_by,
        "source": "youtube",
    }


def format_duration(seconds: int) -> str:
    seconds = int(seconds or 0)
    m, s = divmod(seconds, 60)
    return f"{m}:{s:02d}"


def enqueue(chat_id: int, item) -> int:
    """item can be a resolved track dict or a raw query string. Returns the
    new queue length (position)."""
    queues.setdefault(chat_id, []).append(item)
    return len(queues[chat_id])


def pop_next(chat_id: int):
    q = queues.get(chat_id)
    if not q:
        return None
    return q.pop(0)


def clear_chat(chat_id: int):
    queues.pop(chat_id, None)
    now_playing.pop(chat_id, None)
    repeat_flags.pop(chat_id, None)


# --- Spotify playlist fetching (for /saveplaylist) ---
_SPOTIFY_URL_RE = re.compile(r"playlist/([a-zA-Z0-9]+)")


def _spotify_client():
    return spotipy.Spotify(
        auth_manager=SpotifyClientCredentials(
            client_id=config.SPOTIPY_CLIENT_ID,
            client_secret=config.SPOTIPY_CLIENT_SECRET,
        )
    )


def _fetch_spotify_tracks(playlist_url: str) -> list[str]:
    """Blocking — always call via asyncio.to_thread. Returns a list of
    "<track name> <artist>" search-query strings, one per track."""
    match = _SPOTIFY_URL_RE.search(playlist_url)
    if not match:
        raise ValueError("That doesn't look like a valid Spotify playlist URL.")
    playlist_id = match.group(1)

    sp = _spotify_client()
    results = sp.playlist_items(playlist_id, additional_types=["track"])
    queries = []
    while results:
        for item in results.get("items", []):
            track = item.get("track")
            if not track:
                continue
            name = track.get("name", "")
            artists = ", ".join(a["name"] for a in track.get("artists", []))
            queries.append(f"{name} {artists}".strip())
        results = sp.next(results) if results.get("next") else None
    return queries


async def fetch_spotify_tracks(playlist_url: str) -> list[str]:
    return await asyncio.to_thread(_fetch_spotify_tracks, playlist_url)


# --- Playlist persistence (simple JSON file, keyed by user id) ---
def _load_playlists() -> dict:
    if not os.path.exists(PLAYLISTS_FILE):
        return {}
    try:
        with open(PLAYLISTS_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        log.error(f"[PLAYLIST] Failed to load {PLAYLISTS_FILE}: {e}")
        return {}


def _save_playlists(data: dict):
    with open(PLAYLISTS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def save_playlist(user_id: int, name: str, tracks: list[str]):
    data = _load_playlists()
    data.setdefault(str(user_id), {})[name] = tracks
    _save_playlists(data)


def get_playlist(user_id: int, name: str) -> list[str] | None:
    data = _load_playlists()
    return data.get(str(user_id), {}).get(name)


def list_playlists(user_id: int) -> list[str]:
    data = _load_playlists()
    return list(data.get(str(user_id), {}).keys())


def delete_playlist(user_id: int, name: str) -> bool:
    data = _load_playlists()
    user_playlists = data.get(str(user_id), {})
    if name in user_playlists:
        del user_playlists[name]
        _save_playlists(data)
        return True
    return False
