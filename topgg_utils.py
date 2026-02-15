import os
import aiohttp
import time

TOPGG_TOKEN = os.getenv("TOPGG_TOKEN")
BOT_ID = "1435987186502733878"

_vote_cache = {}
CACHE_SECONDS = 60  # 1 minute

async def has_voted(user_id: int) -> bool:
    now = time.time()

    if user_id in _vote_cache:
        voted, expires = _vote_cache[user_id]
        if now < expires:
            return voted

    if not TOPGG_TOKEN:
        return False

    url = f"https://top.gg/api/bots/{BOT_ID}/check?userId={user_id}"
    headers = {"Authorization": TOPGG_TOKEN}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    return False
                data = await resp.json()
                voted = data.get("voted", 0) == 1
                _vote_cache[user_id] = (voted, now + CACHE_SECONDS)
                return voted
    except:
        return False
