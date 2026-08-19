"""
Core state + logic for voice-chat streaming: search, queue, playlists.
"""
import asyncio
import json
import os
import logging
import re
import aiohttp
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from jiosaavn import JioSaavn
import config

log = logging.getLogger("bot")

_saavn = JioSaavn()
PLAYLISTS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "playlists.json")

# --- Per-chat state ---
queues: dict[int, list] = {}
now_playing: dict[int, dict] = {}
repeat_flags: dict[int, bool] = {}

async def _resolve_via_jiosaavn(query: str) -> dict | None:
    """Resolve track using JioSaavn, including thumbnail extraction."""
    try:
        results = await _saavn.search_songs(query)
    except Exception as e:
        log.warning(f"[JIOSAAVN] Search failed for '{query}': {e}")
        return None

    songs = results.get("results") if isinstance(results, dict) else results
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

    # Extract the highest quality thumbnail
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

async def _piped_extract_async(query: str) -> dict:
    """Async proxy extraction using multiple Piped APIs to bypass IP blocks."""
    instances = [
        "https://pipedapi.kavin.rocks",
        "https://pipedapi.tokhmi.xyz",
        "https://pipedapi.syncpundit.io",
        "https://pipedapi.adminforge.de",
        "https://api.piped.yt"
    ]
    
    async with aiohttp.ClientSession() as session:
        # Detect if query is a URL or a text search
        if "youtube.com" in query or "youtu.be" in query:
            if "v=" in query:
                yt_id = query.split("v=")[-1].split("&")[0]
            else:
                yt_id = query.split("/")[-1].split("?")[0]
        else:
            yt_id = None
            # Search for the video ID using the proxy
            for base_url in instances:
                try:
                    search_url = f"{base_url}/search?q={query}&filter=videos"
                    async with session.get(search_url, timeout=10) as res:
                        if res.status == 200:
                            data = await res.json()
                            if data.get("items"):
                                yt_id = data["items"][0]["url"].split("v=")[-1]
                                break
                except Exception:
                    continue
                    
            if not yt_id:
                raise ValueError(f"Could not find search results for '{query}'.")

        # Extract the highest quality audio stream and thumbnail
        for base_url in instances:
            try:
                stream_url = f"{base_url}/streams/{yt_id}"
                async with session.get(stream_url, timeout=10) as res:
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

async def resolve_track(query: str, requested_by: str) -> dict:
    saavn_track = await _resolve_via_jiosaavn(query)
    if saavn_track:
        saavn_track["requested_by"] = requested_by
        saavn_track["source"] = "jiosaavn"
        return saavn_track

    log.info(f"[STREAM] '{query}' not found on JioSaavn, routing through Piped Proxy")
    info = await _piped_extract_async(query)
    info["requested_by"] = requested_by
    info["source"] = "youtube_proxy"
    
    return info

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
        
