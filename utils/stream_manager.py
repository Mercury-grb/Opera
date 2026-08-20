"""
Core state + logic for voice-chat streaming: search, queue, playlists.
"""
import asyncio
import json
import os
import logging
import re
import urllib.parse
import aiohttp
import yt_dlp
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import config

log = logging.getLogger("bot")

PLAYLISTS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "playlists.json")

# --- Per-chat state ---
queues: dict[int, list] = {}
now_playing: dict[int, dict] = {}
repeat_flags: dict[int, bool] = {}

async def _piped_extract_async(query: str) -> dict:
    """Async proxy extraction using multiple Piped APIs to bypass IP blocks."""
    instances = [
        "https://pipedapi.tokhmi.xyz",
        "https://pipedapi.syncpundit.io",
        "https://pipedapi.smnz.de",
        "https://api.piped.yt",
        "https://pipedapi.kavin.rocks" # Kavin is last because it frequently throws 525 errors
    ]
    
    async with aiohttp.ClientSession() as session:
        yt_id = None
        
        # 1. Detect if query is a URL or a Text Search
        if "youtube.com" in query or "youtu.be" in query:
            if "v=" in query:
                yt_id = query.split("v=")[-1].split("&")[0]
            else:
                yt_id = query.split("/")[-1].split("?")[0]
        else:
            # It's a text search! Cycle through instances to find the video ID
            safe_query = urllib.parse.quote(query)
            for base_url in instances:
                try:
                    search_url = f"{base_url}/search?q={safe_query}&filter=videos"
                    async with session.get(search_url, timeout=5) as res:
                        if res.status == 200:
                            data = await res.json()
                            if data.get("items"):
                                yt_id = data["items"][0]["url"].split("v=")[-1]
                                break
                except Exception:
                    continue
                    
        if not yt_id:
            raise ValueError(f"Could not find YouTube results for '{query}'.")

        # 2. Extract the Audio Stream using the ID
        for base_url in instances:
            try:
                stream_url = f"{base_url}/streams/{yt_id}"
                async with session.get(stream_url, timeout=5) as res:
                    if res.status == 200:
                        data = await res.json()
                        audio_streams = data.get("audioStreams", [])
                        if audio_streams:
                            best_audio = sorted(audio_streams, key=lambda x: x.get("bitrate", 0), reverse=True)[0]
                            return {
                                "title": data.get("title", query),
                                "duration": data.get("duration", 0),
                                "url": best_audio["url"],
                                "webpage_url": f"https://youtube.com/watch?v={yt_id}",
                                "thumbnail": data.get("thumbnailUrl")
                            }
            except Exception:
                continue
                
        raise ValueError("Failed to fetch audio stream. Proxies may be overloaded.")

async def _resolve_via_jiosaavn(query: str) -> dict | None:
    """Resolve track using JioSaavn's actual song-search endpoint directly.

    NOTE: the jiosaavn-python library's search_songs() was found (via logs)
    to call JioSaavn's autocomplete.get endpoint instead of a real search —
    that endpoint only returns typeahead suggestions with no downloadUrl
    field, so every lookup silently came back empty. Calling the real
    search.getResults endpoint ourselves avoids depending on the library's
    (apparently wrong) internal routing.
    """
    url = "https://www.jiosaavn.com/api.php"
    params = {
        "__call": "search.getResults",
        "q": query,
        "_format": "json",
        "_marker": "0",
        "ctx": "web6dot0",
        "p": "1",
        "n": "1",
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=8) as res:
                if res.status != 200:
                    return None
                data = await res.json(content_type=None)
    except Exception as e:
        log.warning(f"[JIOSAAVN] Search request failed: {e}")
        return None

    songs = data.get("results") if isinstance(data, dict) else data
    if not songs:
        return None

    song = songs[0]
    url = None
    if isinstance(song.get("downloadUrl"), list) and song["downloadUrl"]:
        url = song["downloadUrl"][-1].get("link") or song["downloadUrl"][-1].get("url")
    elif isinstance(song.get("download_url"), list) and song["download_url"]:
        url = song["download_url"][-1].get("link") or song["download_url"][-1].get("url")
    else:
        url = song.get("media_url") or song.get("media_preview_url") or song.get("url")

    if not url:
        return None

    title = song.get("song") or song.get("name") or song.get("title") or query
    
    duration = song.get("duration") or 0
    try:
        duration = int(duration)
    except (TypeError, ValueError):
        duration = 0

    image_url = None
    if isinstance(song.get("image"), list) and song["image"]:
        image_url = song["image"][-1].get("link") or song["image"][-1].get("url")
    elif isinstance(song.get("image_url"), list) and song["image_url"]:
        image_url = song["image_url"][-1].get("link") or song["image_url"][-1].get("url")
    elif isinstance(song.get("image"), str):
        image_url = song.get("image")

    return {
        "title": title, 
        "duration": duration, 
        "url": url,
        "thumbnail": image_url
    }

def _sc_extract(query: str) -> dict:
    """Fallback to SoundCloud via yt-dlp for text searches (Bypasses Render IP bans)."""
    ydl_opts = {
        "format": "bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "default_search": "scsearch",
        "socket_timeout": 5, # CRITICAL: Prevents yt-dlp from hanging infinitely
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(query, download=False)
        if "entries" in info:
            if not info["entries"]:
                raise ValueError("No results found.")
            info = info["entries"][0]
            
        return {
            "title": info.get("title") or query,
            "duration": info.get("duration") or 0,
            "url": info.get("url"),
            "thumbnail": info.get("thumbnail"),
            "webpage_url": info.get("webpage_url"),
        }

async def resolve_track(query: str, requested_by: str) -> dict:
    """Bulletproof resolver that routes through 3 different platforms."""
    
    # Tier 1: Piped API (YouTube) - Best Catalog, Async, No IP blocks
    try:
        log.info(f"[STREAM] Routing '{query}' to Piped API")
        info = await asyncio.wait_for(_piped_extract_async(query), timeout=15.0)
        info["requested_by"] = requested_by
        info["source"] = "youtube_proxy"
        return info
    except Exception as e:
        log.warning(f"Piped extraction failed: {e}")

    # Tier 2: JioSaavn - Fast native async, but library might be outdated
    try:
        log.info(f"[STREAM] Routing '{query}' to JioSaavn")
        saavn_track = await asyncio.wait_for(_resolve_via_jiosaavn(query), timeout=5.0)
        if saavn_track:
            saavn_track["requested_by"] = requested_by
            saavn_track["source"] = "jiosaavn"
            return saavn_track
    except Exception as e:
        log.warning(f"JioSaavn failed: {e}")

    # Tier 3: SoundCloud via yt-dlp - Huge catalog, but blocking.
    try:
        log.info(f"[STREAM] Routing '{query}' to SoundCloud")
        info = await asyncio.wait_for(asyncio.to_thread(_sc_extract, query), timeout=10.0)
        info["requested_by"] = requested_by
        info["source"] = "soundcloud"
        return info
    except Exception as e:
        log.warning(f"SoundCloud failed: {e}")

    raise ValueError(f"Could not find or extract '{query}'. All search engines failed or timed out.")

def format_duration(seconds: int) -> str:
    seconds = int(seconds or 0)
    m, s = divmod(seconds, 60)
    return f"{m}:{s:02d}"

def enqueue(chat_id: int, item) -> int:
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

# --- Spotify playlist fetching ---
_SPOTIFY_URL_RE = re.compile(r"playlist/([a-zA-Z0-9]+)")

def _spotify_client():
    return spotipy.Spotify(
        auth_manager=SpotifyClientCredentials(
            client_id=config.SPOTIPY_CLIENT_ID,
            client_secret=config.SPOTIPY_CLIENT_SECRET,
        )
    )

def _fetch_spotify_tracks(playlist_url: str) -> list[str]:
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

# --- Playlist persistence ---
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
    
