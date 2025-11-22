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

def clean_log(text: str) -> str:
    if not text:
        return text
    if OPENROUTER_API_KEY:
        text = text.replace(OPENROUTER_API_KEY, "***")
    return text

async def call_openrouter(prompt: str, model: str, temperature: float = 1.0, retries: int = 4) -> str | None:
    if not OPENROUTER_API_KEY:
        print("[ERROR] OpenRouter API key missing!")
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
    }

    backoff = 1
    for attempt in range(1, retries + 1):
        try:
            async with session.post(OPENROUTER_URL, headers=headers, json=payload, timeout=60) as resp:
                text = await resp.text()
                text_clean = clean_log(text)
                if resp.status != 200:
                    print(f"[OPENROUTER ERROR] Attempt {attempt}: Status {resp.status}, Response: {text_clean}")
                    if resp.status in (401, 403):
                        print("[OPENROUTER] Authentication failed. Check your API key.")
                        return None
                    if resp.status == 429:
                        print(f"[OPENROUTER] Rate limited. Retrying in {backoff}s...")
                        await asyncio.sleep(backoff)
                        backoff = min(backoff * 2, 8)
                        continue
                    # Other errors: retry
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 8)
                    continue

                # Success
                data = await resp.json()
                return data["choices"][0]["message"]["content"]

        except Exception as e:
            print(f"[OPENROUTER EXCEPTION] Attempt {attempt}: {clean_log(str(e))}, retrying in {backoff}s...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 8)

    print("[OPENROUTER] All attempts failed.")
    return None
