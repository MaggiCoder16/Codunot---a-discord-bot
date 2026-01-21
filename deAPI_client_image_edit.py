# deAPI_client_image_edit.py

import os
import aiohttp
import random
import io

DEAPI_API_KEY = os.getenv("DEAPI_API_KEY_IMAGE_EDITING", "").strip()
if not DEAPI_API_KEY:
    raise RuntimeError("DEAPI_API_KEY_IMAGE_EDITING not set")

IMG2IMG_URL = "https://api.deapi.ai/api/v1/client/img2img"

MODEL_NAME = "QwenImageEdit_Plus_NF4"
DEFAULT_STEPS = 15
MAX_STEPS = 40


async def edit_image(
    image_bytes: bytes,
    prompt: str,
    steps: int = DEFAULT_STEPS,
    seed: int | None = None
) -> bytes:
    """
    Sends image + prompt to DeAPI img2img.
    Returns RAW PNG/JPEG BYTES.
    """

    steps = min(int(steps), MAX_STEPS)
    seed = seed or random.randint(1, 2**32 - 1)

    safe_prompt = prompt.replace("\n", " ").replace("\r", " ").strip()

    headers = {
        "Authorization": f"Bearer {DEAPI_API_KEY}",
    }

    form = aiohttp.FormData()
    form.add_field(
        name="image",
        value=io.BytesIO(image_bytes),
        filename="input.png",
        content_type="image/png"
    )
    form.add_field("prompt", safe_prompt)
    form.add_field("model", MODEL_NAME)
    form.add_field("steps", str(steps))
    form.add_field("seed", str(seed))

    timeout = aiohttp.ClientTimeout(total=120)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            IMG2IMG_URL,
            data=form,
            headers=headers
        ) as resp:

            if resp.status != 200:
                raise RuntimeError(await resp.text())

            return await resp.read()
