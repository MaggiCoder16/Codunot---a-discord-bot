import aiohttp
import os
import asyncio
from dotenv import load_dotenv
load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

SESSION: aiohttp.ClientSession | None = None

async def get_session():
    global SESSION
    if SESSION is None or SESSION.closed:
        SESSION = aiohttp.ClientSession()
    return SESSION

async def call_openrouter(prompt: str, model: str, max_tokens: int | None = None, temperature: float = 1.0, retries: int = 4) -> str:
    if OPENROUTER_API_KEY is None:
        return "OpenRouter API key missing."

    session = await get_session()

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
    }
    if max_tokens:
        payload["max_tokens"] = max_tokens

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://example.com",
        "X-Title": "Codunot Discord Bot"
    }

    backoff = 1
    for attempt in range(1, retries + 1):
        try:
            async with session.post(OPENROUTER_URL, headers=headers, json=payload, timeout=20) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"]
                if resp.status == 429:
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 8)
                    continue
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 8)
        except asyncio.TimeoutError:
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 8)
        except Exception:
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 8)

    return "uhh.... my brain lowk lagged 💀💀 say that again?"
