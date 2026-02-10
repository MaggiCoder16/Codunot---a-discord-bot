import aiohttp
import asyncio
import io
import random

# =====================
# CONFIG
# =====================

DEAPI_API_KEY = "<YOUR_API_KEY>"
MODEL_NAME = "flux-dev"
IMG2IMG_URL = "https://api.deapi.ai/v1/images/edits"
RESULT_URL_BASE = "https://api.deapi.ai/v1"

DEFAULT_STEPS = 30
MAX_STEPS = 50


# =====================
# PUBLIC API
# =====================

async def edit_image(
    image_bytes: bytes,
    prompt: str,
    steps: int = DEFAULT_STEPS,
) -> bytes:
    """
    Edit a SINGLE image using Flux img2img.
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

    return await _submit_and_poll(form, headers)


async def merge_images(
    images: list[bytes],
    prompt: str,
    steps: int = DEFAULT_STEPS,
) -> bytes:
    """
    Merge 2+ images using Flux multi-image conditioning.
    """
    if len(images) < 2:
        raise ValueError("merge_images requires at least 2 images")

    seed = random.randint(1, 2**32 - 1)
    steps = min(steps, MAX_STEPS)
    prompt = (prompt or "").strip()

    headers = {
        "Authorization": f"Bearer {DEAPI_API_KEY}",
        "Accept": "application/json",
    }

    form = aiohttp.FormData()

    for i, img in enumerate(images):
        form.add_field(
            "image",
            io.BytesIO(img),
            filename=f"input_{i}.png",
            content_type="image/png",
        )

    form.add_field("prompt", prompt)
    form.add_field("model", MODEL_NAME)
    form.add_field("steps", str(steps))
    form.add_field("seed", str(seed))

    return await _submit_and_poll(form, headers)


# =====================
# INTERNALS
# =====================

async def _submit_and_poll(
    form: aiohttp.FormData,
    headers: dict,
) -> bytes:
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=120)
    ) as session:

        # ---------------------------
        # SUBMIT JOB
        # ---------------------------
        async with session.post(IMG2IMG_URL, data=form, headers=headers) as resp:
            print(
                "[deAPI EDIT] "
                f"RPM limit: {resp.headers.get('x-ratelimit-limit')}, "
                f"RPM remaining: {resp.headers.get('x-ratelimit-remaining')} | "
                f"RPD limit: {resp.headers.get('x-ratelimit-daily-limit')}, "
                f"RPD remaining: {resp.headers.get('x-ratelimit-daily-remaining')}"
            )

            if resp.status != 200:
                raise RuntimeError(
                    f"Submission failed ({resp.status}): {await resp.text()}"
                )

            data = await resp.json()
            request_id = data.get("data", {}).get("request_id")
            if not request_id:
                raise RuntimeError(f"No request_id returned: {data}")

        # ---------------------------
        # POLLING LOOP
        # ---------------------------
        poll_url = f"{RESULT_URL_BASE}/result/{request_id}"
        print(f"[deAPI EDIT] Polling at: {poll_url}")

        delay = 5
        max_attempts = 30

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
                            raise RuntimeError("Done but no result_url returned")

                        async with session.get(result_url) as img_resp:
                            if img_resp.status != 200:
                                raise RuntimeError(
                                    f"Failed to download image ({img_resp.status})"
                                )
                            return await img_resp.read()

                    elif status == "pending":
                        await asyncio.sleep(delay)
                    else:
                        raise RuntimeError(f"Unexpected status: {status_data}")

            except Exception as e:
                print(f"[deAPI EDIT] Poll attempt {attempt + 1} error: {e}")
                await asyncio.sleep(delay)

        raise RuntimeError("Image not ready after timeout")
