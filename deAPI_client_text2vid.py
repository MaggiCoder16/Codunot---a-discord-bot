import os
import aiohttp
import asyncio
import random

DEAPI_API_KEY = os.getenv("DEAPI_API_KEY_TEXT2VID", "").strip()
BASE_URL = "https://api.deapi.ai/api/v1/client"

TXT2VID_ENDPOINT = f"{BASE_URL}/txt2video"
RESULT_ENDPOINT = f"{BASE_URL}/results"

class Text2VidError(Exception):
    pass

async def text_to_video_512(
    *,
    prompt: str,
    frames: int = 120,   # 4 seconds at 30 fps
    fps: int = 30,
    model: str = "Ltxv_13B_0_9_8_Distilled_FP8",
    negative_prompt: str | None = None,
    poll_delay: float = 30.0,  # wait 30s before fetching
):
    if not prompt or not prompt.strip():
        raise Text2VidError("Prompt is required")

    headers = {
        "Authorization": f"Bearer {DEAPI_API_KEY}",
        "Accept": "application/json",
    }

    seed = random.randint(1, 2**32 - 1)

    form = aiohttp.FormData()
    form.add_field("prompt", prompt)
    form.add_field("width", "512")
    form.add_field("height", "512")
    form.add_field("steps", "1")       # model limit
    form.add_field("guidance", "0")    # model limit
    form.add_field("frames", str(frames))
    form.add_field("fps", str(fps))
    form.add_field("model", model)
    form.add_field("seed", str(seed))  # random seed
    if negative_prompt:
        form.add_field("negative_prompt", negative_prompt)

    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.post(TXT2VID_ENDPOINT, data=form, timeout=aiohttp.ClientTimeout(total=60)) as resp:
            if resp.status != 200:
                raise Text2VidError(f"txt2video submit failed ({resp.status}): {await resp.text()}")

            payload = await resp.json()
            request_id = payload.get("data", {}).get("request_id")
            if not request_id:
                raise Text2VidError("No request_id returned")
            print(f"[VIDEO GEN] Request submitted. request_id = {request_id}, seed = {seed}")

        await asyncio.sleep(poll_delay)

        async with session.get(f"{RESULT_ENDPOINT}/{request_id}") as resp:
            if resp.status != 200:
                raise Text2VidError(f"Failed to fetch result ({resp.status}) for request_id={request_id}")

            result = await resp.json()

        status = result.get("data", {}).get("status")
        if status != "completed":
            raise Text2VidError(f"Video generation not completed (status={status}) for request_id={request_id}")

        video_url = result.get("data", {}).get("output", {}).get("video_url")
        if not video_url:
            raise Text2VidError(f"No video_url found for request_id={request_id}")

        async with session.get(video_url) as vresp:
            if vresp.status != 200:
                raise Text2VidError(f"Failed to download video for request_id={request_id}")
            return await vresp.read()
