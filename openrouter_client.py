import aiohttp
import os
import asyncio
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

SESSION: aiohttp.ClientSession | None = None


# --- SANITIZE LOGS SO GITHUB DOESN’T HIDE THEM ---
def clean_log(text: str) -> str:
    if not text:
        return text
    # Remove API key from logs
    if OPENROUTER_API_KEY:
        text = text.replace(OPENROUTER_API_KEY, "***")
    return text


async def get_session():
    global SESSION
    if SESSION is None or SESSION.closed:
        SESSION = aiohttp.ClientSession()
    return SESSION


async def call_openrouter(
    prompt: str,
    model: str,
    temperature: float = 1.0,
    retries: int = 4
) -> str | None:

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
            async with session.post(
                OPENROUTER_URL,
                headers=headers,
                json=payload,
                timeout=60
            ) as resp:

                # ---- SUCCESS ----
                if resp.status == 200:
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"]

                # ---- AUTH FAIL ----
                if resp.status in (401, 403):
                    raw = clean_log(await resp.text())
                    print("\n===== OPENROUTER AUTH ERROR =====")
                    print(f"Status: {resp.status}")
                    print(raw)
                    print("=================================\n")
                    return None

                # ---- RATE LIMIT ----
                if resp.status == 429:
                    print(f"Rate limit — retrying in {backoff}s...")
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 8)
                    continue

                # ---- OTHER ERRORS ----
                raw = clean_log(await resp.text())
                print("\n===== OPENROUTER ERROR =====")
                print(f"Status: {resp.status}")
                print(raw)
                print("================================\n")
                return None

        except Exception as e:
            # Network or server error
            print(f"Exception: {clean_log(str(e))} — retrying in {backoff}s...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 8)

    # ---- TOTAL FAILURE ----
    return None
