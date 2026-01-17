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

# ---------------- GENERAL CLIENT ----------------
async def call_groq(
    prompt: str | None = None,
    model: str = "llama-3.3-70b-versatile",
    temperature: float = 1.0,
    image_bytes: bytes | None = None,
    retries: int = 4
) -> str | None:
    """
    Call Groq for text or image completions.
    - If `image_bytes` is provided, uses SCOUT_MODEL automatically.
    """
    if not GROQ_API_KEY:
        print("Missing GROQ API Key")
        return None

    session = await get_session()

    content_list = [{"type": "text", "text": prompt}]
    if image_bytes:
        # Encode image as base64
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        img_data_url = f"data:image/png;base64,{b64}"
        content_list.append({"type": "image_url", "image_url": {"url": img_data_url}})
        model = SCOUT_MODEL  # enforce Scout for vision

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": content_list}],
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
