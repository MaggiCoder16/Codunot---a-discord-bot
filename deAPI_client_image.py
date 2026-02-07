import os
import asyncio
import aiohttp
import re
import random

# ============================================================
# CONFIG
# ============================================================

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
RESULT_URL_BASE = os.getenv("DEAPI_RESULT_BASE")  # optional: your /result endpoint base

# ============================================================
# PROMPT HELPERS
# ============================================================

def clean_prompt(prompt: str) -> str:
    if not prompt or not prompt.strip():
        return "A clean, simple diagram"
    return re.sub(r"[\r\n]+", " ", prompt.strip())[:900]

# ============================================================
# IMAGE GENERATION (WEBHOOK + POLL RESULT)
# ============================================================

async def generate_image(
    prompt: str,
    aspect_ratio: str = "1:1",
    steps: int = DEFAULT_STEPS,
) -> bytes:
    """
    Submit a generation request to deAPI via webhook.
    Polls your /result endpoint until the image is ready.
    Returns raw PNG bytes.
    """

    prompt = clean_prompt(prompt)
    steps = min(int(steps), MAX_STEPS)

    width = height = DEFAULT_WIDTH
    if aspect_ratio == "16:9":
        width, height = 768, 432
    elif aspect_ratio == "9:16":
        width, height = 432, 768
    elif aspect_ratio == "1:2":
        width, height = 384, 768

    headers = {
        "Authorization": f"Bearer {DEAPI_API_KEY}",
        "Content-Type": "application/json",
    }

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
        # ---------------------------
        # SUBMIT JOB
        # ---------------------------
        async with session.post(TXT2IMG_URL, json=payload, headers=headers) as resp:
            if resp.status != 200:
                raise RuntimeError(await resp.text())
            data = await resp.json()

        request_id = data["data"]["request_id"]
        print(f"[deAPI] request_id={request_id} submitted. Waiting for webhook result...")

        # ---------------------------
        # POLLING LOOP
        # ---------------------------
        poll_url = f"{RESULT_URL_BASE}/result/{request_id}" if RESULT_URL_BASE else None
        if not poll_url:
            # If no base provided, just wait for the webhook to update your local server
            # The Discord bot must fetch from your webhook memory or skip polling
            print("[deAPI] No RESULT_URL_BASE set; ensure your FastAPI webhook is running")
            # Optional: return request_id and let the bot handle /result requests
            return request_id

        max_attempts = 10
        delay = 5  # seconds between polls

        for attempt in range(max_attempts):
            async with session.get(poll_url) as r:
                status_data = await r.json()
                status = status_data.get("status")
                if status == "done":
                    result_url = status_data.get("result_url")
                    if not result_url:
                        raise RuntimeError("Job done but no result_url returned")
                    # Download image
                    async with session.get(result_url) as img_resp:
                        if img_resp.status != 200:
                            raise RuntimeError("Failed to download image")
                        return await img_resp.read()
                elif status == "pending":
                    await asyncio.sleep(delay)
                else:
                    raise RuntimeError(f"Unexpected status: {status_data}")

        raise RuntimeError("Image not ready after polling. Check your webhook server.")
