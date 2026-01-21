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


async def download_image(session: aiohttp.ClientSession, url: str) -> bytes:
    async with session.get(url) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Failed to download image: {resp.status}")
        return await resp.read()


async def edit_image(
    image_bytes: bytes,
    prompt: str,
    steps: int = DEFAULT_STEPS,
    seed: int | None = None,
    strength: float = 0.5,
) -> bytes:
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

            # Direct image
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
    timeout: int = 180,
) -> bytes:
    headers = {"Authorization": f"Bearer {DEAPI_API_KEY}"}

    for attempt in range(timeout):
        async with session.get(
            f"{REQUEST_STATUS_URL}/{request_id}",
            headers=headers,
        ) as resp:

            if resp.status != 200:
                await asyncio.sleep(1)
                continue

            try:
                data = await resp.json()
            except Exception:
                await asyncio.sleep(1)
                continue

            payload = data.get("data", {})
            status = payload.get("status")

            print(f"[DEBUG] Poll attempt {attempt}, status: {status}")

            if status == "done":
                # Base64 result
                image_b64 = payload.get("result") or payload.get("image")
                if image_b64:
                    return base64.b64decode(image_b64)

                # URL result (most common for merges)
                result_url = payload.get("result_url")
                if result_url:
                    return await download_image(session, result_url)

                raise RuntimeError(f"Done but no image data: {data}")

            if status in ("pending", "processing", "queued"):
                await asyncio.sleep(1)
                continue

            if status == "error":
                raise RuntimeError(f"DeAPI img2img failed: {data}")

        await asyncio.sleep(1)

    raise RuntimeError("Timed out waiting for DeAPI image result")
