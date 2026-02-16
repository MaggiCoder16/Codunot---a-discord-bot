import asyncio
import json
import os
import time
from typing import Optional, Tuple, Any
import aiohttp

TOPGG_TOKEN = os.getenv("TOPGG_TOKEN")
BOT_ID = "1435987186502733878"

CACHE_SECONDS = 60
NEGATIVE_CACHE_SECONDS = 15
DEFAULT_POLL_ATTEMPTS = 3
DEFAULT_POLL_INTERVAL_SECONDS = 2

_vote_cache = {}

# WEBHOOK JSON CHECK

def _check_webhook_vote(user_id: int) -> bool:
    try:
        with open("topgg_votes.json", "r", encoding="utf-8") as f:
            votes = json.load(f)
    except Exception:
        return False

    expiry = votes.get(str(user_id))

    if expiry and time.time() < expiry:
        return True

    return False

# API FALLBACK

def _parse_voted_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value == 1
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return False


async def _request_vote_status(
    session: aiohttp.ClientSession,
    user_id: int,
    url: str,
    headers: dict,
) -> Tuple[Optional[bool], Optional[int]]:

    try:
        async with session.get(url, headers=headers) as resp:
            if resp.status != 200:
                return None, resp.status

            data = await resp.json()
            voted = _parse_voted_value(data.get("voted", 0))
            return voted, resp.status

    except Exception:
        return None, None


# MAIN CHECK

async def has_voted(
    user_id: int,
    poll_attempts: int = DEFAULT_POLL_ATTEMPTS,
    poll_interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS,
) -> bool:

    now = time.time()

    if _check_webhook_vote(user_id):
        return True

    if user_id in _vote_cache:
        voted, expires = _vote_cache[user_id]
        if now < expires:
            return voted

    if not TOPGG_TOKEN:
        return False

    url = f"https://top.gg/api/bots/{BOT_ID}/check?userId={user_id}"
    headers = {"Authorization": TOPGG_TOKEN}

    attempts = max(1, poll_attempts)
    interval = max(0, poll_interval_seconds)

    async with aiohttp.ClientSession() as session:
        for attempt in range(attempts):
            voted, _ = await _request_vote_status(
                session, user_id, url, headers
            )

            if voted:
                expires = time.time() + CACHE_SECONDS
                _vote_cache[user_id] = (True, expires)
                return True

            if attempt < attempts - 1:
                await asyncio.sleep(interval)

    expires = time.time() + NEGATIVE_CACHE_SECONDS
    _vote_cache[user_id] = (False, expires)
    return False
