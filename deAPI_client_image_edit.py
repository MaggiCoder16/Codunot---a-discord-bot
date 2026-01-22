import os
import aiohttp
import asyncio
import random
import io
import base64

DEAPI_API_KEY = os.getenv("DEAPI_API_KEY_IMAGE_EDITING", "").strip()
if not DEAPI_API_KEY:
    raise RuntimeError("DEAPI_API_KEY_IMAGE_EDITING not set")

IMG2IMG_URL = "https://api.deapi.ai/api/v1/client/img2img"
REQUEST_STATUS_URL = "https://api.deapi.ai/api/v1/client/request-status"
MODEL_NAME = "QwenImageEdit_Plus_NF4"
DEFAULT_STEPS = 18
MAX_STEPS = 40


async def edit_image(
    image_bytes: bytes,
    prompt: str,
    steps: int = DEFAULT_STEPS,
    seed: int | None = None,
    strength: float = 0.5,
) -> bytes:
    """
    Send image + prompt to DeAPI img2img and return raw image bytes.
    Handles direct image, base64, or async job with result_url.
    """
    steps = min(int(steps), MAX_STEPS)
    seed = seed or random.randint(1, 2**32 - 1)
    safe_prompt = prompt.replace("\n", " ").replace("\r", " ").strip()

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
    form.add_field("prompt", safe_prompt)
    form.add_field("model", MODEL_NAME)
    form.add_field("steps", str(steps))
    form.add_field("seed", str(seed))
    form.add_field("strength", str(strength))
    form.add_field("return_result_in_response", "true")

    timeout = aiohttp.ClientTimeout(total=180)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(IMG2IMG_URL, data=form, headers=headers) as resp:
            content_type = resp.headers.get("Content-Type", "")
            body = await resp.read()

            # Direct image response
            if content_type.startswith("image/"):
                return body

            try:
                data = await resp.json()
            except Exception:
                raise RuntimeError(
                    f"Failed to parse JSON: {body.decode(errors='ignore')}"
                )

            # Immediate base64 image
            image_b64 = data.get("image") or data.get("data", {}).get("image")
            if image_b64:
                return base64.b64decode(image_b64)

            # Async job
            request_id = data.get("data", {}).get("request_id")
            if request_id:
                return await poll_deapi_result(session, request_id)

            raise RuntimeError(f"No image returned by DeAPI: {data}")


async def poll_deapi_result(
    session: aiohttp.ClientSession,
    request_id: str,
    timeout: int = 180
) -> bytes:
    """
    Poll DeAPI request-status endpoint until image is ready.
    Supports result_url download.
    """
    headers = {"Authorization": f"Bearer {DEAPI_API_KEY}"}

    for attempt in range(timeout):
        async with session.get(
            f"{REQUEST_STATUS_URL}/{request_id}",
            headers=headers
        ) as resp:

            if resp.status != 200:
                await asyncio.sleep(1)
                continue

            data = await resp.json()
            payload = data.get("data", {})
            status = payload.get("status")

            print(f"[DEBUG] Poll attempt {attempt}, status: {status}")

            if status == "done":
                # Base64 result
                image_b64 = payload.get("result")
                if image_b64:
                    return base64.b64decode(image_b64)

                # URL result (MOST COMMON)
                result_url = payload.get("result_url")
                if result_url:
                    async with session.get(result_url) as img_resp:
                        if img_resp.status == 200:
                            return await img_resp.read()
                        raise RuntimeError(
                            f"Failed to download result image: {img_resp.status}"
                        )

                raise RuntimeError(f"Done but no image or URL: {payload}")

            if status in ("pending", "processing", "queued"):
                await asyncio.sleep(1)
                continue

            if status == "error":
                raise RuntimeError(f"DeAPI failed: {payload}")

        await asyncio.sleep(1)

    raise RuntimeError("Timed out waiting for DeAPI image result")
