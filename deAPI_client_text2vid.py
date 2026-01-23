import os
import aiohttp
import asyncio

DEAPI_API_KEY = os.getenv("DEAPI_API_KEY_TEXT2VID", "").strip()
BASE_URL = "https://api.deapi.ai/api/v1/client"

TXT2VID_ENDPOINT = f"{BASE_URL}/txt2video"
RESULT_ENDPOINT = f"{BASE_URL}/results"

class Text2VidError(Exception):
    pass

async def text_to_video_512(
    *,
    prompt: str,
    guidance: float = 7.5,
    steps: int = 20,
    frames: int = 120,
    seed: int = 42,
    fps: int = 30,
    model: str = "Ltxv_13B_0_9_8_Distilled_FP8",
    negative_prompt: str | None = None,
    wait_time: float = 30.0,  # wait before fetching result
    timeout: int = 300,
):
    """
    Text-to-video generation at fixed 512x512 resolution.
    Returns raw video bytes (mp4).
    Fetches result only once, after `wait_time` seconds.
    """

    if not prompt or not prompt.strip():
        raise Text2VidError("Prompt is required")

    headers = {
        "Authorization": f"Bearer {DEAPI_API_KEY}",
        "Accept": "application/json",
    }

    # ── MULTIPART FORM (PER API SPEC) ───────────
    form = aiohttp.FormData()
    form.add_field("prompt", prompt)
    form.add_field("width", "512")
    form.add_field("height", "512")
    form.add_field("guidance", str(guidance))
    form.add_field("steps", str(steps))
    form.add_field("frames", str(frames))
    form.add_field("seed", str(seed))
    form.add_field("model", model)
    form.add_field("fps", str(fps))

    if negative_prompt:
        form.add_field("negative_prompt", negative_prompt)

    async with aiohttp.ClientSession(headers=headers) as session:
        # ── SUBMIT JOB ───────────────────────────
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
            raise Text2VidError("No request_id returned")

        # ── WAIT BEFORE FETCHING RESULT ──────────
        await asyncio.sleep(wait_time)

        # ── FETCH RESULT ONCE ───────────────────
        async with session.get(f"{RESULT_ENDPOINT}/{request_id}") as resp:
            if resp.status != 200:
                raise Text2VidError(f"Failed to fetch result ({resp.status})")

            result = await resp.json()

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
                return await vresp.read()

        if status in ("failed", "error"):
            raise Text2VidError(f"txt2video failed: {result}")

        # If not completed yet after 30 seconds
        raise Text2VidError(
            f"Video not ready after {wait_time} seconds. Current status: {status}"
        )
