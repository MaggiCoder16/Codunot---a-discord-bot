import aiohttp
import os
import asyncio
import base64
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

SESSION: aiohttp.ClientSession | None = None

# Default vision model (from your groq_bot.py)
SCOUT_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

def clean_log(text: str) -> str:
    if not text:
        return text
    if GROQ_API_KEY:
        text = text.replace(GROQ_API_KEY, "***")
    return text

async def get_session():
    global SESSION
    if SESSION is None or SESSION.closed:
        SESSION = aiohttp.ClientSession()
    return SESSION

# ---------------- TEXT ONLY CLIENT ----------------
async def call_groq(
    prompt: str | None = None,
    model: str = "llama-3.3-70b-versatile",
    temperature: float = 1.0,
    retries: int = 4
) -> str | None:
    """Call Groq for text completions only."""
    if not GROQ_API_KEY:
        print("Missing GROQ API Key")
        return None

    session = await get_session()
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
        "temperature": temperature,
        "max_tokens": 500
    }

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    backoff = 1
    for attempt in range(1, retries + 1):
        try:
            async with session.post(GROQ_URL, headers=headers, json=payload, timeout=60) as resp:
                text = await resp.text()
                if resp.status == 200:
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"]
                print("\n===== GROQ ERROR =====")
                print(f"Attempt {attempt}, Status: {resp.status}")
                print(clean_log(text))
                print("================================\n")
                if resp.status in (401, 403):
                    return None
                if resp.status == 429:
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 8)
                    continue
        except Exception as e:
            print(f"Exception on attempt {attempt}: {clean_log(str(e))}")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 8)
    return None

# ---------------- VISION CLIENT ----------------
async def call_vision_model(
    image_bytes: bytes,
    prompt: str,
    temperature: float = 0.7,
    retries: int = 3
) -> str | None:
    """
    Call Groq vision model (Scout) with an image and prompt.
    Uses SCOUT_MODEL automatically.
    """
    if not GROQ_API_KEY:
        print("Missing GROQ API Key")
        return None

    session = await get_session()
    # Encode image as base64 data URL
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    img_data_url = f"data:image/png;base64,{b64}"

    payload = {
        "model": SCOUT_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": img_data_url}}
                ]
            }
        ],
        "temperature": temperature,
        "max_tokens": 500
    }

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    backoff = 1
    for attempt in range(1, retries + 1):
        try:
            async with session.post(GROQ_URL, headers=headers, json=payload, timeout=60) as resp:
                text = await resp.text()
                if resp.status == 200:
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"]
                print("\n===== VISION GROQ ERROR =====")
                print(f"Attempt {attempt}, Status: {resp.status}")
                print(clean_log(text))
                print("================================\n")
                if resp.status in (401, 403):
                    return None
                if resp.status == 429:
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 8)
                    continue
        except Exception as e:
            print(f"[VISION ERROR] Attempt {attempt}: {clean_log(str(e))}")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 8)

    return None
