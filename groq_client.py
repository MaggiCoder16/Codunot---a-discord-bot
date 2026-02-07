import aiohttp
import os
import asyncio
import base64
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

SESSION: aiohttp.ClientSession | None = None

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

# ---------------- UNIFIED CLIENT ----------------
async def call_groq(
    prompt: str,
    model: str = "llama-3.3-70b-versatile",
    temperature: float = 1.0,
    image_bytes: bytes | None = None,
    max_tokens: int = 500,
    retries: int = 2
) -> str | None:

    if not GROQ_API_KEY:
        print("Missing GROQ API Key")
        return None

    session = await get_session()

    # Build content
    content = [{"type": "text", "text": prompt}]

    if image_bytes is not None:
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{b64}"
            }
        })

    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": content
            }
        ],
        "temperature": temperature,
        "max_tokens": max_tokens
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
                    response_text = data["choices"][0]["message"]["content"]
                    print(f"[GROQ] Model: {model}, Response length: {len(response_text)} chars")
                    return response_text

                print("\n===== GROQ ERROR =====")
                print(f"Attempt {attempt}/{retries}, Status: {resp.status}")
                print(f"Model: {model}")
                print(clean_log(text))
                print("================================\n")

                # Don't retry on auth errors
                if resp.status in (401, 403):
                    return None
                
                # Rate limit - backoff and retry
                if resp.status == 429:
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 8)
                    continue
                
                # For 503 (overload), raise exception so caller can handle fallback
                if resp.status == 503:
                    raise Exception(f"503 service overloaded - model {model} over capacity")

        except Exception as e:
            error_msg = clean_log(str(e))
            print(f"[GROQ ERROR] Attempt {attempt}/{retries}: {error_msg}")
            
            # If this is the last attempt, re-raise so caller can handle
            if attempt == retries:
                raise e
            
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 8)

    return None
