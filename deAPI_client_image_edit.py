# deAPI_client_image_edit.py

import os
import aiohttp
import random
import io
import base64

DEAPI_API_KEY = os.getenv("DEAPI_API_KEY_IMAGE_EDITING", "").strip()
if not DEAPI_API_KEY:
    raise RuntimeError("DEAPI_API_KEY_IMAGE_EDITING not set")

IMG2IMG_URL = "https://api.deapi.ai/api/v1/client/img2img"

MODEL_NAME = "QwenImageEdit_Plus_NF4"
DEFAULT_STEPS = 18
MAX_STEPS = 40


async def edit_image(
    image_bytes: bytes,
    prompt: str,
    steps: int = DEFAULT_STEPS,
    seed: int | None = None
) -> bytes:
    """
    Send image + prompt to DeAPI Qwen img2img and return raw PNG bytes.
    """
    steps = min(int(steps), MAX_STEPS)
    seed = seed or random.randint(1, 2**32 - 1)
    safe_prompt = prompt.replace("\n", " ").replace("\r", " ").strip()

    headers = {
        "Authorization": f"Bearer {DEAPI_API_KEY}",
        "Accept": "application/json",
    }

    form = aiohttp.FormData()
    form.add_field("image", io.BytesIO(image_bytes), filename="input.png", content_type="image/png")
    form.add_field("prompt", safe_prompt)
    form.add_field("model", MODEL_NAME)
    form.add_field("steps", str(steps))
    form.add_field("seed", str(seed))

    timeout = aiohttp.ClientTimeout(total=120)  # 2 min max

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(IMG2IMG_URL, data=form, headers=headers) as resp:
            body = await resp.read()
            content_type = resp.headers.get("Content-Type", "")

            if content_type.startswith("image/"):
                return body

            try:
                data = await resp.json()
            except Exception:
                raise RuntimeError(f"Failed to parse JSON: {body.decode(errors='ignore')}")

            # If JSON contains base64 image
            image_b64 = None
            if "image" in data:
                image_b64 = data["image"]
            elif "data" in data and "image" in data["data"]:
                image_b64 = data["data"]["image"]

            if image_b64:
                return base64.b64decode(image_b64)

            # If DeAPI returned a request_id (async), poll it
            request_id = data.get("data", {}).get("request_id")
            if request_id:
                return await poll_deapi_result(session, request_id)

            raise RuntimeError(f"No image returned by DeAPI: {data}")


async def poll_deapi_result(session, request_id, timeout=60) -> bytes:
    """
    Poll DeAPI img2img result until ready. Only used if request_id exists.
    """
    headers = {"Authorization": f"Bearer {DEAPI_API_KEY}"}

    for _ in range(timeout):
        async with session.get(f"{IMG2IMG_URL}/result/{request_id}", headers=headers) as resp:
            if resp.status != 200:
                await asyncio.sleep(1)
                continue

            try:
                data = await resp.json()
            except Exception:
                await asyncio.sleep(1)
                continue

            # Image in response
            image_b64 = data.get("image") or data.get("data", {}).get("image")
            if image_b64:
                return base64.b64decode(image_b64)

            # Status check
            status = data.get("data", {}).get("status")
            if status in ("pending", "processing", "queued"):
                await asyncio.sleep(1)
                continue

            if status == "failed":
                raise RuntimeError(f"DeAPI img2img failed: {data}")

        await asyncio.sleep(1)

    raise RuntimeError("Timed out waiting for DeAPI image result")
