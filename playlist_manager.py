import json
import os
import uuid
from datetime import datetime, timezone
from typing import Optional
from encryption import save_encrypted, load_encrypted

PLAYLIST_FILE = "playlists.json"
MAX_TRACKS_PER_PLAYLIST = 50
MAX_PLAYLISTS_PER_GUILD = 20

_data: dict = {"playlists": {}}


def load() -> None:
    global _data
    if not os.path.exists(PLAYLIST_FILE):
        _data = {"playlists": {}}
        return
    try:
        raw = load_encrypted(PLAYLIST_FILE)
        _data = json.loads(raw)
        _data.setdefault("playlists", {})
    except Exception as e:
        print(f"[PLAYLIST] Load error: {e}")
        _data = {"playlists": {}}


def save() -> None:
    try:
        save_encrypted(PLAYLIST_FILE, json.dumps(_data, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"[PLAYLIST] Save error: {e}")


def get_guild_playlists(guild_id: int) -> dict[str, dict]:
    return _data["playlists"].get(str(guild_id), {})


def get_playlist(guild_id: int, playlist_id: str) -> Optional[dict]:
    return _data["playlists"].get(str(guild_id), {}).get(playlist_id)


def create_playlist(
    guild_id: int,
    name: str,
    creator_id: int,
    creator_name: str,
) -> tuple[Optional[str], Optional[str]]:
    gid = str(guild_id)
    guild_pls = _data["playlists"].setdefault(gid, {})
    if len(guild_pls) >= MAX_PLAYLISTS_PER_GUILD:
        return None, f"Maximum of {MAX_PLAYLISTS_PER_GUILD} playlists per server reached."
    for pl in guild_pls.values():
        if pl["name"].lower() == name.strip().lower():
            return None, f"A playlist named **{name}** already exists in this server."
    pid = str(uuid.uuid4())[:8]
    guild_pls[pid] = {
        "name": name.strip(),
        "creator_id": creator_id,
        "creator_name": creator_name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "tracks": [],
    }
    save()
    return pid, None


def add_tracks(
    guild_id: int,
    playlist_id: str,
    tracks: list[dict],
    max_tracks: Optional[int] = None,
) -> tuple[int, int]:
    gid = str(guild_id)
    pl = _data["playlists"].get(gid, {}).get(playlist_id)
    if not pl:
        return 0, len(tracks)
    limit = MAX_TRACKS_PER_PLAYLIST if max_tracks is None else max_tracks
    available = max(limit - len(pl["tracks"]), 0)
    to_add = tracks[:available]
    skipped = len(tracks) - len(to_add)
    pl["tracks"].extend(to_add)
    save()
    return len(to_add), skipped


def delete_playlist(guild_id: int, playlist_id: str) -> bool:
    gid = str(guild_id)
    guild_pls = _data["playlists"].get(gid, {})
    if playlist_id not in guild_pls:
        return False
    del guild_pls[playlist_id]
    save()
    return True


def remove_track(guild_id: int, playlist_id: str, index: int) -> bool:
    pl = get_playlist(guild_id, playlist_id)
    if not pl:
        return False
    tracks = pl.get("tracks", [])
    if not (0 <= index < len(tracks)):
        return False
    tracks.pop(index)
    save()
    return True


load()
