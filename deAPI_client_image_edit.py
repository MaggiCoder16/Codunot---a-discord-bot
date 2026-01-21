# deAPI_client_image_edit.py
import os
import aiohttp
import asyncio
import random
import base64

DEAPI_API_KEY = os.getenv("DEAPI_API_KEY_IMAGE_EDITING", "").strip()
if not DEAPI_API_KEY:
    raise RuntimeError("DEAPI_API_KEY_IMAGE_EDITING not set")

# -------- ENDPOINTS --------
IMG2IMG_URL = "https://api.deapi.ai/api/v1/client/img2img"
IMG2IMG_RESULT_URL = "https://api.deapi.ai/api/v1/client/img2img/result"

MODEL_NAME = "QwenImageEdit_Plus_NF4"
DEFAULT_STEPS = 15
MAX_STEPS = 40


async def poll_deapi_result(session, request_id, timeout=60) -> bytes:
    """Poll DeAPI until the image is ready."""
    headers = {"Authorization": f"Bearer {DEAPI_API_KEY}"}

    for _ in range(timeout):
        async with session.get(f"{IMG2IMG_RESULT_URL}/{request_id}", headers=headers) as resp:
            if resp.status != 200:
                await asyncio.sleep(1)
                continue

            try:
                data = await resp.json()
            except Exception:
                await asyncio.sleep(1)
                continue

            # Correct path for returned image
            image_b64 = None
            if "image" in data:
                image_b64 = data["image"]
            elif "data" in data and "image" in data["data"]:
                image_b64 = data["data"]["image"]

            if image_b64:
                try:
                    return base64.b64decode(image_b64)
                except Exception as e:
                    raise RuntimeError(f"Failed to decode base64 image: {e}")

            status = data.get("data", {}).get("status")
            if status in ("pending", "processing", "queued"):
                await asyncio.sleep(1)
                continue

            if status == "failed":
                raise RuntimeError(f"DeAPI img2img failed: {data}")

        await asyncio.sleep(1)

    raise RuntimeError("Timed out waiting for DeAPI image result")


async def edit_image(
    image_bytes: bytes,
    prompt: str,
    steps: int = DEFAULT_STEPS,
    seed: int | None = None
) -> bytes:
    """Send image + prompt to DeAPI Qwen img2img and return PNG bytes."""
    steps = min(int(steps), MAX_STEPS)
    seed = seed or random.randint(1, 2**32 - 1)
    safe_prompt = prompt.replace("\n", " ").replace("\r", " ").strip()
    headers = {"Authorization": f"Bearer {DEAPI_API_KEY}"}

    form = aiohttp.FormData()
    form.add_field("image", image_bytes, filename="input.png", content_type="image/png")
    form.add_field("prompt", safe_prompt)
    form.add_field("model", MODEL_NAME)
    form.add_field("steps", str(steps))
    form.add_field("seed", str(seed))

    async with aiohttp.ClientSession() as session:
        async with session.post(IMG2IMG_URL, data=form, headers=headers) as resp:
            body = await resp.read()
            content_type = resp.headers.get("Content-Type", "")

            # If DeAPI returns raw image
            if content_type.startswith("image/"):
                return body

            # Try JSON
            try:
                data = await resp.json()
            except Exception:
                raise RuntimeError(f"Failed to parse JSON: {body.decode(errors='ignore')}")

            # Check top-level or nested image
            image_b64 = None
            if "image" in data:
                image_b64 = data["image"]
            elif "data" in data and "image" in data["data"]:
                image_b64 = data["data"]["image"]

            if image_b64:
                return base64.b64decode(image_b64)

            # Poll if request_id exists
            request_id = data.get("data", {}).get("request_id")
            if not request_id:
                raise RuntimeError(f"No image or request_id returned: {data}")

            return await poll_deapi_result(session, request_id)
