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

ASPECT_RATIO_DIMENSIONS = {
    "1:1": (768, 768),
    "16:9": (1024, 576),
    "9:16": (576, 1024),
    "4:3": (896, 672),
    "3:4": (672, 896),
}


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


def _dimensions_from_aspect_ratio(aspect_ratio: str) -> tuple[int, int]:
    ratio = (aspect_ratio or "1:1").strip()
    if ratio in ASPECT_RATIO_DIMENSIONS:
        return ASPECT_RATIO_DIMENSIONS[ratio]
    logger.warning("[IMAGE GEN] Unsupported aspect ratio '%s'; falling back to 1:1", ratio)
    return ASPECT_RATIO_DIMENSIONS["1:1"]


async def _submit_job(
    session: aiohttp.ClientSession,
    *,
    prompt: str,
    model: str,
    aspect_ratio: str = "16:9",
    steps: int = 8,
) -> str:
    width, height = _dimensions_from_aspect_ratio(aspect_ratio)
    seed = random.randint(1, 2**32 - 1)
    form = aiohttp.FormData()
    form.add_field("prompt", prompt)
    form.add_field("model", model)
    form.add_field("width", str(width))
    form.add_field("height", str(height))
    form.add_field("seed", str(seed))
    form.add_field("steps", str(int(steps)))
    form.add_field("negative_prompt", "")
    webhook_url = (f"{RESULT_URL_BASE}/webhook" if RESULT_URL_BASE else "").strip()
    if webhook_url:
        form.add_field("webhook_url", webhook_url)

    logger.info(
        "[IMAGE GEN] Submitting txt2img | model=%s width=%s height=%s steps=%s seed=%s",
        model,
        width,
        height,
        steps,
        seed,
    )

    async with session.post(TXT2IMG_ENDPOINT, data=form) as resp:
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
    steps: int = 8,
    wait_for_result: bool = True,
    max_retries: int = 60,
    delay: int = 5,
) -> Optional[bytes]:
    if not DEAPI_API_KEY:
        raise Text2ImgError("DEAPI_API_KEY not set")
    if not prompt.strip():
        raise Text2ImgError("Prompt is required")

    headers = {"Authorization": f"Bearer {DEAPI_API_KEY}", "Accept": "application/json"}

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
