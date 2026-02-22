import json
from pathlib import Path
from typing import Dict, List, Optional

CONFIG_FILE = Path("guild_chat_config.json")
DEFAULT_MODE = "server"

# Cache loaded once on startup and kept in-memory throughout runtime.
_guild_chat_config: Dict[int, Dict[str, object]] = {}


def load_guild_chat_config() -> None:
    global _guild_chat_config

    if not CONFIG_FILE.exists():
        _guild_chat_config = {}
        return

    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as f:
            raw = json.load(f)

        parsed: Dict[int, Dict[str, object]] = {}
        for guild_id, data in raw.items():
            try:
                gid = int(guild_id)
            except (TypeError, ValueError):
                continue

            mode = data.get("mode", DEFAULT_MODE)
            channels_raw = data.get("channels", [])
            channels: List[int] = []

            if isinstance(channels_raw, list):
                for channel_id in channels_raw:
                    try:
                        channels.append(int(channel_id))
                    except (TypeError, ValueError):
                        continue

            parsed[gid] = {
                "mode": "channels" if mode == "channels" else DEFAULT_MODE,
                "channels": sorted(set(channels)),
            }

        _guild_chat_config = parsed
    except Exception as e:
        print(f"[CONFIG] Failed to load guild chat config: {e}")
        _guild_chat_config = {}


def save_guild_chat_config() -> None:
    try:
        serialized = {
            str(gid): {
                "mode": data.get("mode", DEFAULT_MODE),
                "channels": [str(ch) for ch in data.get("channels", [])],
            }
            for gid, data in _guild_chat_config.items()
        }

        with CONFIG_FILE.open("w", encoding="utf-8") as f:
            json.dump(serialized, f, indent=2)
    except Exception as e:
        print(f"[CONFIG] Failed to save guild chat config: {e}")


def set_server_mode(guild_id: int, channel_ids: Optional[List[int]] = None) -> None:
    deduped_channels: List[int] = []
    if channel_ids:
        deduped_channels = sorted(set(channel_ids))

    _guild_chat_config[guild_id] = {"mode": "server", "channels": deduped_channels}
    save_guild_chat_config()


def set_channels_mode(guild_id: int, channel_ids: List[int]) -> None:
    deduped = sorted(set(channel_ids))
    _guild_chat_config[guild_id] = {"mode": "channels", "channels": deduped}
    save_guild_chat_config()


def get_guild_config(guild_id: int) -> Dict[str, object]:
    cfg = _guild_chat_config.get(guild_id)
    if not cfg:
        return {"mode": DEFAULT_MODE, "channels": []}
    return cfg


def is_channel_allowed(guild_id: int, channel_id: int) -> bool:
    cfg = get_guild_config(guild_id)
    if cfg.get("mode") != "channels":
        return True
    return channel_id in set(cfg.get("channels", []))
