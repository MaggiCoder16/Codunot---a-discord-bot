import os
import aiohttp
import asyncio
import random
import re
from typing import Optional

# ============================================================
# CONFIG
# ============================================================

DEAPI_API_KEY = os.getenv("DEAPI_API_KEY")
if not DEAPI_API_KEY:
    raise RuntimeError("DEAPI_API_KEY not set")

WEBHOOK_URL = os.getenv("DEAPI_WEBHOOK_URL")
if not WEBHOOK_URL:
    raise RuntimeError("DEAPI_WEBHOOK_URL not set")

MODEL_NAME = "Ltxv_13B_0_9_8_Distilled_FP8"

DEFAULT_FRAMES = 120
DEFAULT_FPS = 30
DEFAULT_WIDTH = 512
DEFAULT_HEIGHT = 512

TXT2VID_URL = "https://api.deapi.ai/api/v1/client/txt2video"
RESULT_URL_BASE = os.getenv("DEAPI_RESULT_BASE", "http://localhost:8000")  # your webhook server

# ============================================================
# PROMPT CLEANUP
# ============================================================

def clean_prompt(prompt: str) -> str:
    if not prompt or not prompt.strip():
        return "A simple animated scene"
    return re.sub(r"[\r\n]+", " ", prompt.strip())[:900]

# ============================================================
# VIDEO GENERATION (WEBHOOK + POLL RESULT)
# ============================================================

async def generate_video(
    prompt: str,
    negative_prompt: Optional[str] = None,
    frames: int = DEFAULT_FRAMES,
    fps: int = DEFAULT_FPS,
    model: str = MODEL_NAME,
) -> bytes:
    """
    Submit a txt2video request to deAPI via webhook.
    Polls /result endpoint until video is ready.
    Returns raw video bytes.
    """

    prompt = clean_prompt(prompt)

    headers = {
        "Authorization": f"Bearer {DEAPI_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "prompt": prompt,
        "width": DEFAULT_WIDTH,
        "height": DEFAULT_HEIGHT,
        "frames": frames,
        "fps": fps,
        "negative_prompt": negative_prompt or "",
        "seed": random.randint(1, 2**32 - 1),
        "webhook_url": WEBHOOK_URL,
    }

    async with aiohttp.ClientSession() as session:
        # ---------------------------
        # SUBMIT JOB
        # ---------------------------
        async with session.post(TXT2VID_URL, json=payload, headers=headers) as resp:
            if resp.status != 200:
                raise RuntimeError(await resp.text())
            data = await resp.json()

        request_id = data["data"]["request_id"]
        print(f"[VIDEO GEN] request_id={request_id} submitted. Waiting for webhook result...")

        # ---------------------------
        # POLLING LOOP
        # ---------------------------
        poll_url = f"{RESULT_URL_BASE}/result/{request_id}"
        max_attempts = 60
        delay = 5  # seconds between polls

        for attempt in range(max_attempts):
            try:
                async with session.get(poll_url) as r:
                    if r.status != 200:
                        print(f"[VIDEO GEN] Poll attempt {attempt + 1} failed with status {r.status}")
                        await asyncio.sleep(delay)
                        continue

                    status_data = await r.json()
                    status = status_data.get("status")

                    if status == "done":
                        result_url = status_data.get("result_url")
                        if not result_url:
                            raise RuntimeError("Job done but no result_url returned")

                        print(f"[VIDEO GEN] Video ready! Downloading from: {result_url}")

                        # Download video
                        async with session.get(result_url) as vresp:
                            if vresp.status != 200:
                                raise RuntimeError(f"Failed to download video (status {vresp.status})")
                            return await vresp.read()

                    elif status == "pending":
                        print(f"[VIDEO GEN] Poll attempt {attempt + 1}/{max_attempts} - status: pending")
                        await asyncio.sleep(delay)
                    else:
                        raise RuntimeError(f"Unexpected status: {status_data}")

            except aiohttp.ClientError as e:
                print(f"[VIDEO GEN] Network error on attempt {attempt + 1}: {e}")
                await asyncio.sleep(delay)
            except Exception as e:
                print(f"[VIDEO GEN] Error on attempt {attempt + 1}: {e}")
                await asyncio.sleep(delay)

        raise RuntimeError(f"Video not ready after {max_attempts * delay} seconds. Check your webhook server.")
