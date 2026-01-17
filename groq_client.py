import aiohttp
import os
import asyncio
import base64
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

SESSION: aiohttp.ClientSession | None = None

# ---------------- HELPERS ----------------
def clean_log(text: str) -> str:
    """Mask API keys in logs."""
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

def encode_image_bytes(image_bytes: bytes, mime: str = "image/png") -> str:
    """Return base64 data URL string."""
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    return f"data:{mime};base64,{b64}"

# ---------------- TEXT MODEL CALL ----------------
async def call_groq(
    prompt: str | None = None,
    model: str = "llama-3.3-70b-versatile",
    temperature: float = 1.0,
    retries: int = 4
) -> str | None:
    """Call Groq text models (no vision)."""
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

    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
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

# ---------------- VISION MODEL CALL ----------------
async def call_groq_vision(
    prompt: str,
    image_bytes: bytes,
    image_mime: str = "image/png",
    temperature: float = 0.7
) -> str:
    """
    Call Groq vision model (Scout) with an image.
    Streams the response and returns the full text.
    """
    if not GROQ_API_KEY:
        print("Missing GROQ API Key")
        return "⚠️ No API key set."

    client = Groq()
    img_url = encode_image_bytes(image_bytes, mime=image_mime)
    content_blocks = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": img_url}}
    ]

    print(f"[VISION PROMPT SENT TO AI]: {prompt}")

    completion = client.chat.completions.create(
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        messages=[{"role": "user", "content": content_blocks}],
        temperature=temperature,
        max_completion_tokens=1024,
        stream=True
    )

    # Collect streamed response
    full_reply = ""
    for chunk in completion:
        delta = chunk.choices[0].delta
        if delta and delta.content:
            full_reply += delta.content

    return full_reply.strip()
