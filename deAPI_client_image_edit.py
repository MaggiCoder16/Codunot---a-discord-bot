import os
import asyncio
import aiohttp
import io
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

IMG2IMG_URL = "https://api.deapi.ai/api/v1/client/img2img"
# Your webhook server base URL
RESULT_URL_BASE = os.getenv("DEAPI_RESULT_BASE", "http://localhost:8000") 

FLUX_MODEL = "Flux_2_Klein_4B_BF16"

DEFAULT_STEPS = 4
MAX_STEPS = 4

# ============================================================
# UTILITIES
# ============================================================

async def _poll_result(session: aiohttp.ClientSession, request_id: str) -> bytes:
    """Helper to poll your webhook server for the result."""
    poll_url = f"{RESULT_URL_BASE}/result/{request_id}"
    max_attempts = 40
    delay = 3

    for attempt in range(max_attempts):
        try:
            async with session.get(poll_url) as r:
                if r.status != 200:
                    await asyncio.sleep(delay)
                    continue

                status_data = await r.json()
                status = status_data.get("status")

                if status == "done":
                    result_url = status_data.get("result_url") or status_data.get("data", {}).get("result_url")
                    if not result_url:
                        raise RuntimeError("Job done but no result_url")
                    
                    async with session.get(result_url) as img_resp:
                        if img_resp.status != 200:
                            raise RuntimeError(f"Download failed: {img_resp.status}")
                        return await img_resp.read()

                elif status == "pending":
                    print(f"[deAPI Poll] Attempt {attempt + 1}/{max_attempts}: pending...")
                    await asyncio.sleep(delay)
                else:
                    raise RuntimeError(f"Unexpected status: {status}")
        except Exception as e:
            print(f"[deAPI Poll] Error: {e}")
            await asyncio.sleep(delay)

    raise RuntimeError("Polling timed out. Check your webhook server.")

# ============================================================
# IMAGE GENERATION (WEBHOOK + POLL RESULT)
# ============================================================

async def edit_image(image_bytes: bytes, prompt: str = "", steps: int = DEFAULT_STEPS) -> bytes:
    """Submit a single-image Flux img2img request."""
    steps = min(int(steps or DEFAULT_STEPS), MAX_STEPS)
    seed = random.randint(1, 2**32 - 1)

    # Added Accept header required by deAPI
    headers = {
        "Authorization": f"Bearer {DEAPI_API_KEY}",
        "Accept": "application/json"
    }

    payload = {
        "model": FLUX_MODEL,
        "prompt": prompt.strip() or "high quality image edit",
        "steps": steps,
        "seed": seed,
        "webhook_url": WEBHOOK_URL,
    }

    form = aiohttp.FormData()
    form.add_field("image", image_bytes, filename="input.jpg", content_type="image/jpeg")
    for k, v in payload.items():
        form.add_field(k, str(v))

    async with aiohttp.ClientSession() as session:
        async with session.post(IMG2IMG_URL, data=form, headers=headers) as resp:
            print(f"[deAPI IMG2IMG] Status: {resp.status} | RPM: {resp.headers.get('x-ratelimit-remaining')}")
            if resp.status != 200:
                raise RuntimeError(await resp.text())
            data = await resp.json()

        request_id = data["data"]["request_id"]
        return await _poll_result(session, request_id)


async def merge_images(images: list[bytes], prompt: str = "", steps: int = DEFAULT_STEPS) -> bytes:
    """Submit a multi-image Flux merge request."""
    if len(images) < 2:
        raise ValueError("merge_images requires at least 2 images")

    steps = min(int(steps or DEFAULT_STEPS), MAX_STEPS)
    seed = random.randint(1, 2**32 - 1)

    headers = {
        "Authorization": f"Bearer {DEAPI_API_KEY}",
        "Accept": "application/json"
    }

    payload = {
        "model": FLUX_MODEL,
        "prompt": prompt.strip() or "A high quality merge of these subjects",
        "steps": steps,
        "seed": seed,
        "webhook_url": WEBHOOK_URL,
    }

    form = aiohttp.FormData()
    for i, img in enumerate(images):
        form.add_field("images[]", img, filename=f"input_{i}.jpg", content_type="image/jpeg")
    
    for k, v in payload.items():
        form.add_field(k, str(v))

    async with aiohttp.ClientSession() as session:
        async with session.post(IMG2IMG_URL, data=form, headers=headers) as resp:
            print(f"[deAPI Merge] Status: {resp.status} | RPM: {resp.headers.get('x-ratelimit-remaining')}")
            if resp.status != 200:
                raise RuntimeError(await resp.text())
            data = await resp.json()

        request_id = data["data"]["request_id"]
        return await _poll_result(session, request_id)
