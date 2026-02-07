import os
import aiohttp
import io
import random
import asyncio

DEAPI_API_KEY = os.getenv("DEAPI_API_KEY", "").strip()
RESULT_URL_BASE = os.getenv("DEAPI_RESULT_BASE", "http://localhost:8000")
if not DEAPI_API_KEY:
    raise RuntimeError("DEAPI_API_KEY not set")

IMG2IMG_URL = "https://api.deapi.ai/api/v1/client/img2img"
MODEL_NAME = "Flux_2_Klein_4B_BF16"
DEFAULT_STEPS = 4
MAX_STEPS = 50

async def edit_image(
    image_bytes: bytes,
    prompt: str,
    steps: int = DEFAULT_STEPS,
) -> bytes:
    """
    Submit an img2img job to deAPI and poll RESULT_URL_BASE until done.
    Returns raw PNG bytes.
    """
    seed = random.randint(1, 2**32 - 1)
    steps = min(steps, MAX_STEPS)
    prompt = (prompt or "").strip()

    headers = {
        "Authorization": f"Bearer {DEAPI_API_KEY}",
        "Accept": "application/json",
    }

    form = aiohttp.FormData()
    form.add_field(
        "image",
        io.BytesIO(image_bytes),
        filename="input.png",
        content_type="image/png",
    )
    form.add_field("prompt", prompt)
    form.add_field("model", MODEL_NAME)
    form.add_field("steps", str(steps))
    form.add_field("seed", str(seed))
    form.add_field("strength", "1.0")

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as session:
        # submit the job
        async with session.post(IMG2IMG_URL, data=form, headers=headers) as resp:
            # 🔎 print rate limit info from headers
            print(
                f"[deAPI EDIT] x‑ratelimit‑limit: {resp.headers.get('x-ratelimit-limit')}, "
                f"x‑ratelimit‑remaining: {resp.headers.get('x-ratelimit-remaining')}"
            )

            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"Image edit submission failed ({resp.status}): {text}")
            data = await resp.json()
            request_id = data.get("data", {}).get("request_id")
            if not request_id:
                raise RuntimeError(f"No request_id returned: {data}")

        # poll the result
        poll_url = f"{RESULT_URL_BASE}/result/{request_id}"
        print(f"[deAPI EDIT] Polling at: {poll_url}")

        max_attempts = 30
        delay = 5  # seconds
        for attempt in range(max_attempts):
            try:
                async with session.get(poll_url) as r:
                    if r.status != 200:
                        await asyncio.sleep(delay)
                        continue
                    status_data = await r.json()
                    status = status_data.get("status")

                    if status == "done":
                        result_url = status_data.get("result_url")
                        if not result_url:
                            raise RuntimeError("Edit done but no result_url returned")
                        async with session.get(result_url) as img_resp:
                            if img_resp.status != 200:
                                raise RuntimeError(f"Failed to download image (status {img_resp.status})")
                            return await img_resp.read()
                    elif status == "pending":
                        await asyncio.sleep(delay)
                    else:
                        raise RuntimeError(f"Unexpected status: {status_data}")
            except Exception as e:
                print(f"[deAPI EDIT] Polling attempt {attempt+1} error: {e}")
                await asyncio.sleep(delay)

        raise RuntimeError(f"Image not ready after {max_attempts * delay} seconds")
