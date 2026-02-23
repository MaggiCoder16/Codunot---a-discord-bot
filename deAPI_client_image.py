import os
import asyncio
import aiohttp
import random
import logging
from typing import Optional

DEAPI_API_KEY = os.getenv("DEAPI_API_KEY", "").strip()
TXT2IMG_ENDPOINT = "https://api.deapi.ai/api/v1/client/txt2img"
RESULT_URL_BASE = os.getenv("DEAPI_RESULT_BASE", "http://localhost:8000")
logger = logging.getLogger(__name__)

class Text2ImgError(Exception):
    pass

async def warm_webhook_server():
    if not RESULT_URL_BASE:
        return
    try:
        async with aiohttp.ClientSession() as session:
            await session.get(RESULT_URL_BASE, timeout=5)
        print("[Warmup] Webhook server awake.")
    except Exception as e:
        logger.warning("[Warmup] Warmup skipped: %s", e)

async def _submit_job(
    session: aiohttp.ClientSession,
    *,
    prompt: str,
    model: str,
    aspect_ratio: str = "16:9",
    steps: int = 15,
) -> str:
    seed = random.randint(1, 2**32 - 1)
    payload = {
        "prompt": prompt,
        "model": model,
        "aspect_ratio": aspect_ratio,
        "steps": int(steps),
        "seed": seed,
        "webhook_url": f"{RESULT_URL_BASE}/webhook" if RESULT_URL_BASE else None,
    }
    async with session.post(TXT2IMG_ENDPOINT, json=payload) as resp:
        if resp.status != 200:
            raise Text2ImgError(f"Submission failed: {await resp.text()}")
        data = await resp.json()
        request_id = data.get("request_id") or data.get("data", {}).get("request_id")
        if not request_id:
            raise Text2ImgError("No request_id returned from txt2img")
        print(f"[IMAGE GEN] Submitted | request_id={request_id}")
        return request_id

async def generate_image(
    prompt: str,
    model: str = "ZImageTurbo_INT8",
    aspect_ratio: str = "16:9",
    steps: int = 15,
    wait_for_result: bool = True,
    max_retries: int = 60,
    delay: int = 5,
) -> Optional[bytes]:
    if not DEAPI_API_KEY:
        raise Text2ImgError("DEAPI_API_KEY not set")
    if not prompt.strip():
        raise Text2ImgError("Prompt is required")

    headers = {"Authorization": f"Bearer {DEAPI_API_KEY}", "Content-Type": "application/json"}

    async with aiohttp.ClientSession(headers=headers) as session:
        await warm_webhook_server()
        request_id = await _submit_job(
            session,
            prompt=prompt,
            model=model,
            aspect_ratio=aspect_ratio,
            steps=steps,
        )

        if wait_for_result and RESULT_URL_BASE:
            poll_url = f"{RESULT_URL_BASE}/result/{request_id}"

            for attempt in range(max_retries):
                await asyncio.sleep(delay)
                try:
                    async with session.get(poll_url) as res:
                        if res.status != 200:
                            logger.info("[IMAGE GEN] Poll attempt %s not ready (HTTP %s)", attempt + 1, res.status)
                            continue
                        status_data = await res.json()
                        result_url = (
                            status_data.get("result_url")
                            or status_data.get("data", {}).get("result_url")
                            or status_data.get("raw", {}).get("result_url")
                        )
                        if result_url:
                            print("[IMAGE GEN] Result received:", result_url)
                            async with session.get(result_url) as img_resp:
                                if img_resp.status != 200:
                                    raise Text2ImgError(f"Failed to download image (status {img_resp.status})")
                                return await img_resp.read()
                except Exception as e:
                    logger.exception("[IMAGE GEN] Polling/download error on attempt %s: %s", attempt + 1, e)
                    continue

            raise Text2ImgError("Image not ready after polling timeout. Check your webhook server.")
    return None
