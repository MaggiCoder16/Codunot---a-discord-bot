import os
import asyncio
import aiohttp
import re
import random

DEAPI_API_KEY = os.getenv("DEAPI_API_KEY")
if not DEAPI_API_KEY:
    raise RuntimeError("DEAPI_API_KEY not set")
WEBHOOK_URL = os.getenv("DEAPI_WEBHOOK_URL")
if not WEBHOOK_URL:
    raise RuntimeError("DEAPI_WEBHOOK_URL not set")
MODEL_NAME = "ZImageTurbo_INT8"

DEFAULT_STEPS = 15
MAX_STEPS = 50
DEFAULT_WIDTH = 512
DEFAULT_HEIGHT = 512
TXT2IMG_URL = "https://api.deapi.ai/api/v1/client/txt2img"
RESULT_URL_BASE = os.getenv("DEAPI_RESULT_BASE", "http://localhost:8000")

async def warm_webhook_server():
    if not RESULT_URL_BASE:
        return
    try:
        async with aiohttp.ClientSession() as session:
            await session.get(RESULT_URL_BASE, timeout=5)
        print("[Warmup] Webhook server awake.")
    except Exception as e:
        print("[Warmup] Warmup skipped:", e)

def clean_prompt(prompt: str) -> str:
    if not prompt or not prompt.strip():
        return "A clean, simple diagram"
    return re.sub(r"[\r\n]+", " ", prompt.strip())[:900]

async def generate_image(prompt: str, aspect_ratio: str = "1:1", steps: int = DEFAULT_STEPS) -> bytes:
    prompt = clean_prompt(prompt)
    steps = min(int(steps), MAX_STEPS)

    width = height = DEFAULT_WIDTH
    if aspect_ratio == "16:9":
        width, height = 768, 432
    elif aspect_ratio == "9:16":
        width, height = 432, 768
    elif aspect_ratio == "1:2":
        width, height = 384, 768

    headers = {"Authorization": f"Bearer {DEAPI_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "width": width,
        "height": height,
        "steps": steps,
        "negative_prompt": "",
        "seed": random.randint(1, 2**32 - 1),
        "webhook_url": WEBHOOK_URL,
    }

    async with aiohttp.ClientSession() as session:
        await warm_webhook_server()

        async with session.post(TXT2IMG_URL, json=payload, headers=headers) as resp:
            if resp.status != 200:
                raise RuntimeError(await resp.text())
            data = await resp.json()

        request_id = data["data"]["request_id"]
        poll_url = f"{RESULT_URL_BASE}/result/{request_id}"

        max_attempts = 30
        delay = 5
        for attempt in range(max_attempts):
            async with session.get(poll_url) as r:
                if r.status != 200:
                    await asyncio.sleep(delay)
                    continue
                status_data = await r.json()
                status = status_data.get("status")
                if status == "done":
                    result_url = status_data.get("result_url") or status_data.get("data", {}).get("result_url")
                    if not result_url:
                        raise RuntimeError("Job done but no result_url returned")
                    async with session.get(result_url) as img_resp:
                        if img_resp.status != 200:
                            raise RuntimeError(f"Failed to download image (status {img_resp.status})")
                        return await img_resp.read()
            await asyncio.sleep(delay)

        raise RuntimeError(f"Image not ready after {max_attempts * delay} seconds. Check your webhook server.")
