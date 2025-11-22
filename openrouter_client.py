import aiohttp
import os
import asyncio
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

SESSION: aiohttp.ClientSession | None = None

def clean_log(text: str) -> str:
    if not text:
        return text
    if OPENROUTER_API_KEY:
        text = text.replace(OPENROUTER_API_KEY, "***")
    return text

async def get_session():
    global SESSION
    if SESSION is None or SESSION.closed:
        SESSION = aiohttp.ClientSession()
    return SESSION

async def call_openrouter(prompt: str, model: str, temperature: float = 1.0, retries: int = 4) -> str | None:
    if not OPENROUTER_API_KEY:
        print("Missing OpenRouter API Key")
        return None

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
            async with session.post(OPENROUTER_URL, headers=headers, json=payload, timeout=60) as resp:
                text = await resp.text()
                if resp.status == 200:
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"]

                # Print errors
                print("\n===== OPENROUTER ERROR =====")
                print(f"Attempt {attempt}, Status: {resp.status}")
                print(clean_log(text))
                print("================================\n")

                # Auth error
                if resp.status in (401, 403):
                    return None

                # Rate limit
                if resp.status == 429:
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 8)
                    continue

        except Exception as e:
            print(f"Exception on attempt {attempt}: {clean_log(str(e))}")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 8)

    return None
