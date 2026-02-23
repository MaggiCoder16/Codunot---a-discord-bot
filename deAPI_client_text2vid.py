import os
import aiohttp
import asyncio
import random
import logging
from typing import Optional

DEAPI_API_KEY = os.getenv("DEAPI_API_KEY", "").strip()
TXT2VID_ENDPOINT = "https://api.deapi.ai/api/v1/client/txt2video"
RESULT_URL_BASE = os.getenv("DEAPI_RESULT_BASE", "http://localhost:8000")
logger = logging.getLogger(__name__)

class Text2VidError(Exception):
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

async def _submit_job(session: aiohttp.ClientSession, *, prompt: str, model: str) -> tuple[str, int]:
    seed = random.randint(0, 2**32 - 1)
    form = aiohttp.FormData()
    form.add_field("prompt", prompt)
    form.add_field("width", "512")
    form.add_field("height", "512")
    form.add_field("frames", "121")
    form.add_field("fps", "24")
    form.add_field("steps", "8")
    form.add_field("guidance", "1")
    form.add_field("seed", str(seed))
    form.add_field("model", model)

    webhook_url = os.getenv("DEAPI_WEBHOOK_URL")
    if not webhook_url:
        raise Text2VidError("DEAPI_WEBHOOK_URL is not set")
    form.add_field("webhook_url", webhook_url)

    async with session.post(TXT2VID_ENDPOINT, data=form, timeout=aiohttp.ClientTimeout(total=120)) as resp:
        if resp.status != 200:
            raise Text2VidError(f"txt2video submit failed ({resp.status}): {await resp.text()}")
        payload = await resp.json()
        request_id = payload.get("data", {}).get("request_id")
        if not request_id:
            raise Text2VidError("No request_id returned from txt2video")
        print(f"[VIDEO GEN] Submitted | request_id={request_id} | seed={seed}")
        return request_id, seed

async def generate_video(*, prompt: str, model: str = "Ltx2_19B_Dist_FP8", wait_for_result: bool = True) -> Optional[bytes]:
    if not DEAPI_API_KEY:
        raise Text2VidError("DEAPI_API_KEY is not set")
    if not prompt.strip():
        raise Text2VidError("Prompt is required")

    headers = {"Authorization": f"Bearer {DEAPI_API_KEY}", "Accept": "application/json"}

    async with aiohttp.ClientSession(headers=headers) as session:
        await warm_webhook_server()
        request_id, seed = await _submit_job(session, prompt=prompt, model=model)

        if wait_for_result and RESULT_URL_BASE:
            poll_url = f"{RESULT_URL_BASE}/result/{request_id}"
            max_attempts = 60
            delay = 5

            async with aiohttp.ClientSession() as session:
                for attempt in range(max_attempts):
                    await asyncio.sleep(delay)
                    try:
                        async with session.get(poll_url) as res:
                            if res.status != 200:
                                logger.info("[VIDEO GEN] Poll attempt %s not ready (HTTP %s)", attempt + 1, res.status)
                                continue
                            status_data = await res.json()
                            result_url = (
                                status_data.get("result_url")
                                or status_data.get("data", {}).get("result_url")
                                or status_data.get("raw", {}).get("result_url")
                            )
                            if result_url:
                                print("[VIDEO GEN] Result received:", result_url)
                                async with session.get(result_url) as vresp:
                                    if vresp.status != 200:
                                        raise Text2VidError(f"Failed to download video (status {vresp.status})")
                                    return await vresp.read()
                    except Exception as e:
                        logger.exception("[VIDEO GEN] Polling/download error on attempt %s: %s", attempt + 1, e)
                        continue
            raise Text2VidError("Video not ready after polling timeout. Check your webhook server.")
    return None
