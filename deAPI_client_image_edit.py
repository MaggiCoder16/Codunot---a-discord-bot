import os
import aiohttp
import asyncio
import random
from typing import Optional

DEAPI_API_KEY = os.getenv("DEAPI_API_KEY_TEXT2VID", "").strip()
BASE_URL = "https://api.deapi.ai/api/v1/client"

TXT2VID_ENDPOINT = f"{BASE_URL}/txt2video"
RESULT_ENDPOINT = f"{BASE_URL}/results"


class Text2VidError(Exception):
    pass


async def _submit_job(
    session: aiohttp.ClientSession,
    *,
    prompt: str,
    guidance: float,
    steps: int,
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
    form.add_field("guidance", str(guidance))
    form.add_field("steps", str(steps))
    form.add_field("frames", str(frames))
    form.add_field("fps", str(fps))
    form.add_field("seed", str(seed))
    form.add_field("model", model)

    if negative_prompt:
        form.add_field("negative_prompt", negative_prompt)

    async with session.post(
        TXT2VID_ENDPOINT,
        data=form,
        timeout=aiohttp.ClientTimeout(total=60),
    ) as resp:
        if resp.status != 200:
            raise Text2VidError(
                f"txt2video submit failed ({resp.status}): {await resp.text()}"
            )

        payload = await resp.json()
        request_id = payload.get("data", {}).get("request_id")

        if not request_id:
            raise Text2VidError("No request_id returned from txt2video")

        print(f"[VIDEO GEN] Submitted job | request_id={request_id} | seed={seed}")
        return request_id, seed


async def _poll_result(
    session: aiohttp.ClientSession,
    request_id: str,
    wait_seconds: int,
) -> Optional[dict]:

    await asyncio.sleep(wait_seconds)

    async with session.get(f"{RESULT_ENDPOINT}/{request_id}") as resp:
        if resp.status == 200:
            return await resp.json()
        if resp.status == 404:
            return None
        raise Text2VidError(
            f"Unexpected status while polling ({resp.status}): {await resp.text()}"
        )


async def text_to_video_512(
    *,
    prompt: str,
    guidance: float = 7.5,
    steps: int = 20,
    frames: int = 120,
    fps: int = 30,
    model: str = "Ltxv_13B_0_9_8_Distilled_FP8",
    negative_prompt: Optional[str] = None,
) -> bytes:

    if not DEAPI_API_KEY:
        raise Text2VidError("DEAPI_API_KEY_TEXT2VID is not set")

    if not prompt or not prompt.strip():
        raise Text2VidError("Prompt is required")

    headers = {
        "Authorization": f"Bearer {DEAPI_API_KEY}",
        "Accept": "application/json",
    }

    async with aiohttp.ClientSession(headers=headers) as session:
        for attempt in (1, 2):
            print(f"[VIDEO GEN] Attempt {attempt}/2")

            request_id, seed = await _submit_job(
                session,
                prompt=prompt,
                guidance=guidance,
                steps=steps,
                frames=frames,
                fps=fps,
                model=model,
                negative_prompt=negative_prompt,
            )

            result = await _poll_result(
                session,
                request_id=request_id,
                wait_seconds=180,
            )

            if result is None:
                print(
                    f"[VIDEO GEN] Result not found (404) | request_id={request_id}"
                )
                continue

            status = result.get("data", {}).get("status")

            if status == "completed":
                video_url = (
                    result.get("data", {})
                    .get("output", {})
                    .get("video_url")
                )

                if not video_url:
                    raise Text2VidError("Completed but no video_url")

                async with session.get(video_url) as vresp:
                    if vresp.status != 200:
                        raise Text2VidError("Failed to download video")

                    print(f"[VIDEO GEN] Success | request_id={request_id}")
                    return await vresp.read()

            if status in ("failed", "error"):
                raise Text2VidError(f"txt2video failed | payload={result}")

            raise Text2VidError(f"Unexpected status '{status}'")

        raise Text2VidError(
            "Video generation failed after 2 attempts (backend timeout)."
        )
