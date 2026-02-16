import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Tuple

import aiohttp

TOPGG_TOKEN = os.getenv("TOPGG_TOKEN")
BOT_ID = "1435987186502733878"
VOTE_LOG_FILE = Path(os.getenv("TOPGG_VOTE_LOG_FILE", "topgg_vote_log.jsonl"))

_vote_cache = {}
CACHE_SECONDS = 60
NEGATIVE_CACHE_SECONDS = 15
DEFAULT_POLL_ATTEMPTS = 3
DEFAULT_POLL_INTERVAL_SECONDS = 2


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log_vote_event(event_type: str, user_id: int, **details: Any) -> None:
    """Append vote check events as JSONL for auditing/debugging."""
    payload = {
        "timestamp": _now_iso(),
        "event": event_type,
        "user_id": str(user_id),
        **details,
    }

    try:
        with VOTE_LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        return


def _parse_voted_value(value: Any) -> bool:
    """Parse Top.gg `voted` value which may be int, bool, or string."""
    if isinstance(value, bool):
        return value

    if isinstance(value, int):
        return value == 1

    if isinstance(value, str):
        normalized = value.strip().lower()
        return normalized in {"1", "true", "yes"}

    return False


async def _request_vote_status(
    session: aiohttp.ClientSession,
    user_id: int,
    url: str,
    headers: dict,
    attempt: int,
    total_attempts: int,
) -> Tuple[Optional[bool], Optional[int]]:
    _log_vote_event(
        "topgg_request",
        user_id,
        bot_id=BOT_ID,
        attempt=attempt,
        total_attempts=total_attempts,
    )

    try:
        async with session.get(url, headers=headers) as resp:
            status = resp.status

            if status != 200:
                _log_vote_event(
                    "topgg_response_error",
                    user_id,
                    status=status,
                    attempt=attempt,
                    total_attempts=total_attempts,
                )
                return None, status

            data = await resp.json()
            raw_voted = data.get("voted", 0)
            voted = _parse_voted_value(raw_voted)
            _log_vote_event(
                "topgg_response",
                user_id,
                status=status,
                voted=voted,
                raw_voted=raw_voted,
                attempt=attempt,
                total_attempts=total_attempts,
            )
            return voted, status
    except Exception as exc:
        _log_vote_event(
            "topgg_request_exception",
            user_id,
            error=str(exc),
            attempt=attempt,
            total_attempts=total_attempts,
        )
        return None, None


async def has_voted(
    user_id: int,
    poll_attempts: int = DEFAULT_POLL_ATTEMPTS,
    poll_interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS,
) -> bool:
    now = time.time()

    if user_id in _vote_cache:
        voted, expires = _vote_cache[user_id]
        if now < expires:
            _log_vote_event("cache_hit", user_id, voted=voted, cache_expires_at=expires)
            return voted

    if not TOPGG_TOKEN:
        _log_vote_event("topgg_token_missing", user_id)
        return False

    url = f"https://top.gg/api/bots/{BOT_ID}/check?userId={user_id}"
    headers = {"Authorization": TOPGG_TOKEN}

    attempts = max(1, poll_attempts)
    interval = max(0, poll_interval_seconds)

    async with aiohttp.ClientSession() as session:
        for attempt in range(1, attempts + 1):
            voted, _ = await _request_vote_status(session, user_id, url, headers, attempt, attempts)

            if voted is True:
                expires = time.time() + CACHE_SECONDS
                _vote_cache[user_id] = (True, expires)
                _log_vote_event("vote_confirmed", user_id, cache_expires_at=expires)
                return True

            if attempt < attempts:
                await asyncio.sleep(interval)

    expires = time.time() + NEGATIVE_CACHE_SECONDS
    _vote_cache[user_id] = (False, expires)
    _log_vote_event("vote_not_confirmed", user_id, cache_expires_at=expires, attempts=attempts)
    return False
