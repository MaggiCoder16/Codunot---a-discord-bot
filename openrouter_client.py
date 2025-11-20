import aiohttp
import os
import asyncio
from dotenv import load_dotenv
load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Default fallback model
DEFAULT_MODEL = "openai/gpt-oss-20b:free"

SESSION: aiohttp.ClientSession | None = None


async def get_session():
    global SESSION
    if SESSION is None or SESSION.closed:
        SESSION = aiohttp.ClientSession()
    return SESSION


async def call_openrouter(prompt: str, max_tokens=1000, retries=4, model=None, temperature: float = 1.3) -> str:
    """
    Safe OpenRouter call with retries, no crashes, no drops.
    Includes support for the 'temperature' parameter.
    """

    if OPENROUTER_API_KEY is None:
        return "OpenRouter API key missing."

    session = await get_session()

    payload = {
        "model": model or DEFAULT_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://example.com",
        "X-Title": "Codunot Discord Bot"
    }

    backoff = 1

    for attempt in range(1, retries + 1):
        try:
            async with session.post(
                OPENROUTER_URL, headers=headers, json=payload, timeout=20
            ) as resp:

                if resp.status == 200:
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"]

                # Rate limit
                if resp.status == 429:
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 8)
                    continue

                # Other server-side issues
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 8)

        except asyncio.TimeoutError:
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 8)

        except Exception:
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 8)

    return "uhh.... my brain lowk lagged 💀💀 say that again?"
