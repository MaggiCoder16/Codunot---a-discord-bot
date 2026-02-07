import os
import aiohttp
import asyncio
import random
from typing import Optional

DEAPI_API_KEY = os.getenv("DEAPI_API_KEY", "").strip()
TXT2VID_ENDPOINT = "https://api.deapi.ai/api/v1/client/txt2video"
RESULT_URL_BASE = os.getenv("DEAPI_RESULT_BASE", "http://localhost:8000")  # Default to localhost

class Text2VidError(Exception):
    pass

async def _submit_job(
    session: aiohttp.ClientSession,
    *,
    prompt: str,
    frames: int,
    fps: int,
    model: str,
    negative_prompt: Optional[str],
) -> tuple[str, int]:

    seed = random.randint(0, 2**32 - 1)

    form = aiohttp.FormData()
    form.add_field("prompt", prompt)
    form.add_field("width", "512")
    form.add_field("height", "512")
    form.add_field("steps", "1")
    form.add_field("guidance", "0")
    form.add_field("frames", str(frames))
    form.add_field("fps", str(fps))
    form.add_field("seed", str(seed))
    form.add_field("model", model)

    if negative_prompt:
        form.add_field("negative_prompt", negative_prompt)

    # Add webhook URL
    WEBHOOK_URL = os.getenv("DEAPI_WEBHOOK_URL")
    if not WEBHOOK_URL:
        raise Text2VidError("DEAPI_WEBHOOK_URL is not set")
    form.add_field("webhook_url", WEBHOOK_URL)

    async with session.post(
        TXT2VID_ENDPOINT,
        data=form,
        timeout=aiohttp.ClientTimeout(total=60),
    ) as resp:
        print(
            f"[VIDEO GEN] x‑ratelimit‑limit: {resp.headers.get('x-ratelimit-limit')}, "
            f"x‑ratelimit‑remaining: {resp.headers.get('x-ratelimit-remaining')}"
        )

        if resp.status != 200:
            raise Text2VidError(
                f"txt2video submit failed ({resp.status}): {await resp.text()}"
            )

        payload = await resp.json()
        request_id = payload.get("data", {}).get("request_id")

        if not request_id:
            raise Text2VidError("No request_id returned from txt2video")

        print(f"[VIDEO GEN] Submitted | request_id={request_id} | seed={seed}")
        return request_id, seed


async def generate_video(
    *,
    prompt: str,
    negative_prompt: Optional[str] = None,
    model: str = "Ltxv_13B_0_9_8_Distilled_FP8",
    wait_for_result: bool = True,
) -> Optional[bytes]:
    """
    Submit a txt2video request to deAPI via webhook.
    If wait_for_result=True, polls /result endpoint using RESULT_URL_BASE until video is ready.
    Returns raw video bytes if polling; otherwise returns None.
    """
    if not DEAPI_API_KEY:
        raise Text2VidError("DEAPI_API_KEY_TEXT2VID is not set")

    if not prompt or not prompt.strip():
        raise Text2VidError("Prompt is required")

    headers = {
        "Authorization": f"Bearer {DEAPI_API_KEY}",
        "Accept": "application/json",
    }

    async with aiohttp.ClientSession(headers=headers) as session:
        request_id, seed = await _submit_job(
            session,
            prompt=prompt,
            frames=120,
            fps=30,
            model=model,
            negative_prompt=negative_prompt,
        )

    print(f"[VIDEO GEN] request_id={request_id} submitted. Video will be delivered to your webhook.")

    # ---------------------------
    # Optional polling for result
    # ---------------------------
    if wait_for_result and RESULT_URL_BASE:
        poll_url = f"{RESULT_URL_BASE}/result/{request_id}"
        print(f"[VIDEO GEN] Polling at: {poll_url}")

        async with aiohttp.ClientSession() as session:
            max_attempts = 30
            delay = 5  # seconds

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
                                raise Text2VidError("Job done but no result_url returned")

                            print(f"[VIDEO GEN] Video ready! Downloading from: {result_url}")

                            # Download video
                            async with session.get(result_url) as vresp:
                                if vresp.status != 200:
                                    raise Text2VidError(f"Failed to download video (status {vresp.status})")
                                return await vresp.read()

                        elif status == "pending":
                            print(f"[VIDEO GEN] Polling attempt {attempt + 1}/{max_attempts} - status: pending")
                            await asyncio.sleep(delay)
                        else:
                            raise Text2VidError(f"Unexpected status: {status_data}")

                except aiohttp.ClientError as e:
                    print(f"[VIDEO GEN] Network error on attempt {attempt + 1}: {e}")
                    await asyncio.sleep(delay)
                except Exception as e:
                    print(f"[VIDEO GEN] Error on attempt {attempt + 1}: {e}")
                    await asyncio.sleep(delay)

        raise Text2VidError(f"Video not ready after {max_attempts * delay} seconds. Check your webhook server.")

    return None  # webhook will deliver the video if wait_for_result=False
