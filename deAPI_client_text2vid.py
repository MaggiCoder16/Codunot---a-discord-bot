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
    prompt,
    guidance=0.0,     # LTX requires 0
    steps=1,          # LTX requires 1
    frames=120,       # 4 seconds @ 30 fps
    fps=30,
    model="Ltxv_13B_0_9_8_Distilled_FP8",
    negative_prompt=None,
):
    """
    Generate a 512x512 text-to-video clip.
    Returns raw video bytes (mp4).
    Polls up to 5 minutes total.
    """

    if not prompt or not prompt.strip():
        raise Text2VidError("Prompt is required")

    seed = random.randint(0, 2**32 - 1)

    headers = {
        "Authorization": f"Bearer {DEAPI_API_KEY}",
        "Accept": "application/json",
    }

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
        # ── SUBMIT JOB ──
        async with session.post(TXT2VID_ENDPOINT, data=form) as resp:
            text = await resp.text()
            if resp.status != 200:
                raise Text2VidError(f"txt2video submit failed ({resp.status}): {text}")

            payload = await resp.json()
            request_id = payload.get("data", {}).get("request_id")

            if not request_id:
                raise Text2VidError(f"No request_id returned. Payload: {payload}")

            print(f"[VIDEO GEN] Request submitted. request_id={request_id}, seed={seed}")

        # ── POLL #1 (150s) ──
        await asyncio.sleep(150)
        for attempt in (1, 2):
            async with session.get(f"{RESULT_ENDPOINT}/{request_id}") as resp:
                text = await resp.text()

                # 404 = still processing (EXPECTED)
                if resp.status == 404:
                    print(f"[VIDEO GEN] Poll {attempt}: still processing (404)")
                elif resp.status == 200:
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

                    print(f"[VIDEO GEN] Poll {attempt}: status={status}")
                else:
                    raise Text2VidError(
                        f"Unexpected status {resp.status} on poll {attempt}: {text}"
                    )

            # wait another 150s before second poll
            if attempt == 1:
                await asyncio.sleep(150)

        raise Text2VidError(
            f"Video not ready after 5 minutes. request_id={request_id}"
        )
