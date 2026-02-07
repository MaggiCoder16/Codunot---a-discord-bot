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
RESULT_URL_BASE = os.getenv("DEAPI_RESULT_BASE", "http://localhost:8000")  # Default to localhost

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
        poll_url = f"{RESULT_URL_BASE}/result/{request_id}"
        print(f"[deAPI] Polling at: {poll_url}")

        max_attempts = 30
        delay = 5  # seconds between polls

        for attempt in range(max_attempts):
            try:
                async with session.get(poll_url) as r:
                    if r.status != 200:
                        print(f"[deAPI] Poll attempt {attempt + 1} failed with status {r.status}")
                        await asyncio.sleep(delay)
                        continue
                        
                    status_data = await r.json()
                    status = status_data.get("status")
                    
                    if status == "done":
                        result_url = status_data.get("result_url")
                        if not result_url:
                            raise RuntimeError("Job done but no result_url returned")
                        
                        print(f"[deAPI] Image ready! Downloading from: {result_url}")
                        
                        # Download image
                        async with session.get(result_url) as img_resp:
                            if img_resp.status != 200:
                                raise RuntimeError(f"Failed to download image (status {img_resp.status})")
                            return await img_resp.read()
                    
                    elif status == "pending":
                        print(f"[deAPI] Polling attempt {attempt + 1}/{max_attempts} - status: pending")
                        await asyncio.sleep(delay)
                    else:
                        raise RuntimeError(f"Unexpected status: {status_data}")
                        
            except aiohttp.ClientError as e:
                print(f"[deAPI] Network error on attempt {attempt + 1}: {e}")
                await asyncio.sleep(delay)
            except Exception as e:
                print(f"[deAPI] Error on attempt {attempt + 1}: {e}")
                await asyncio.sleep(delay)

        raise RuntimeError(f"Image not ready after {max_attempts * delay} seconds. Check your webhook server.")
