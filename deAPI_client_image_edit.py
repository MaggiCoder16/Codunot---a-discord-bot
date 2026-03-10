import os
import asyncio
import aiohttp
import random
from typing import List

DEAPI_API_KEY = os.getenv("DEAPI_API_KEY", "").strip()
IMG2IMG_URL = "https://api.deapi.ai/api/v1/client/img2img"
RESULT_URL_BASE = os.getenv("DEAPI_RESULT_BASE", "http://localhost:8000")
FLUX_MODEL = "Flux_2_Klein_4B_BF16"
DEFAULT_STEPS = 4
MAX_STEPS = 4


async def warm_webhook_server():
    if not RESULT_URL_BASE:
        return
    for attempt in range(5):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    RESULT_URL_BASE,
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    if resp.status == 200:
                        print(f"[Warmup] Webhook server awake (attempt {attempt + 1})")
                        await asyncio.sleep(3)
                        return
        except Exception as e:
            print(f"[Warmup] Attempt {attempt + 1} failed: {e}")
            await asyncio.sleep(5)
    print("[Warmup] Warning: webhook server may not be ready")


async def _poll_result(session: aiohttp.ClientSession, request_id: str) -> bytes:
    poll_url = f"{RESULT_URL_BASE}/result/{request_id}"
    max_attempts = 40
    delay = 3
    for attempt in range(max_attempts):
        await asyncio.sleep(delay)
        try:
            async with session.get(poll_url) as r:
                if r.status != 200:
                    continue
                status_data = await r.json()
                result_url = (
                    status_data.get("result_url")
                    or status_data.get("data", {}).get("result_url")
                    or status_data.get("raw", {}).get("result_url")
                )
                if result_url:
                    async with session.get(result_url) as img_resp:
                        if img_resp.status != 200:
                            raise RuntimeError(f"Download failed: {img_resp.status}")
                        return await img_resp.read()
        except Exception:
            continue
    raise RuntimeError("Polling timed out. Check your webhook server.")


async def edit_image(image_bytes: bytes, prompt: str = "", steps: int = DEFAULT_STEPS) -> bytes:
    await warm_webhook_server()
    steps = min(int(steps or DEFAULT_STEPS), MAX_STEPS)
    seed = random.randint(1, 2**32 - 1)
    headers = {"Authorization": f"Bearer {DEAPI_API_KEY}", "Accept": "application/json"}
    payload = {
        "model": FLUX_MODEL,
        "prompt": prompt.strip() or "high quality image edit",
        "steps": steps,
        "seed": seed,
        "webhook_url": os.getenv("DEAPI_WEBHOOK_URL"),
    }
    form = aiohttp.FormData()
    form.add_field("image", image_bytes, filename="input.jpg", content_type="image/jpeg")
    for k, v in payload.items():
        form.add_field(k, str(v))
    async with aiohttp.ClientSession() as session:
        async with session.post(IMG2IMG_URL, data=form, headers=headers) as resp:
            if resp.status != 200:
                raise RuntimeError(await resp.text())
            data = await resp.json()
        request_id = data["data"]["request_id"]
        return await _poll_result(session, request_id)


async def merge_images(images: List[bytes], prompt: str = "", steps: int = DEFAULT_STEPS) -> bytes:
    await warm_webhook_server()
    if len(images) < 2:
        raise ValueError("merge_images requires at least 2 images")
    steps = min(int(steps or DEFAULT_STEPS), MAX_STEPS)
    seed = random.randint(1, 2**32 - 1)
    headers = {"Authorization": f"Bearer {DEAPI_API_KEY}", "Accept": "application/json"}
    payload = {
        "model": FLUX_MODEL,
        "prompt": prompt.strip() or "A high quality merge of these subjects",
        "steps": steps,
        "seed": seed,
        "webhook_url": os.getenv("DEAPI_WEBHOOK_URL"),
    }
    form = aiohttp.FormData()
    for i, img in enumerate(images):
        form.add_field("images[]", img, filename=f"input_{i}.jpg", content_type="image/jpeg")
    for k, v in payload.items():
        form.add_field(k, str(v))
    async with aiohttp.ClientSession() as session:
        async with session.post(IMG2IMG_URL, data=form, headers=headers) as resp:
            if resp.status != 200:
                raise RuntimeError(await resp.text())
            data = await resp.json()
        request_id = data["data"]["request_id"]
        return await _poll_result(session, request_id)
