import os
import asyncio
import aiohttp
import io
import random

# ============================================================
# CONFIG
# ============================================================

DEAPI_API_KEY = os.getenv("DEAPI_API_KEY")
if not DEAPI_API_KEY:
    raise RuntimeError("DEAPI_API_KEY not set")

WEBHOOK_URL = os.getenv("DEAPI_WEBHOOK_URL")
if not WEBHOOK_URL:
    raise RuntimeError("DEAPI_WEBHOOK_URL not set")

IMG2IMG_URL = "https://api.deapi.ai/api/v1/client/img2img"
RESULT_URL_BASE = os.getenv("DEAPI_RESULT_BASE", "http://localhost:8000")  # webhook server

FLUX_MODEL = "Flux_2_Klein_4B_BF16"

DEFAULT_STEPS = 4
MAX_STEPS = 4

# ============================================================
# IMAGE GENERATION (WEBHOOK + POLL RESULT)
# ============================================================

async def edit_image(image_bytes: bytes, prompt: str = "", steps: int = DEFAULT_STEPS) -> bytes:
    """
    Submit a single-image Flux img2img request via webhook.
    Polls your /result endpoint until the image is ready.
    Returns raw PNG bytes.
    """
    steps = min(int(steps), MAX_STEPS)
    seed = random.randint(1, 2**32 - 1)

    headers = {"Authorization": f"Bearer {DEAPI_API_KEY}", "Content-Type": "application/json"}

    payload = {
        "model": FLUX_MODEL,
        "prompt": prompt.strip(),
        "steps": steps,
        "seed": seed,
        "webhook_url": WEBHOOK_URL,
    }

    form = aiohttp.FormData()
    form.add_field("image", io.BytesIO(image_bytes), filename="input.png", content_type="image/png")
    for k, v in payload.items():
        form.add_field(k, str(v))

    async with aiohttp.ClientSession() as session:
        # ---------------------------
        # SUBMIT JOB
        # ---------------------------
        async with session.post(IMG2IMG_URL, data=form, headers={"Authorization": f"Bearer {DEAPI_API_KEY}"}) as resp:
            print(
                "[deAPI IMG2IMG] "
                f"RPM limit: {resp.headers.get('x-ratelimit-limit')}, "
                f"RPM remaining: {resp.headers.get('x-ratelimit-remaining')} | "
                f"RPD limit: {resp.headers.get('x-ratelimit-daily-limit')}, "
                f"RPD remaining: {resp.headers.get('x-ratelimit-daily-remaining')}"
            )
            if resp.status != 200:
                raise RuntimeError(await resp.text())
            data = await resp.json()

        request_id = data["data"]["request_id"]
        print(f"[deAPI IMG2IMG] request_id={request_id} submitted. Waiting for webhook result...")

        # ---------------------------
        # POLLING LOOP
        # ---------------------------
        poll_url = f"{RESULT_URL_BASE}/result/{request_id}"
        print(f"[deAPI IMG2IMG] Polling at: {poll_url}")

        max_attempts = 30
        delay = 5

        for attempt in range(max_attempts):
            try:
                async with session.get(poll_url) as r:
                    if r.status != 200:
                        print(f"[deAPI IMG2IMG] Poll attempt {attempt + 1} failed with status {r.status}")
                        await asyncio.sleep(delay)
                        continue

                    status_data = await r.json()
                    status = status_data.get("status")

                    if status == "done":
                        result_url = status_data.get("result_url")
                        if not result_url:
                            raise RuntimeError("Job done but no result_url returned")
                        print(f"[deAPI IMG2IMG] Image ready! Downloading from: {result_url}")
                        async with session.get(result_url) as img_resp:
                            if img_resp.status != 200:
                                raise RuntimeError(f"Failed to download image (status {img_resp.status})")
                            return await img_resp.read()

                    elif status == "pending":
                        print(f"[deAPI IMG2IMG] Polling attempt {attempt + 1}/{max_attempts} - status: pending")
                        await asyncio.sleep(delay)
                    else:
                        raise RuntimeError(f"Unexpected status: {status_data}")

            except aiohttp.ClientError as e:
                print(f"[deAPI IMG2IMG] Network error on attempt {attempt + 1}: {e}")
                await asyncio.sleep(delay)
            except Exception as e:
                print(f"[deAPI IMG2IMG] Error on attempt {attempt + 1}: {e}")
                await asyncio.sleep(delay)

        raise RuntimeError(f"Image not ready after {max_attempts * delay} seconds. Check your webhook server.")


async def merge_images(images: list[bytes], prompt: str = "", steps: int = DEFAULT_STEPS) -> bytes:
    """
    Submit a multi-image Flux img2img request via webhook.
    Polls your /result endpoint until the image is ready.
    """
    if len(images) < 2:
        raise ValueError("merge_images requires at least 2 images")

    steps = min(int(steps), MAX_STEPS)
    seed = random.randint(1, 2**32 - 1)

    headers = {"Authorization": f"Bearer {DEAPI_API_KEY}", "Content-Type": "application/json"}

    payload = {
        "model": FLUX_MODEL,
        "prompt": prompt.strip(),
        "steps": steps,
        "seed": seed,
        "webhook_url": WEBHOOK_URL,
    }

    form = aiohttp.FormData()
    for i, img in enumerate(images):
        form.add_field("images[]", io.BytesIO(img), filename=f"input_{i}.png", content_type="image/png")
    for k, v in payload.items():
        form.add_field(k, str(v))

    async with aiohttp.ClientSession() as session:
        async with session.post(IMG2IMG_URL, data=form, headers={"Authorization": f"Bearer {DEAPI_API_KEY}"}) as resp:
            if resp.status != 200:
                raise RuntimeError(await resp.text())
            data = await resp.json()

        request_id = data["data"]["request_id"]
        print(f"[deAPI IMG2IMG] request_id={request_id} submitted. Waiting for webhook result...")

        # ---------------------------
        # POLLING LOOP
        # ---------------------------
        poll_url = f"{RESULT_URL_BASE}/result/{request_id}"
        print(f"[deAPI IMG2IMG] Polling at: {poll_url}")

        max_attempts = 30
        delay = 5

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
                            raise RuntimeError("Job done but no result_url returned")
                        async with session.get(result_url) as img_resp:
                            if img_resp.status != 200:
                                raise RuntimeError(f"Failed to download image (status {img_resp.status})")
                            return await img_resp.read()
                    elif status == "pending":
                        await asyncio.sleep(delay)
                    else:
                        raise RuntimeError(f"Unexpected status: {status_data}")
            except Exception as e:
                print(f"[deAPI IMG2IMG] Poll attempt {attempt + 1} error: {e}")
                await asyncio.sleep(delay)

        raise RuntimeError(f"Image not ready after {max_attempts * delay} seconds. Check your webhook server.")
