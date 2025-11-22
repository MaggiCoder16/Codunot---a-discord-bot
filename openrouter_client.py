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

async def call_openrouter(prompt: str, model: str, temperature: float = 1.0, retries: int = 4) -> str:
    if OPENROUTER_API_KEY is None:
        return "OpenRouter API key missing."

    session = await get_session()

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
    }

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/MaggiCoder16/Codunot---a-discord-bot",
        "X-Title": "Codunot Discord Bot"
    }

    backoff = 1
    for attempt in range(1, retries + 1):
        try:
            async with session.post(
                OPENROUTER_URL,
                headers=headers,
                json=payload,
                timeout=60
            ) as resp:

                if resp.status != 200:
                    error_text = await resp.text()
                    print("\n===== OPENROUTER ERROR =====")
                    print(f"Status: {resp.status}")
                    print(f"Response: {error_text}")
                    print("================================\n")
                    return None

                if resp.status in (401, 403):
                    return f"OpenRouter auth failed ({resp.status}). Your API key is invalid."

                if resp.status == 429:
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 8)
                    continue

                # other errors
                text = await resp.text()
                return f"OpenRouter error {resp.status}: {text}"

        except Exception:
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 8)

    return "uhm uhm.. i gtg ahh... lets talk later, k? sooweeeeyyy"
