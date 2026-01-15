import os
import asyncio
import aiohttp
import io
import re
import random

# ============================================================
# CONFIG
# ============================================================

DEAPI_API_KEY = os.getenv("DEAPI_API_KEY")
if not DEAPI_API_KEY:
    raise RuntimeError("DEAPI_API_KEY not set")

MODEL_NAME = "Flux1schnell"  # use the slug
DEFAULT_STEPS = 4
DEFAULT_WIDTH = 768
DEFAULT_HEIGHT = 768

# ============================================================
# PROMPT HELPERS
# ============================================================

def build_diagram_prompt(user_text: str) -> str:
    return (
        "Simple clean diagram, flat vector style, white background, "
        "clear labels, arrows, minimal design, educational, no realism.\n\n"
        + user_text
    )

def clean_prompt(prompt: str) -> str:
    if not prompt or not prompt.strip():
        return "A clean, simple diagram"  # fallback if empty
    prompt = re.sub(r'[\r\n]+', ' ', prompt.strip())
    return prompt[:900]

# ============================================================
# IMAGE GENERATION
# ============================================================

async def generate_image(
    prompt: str,
    aspect_ratio: str = "1:1",
    steps: int = DEFAULT_STEPS
) -> bytes:
    """
    Generate image using deAPI (Flux1schnell or other models).
    Returns raw PNG bytes.
    """

    prompt = clean_prompt(prompt)

    width = height = DEFAULT_WIDTH
    if aspect_ratio == "16:9":
        width, height = 768, 432
    elif aspect_ratio == "9:16":
        width, height = 432, 768
    elif aspect_ratio == "1:2":
        width, height = 384, 768

    async with aiohttp.ClientSession() as session:
        # 1️⃣ Send generation request
        payload = {
            "model": MODEL_NAME,
            "prompt": prompt,
            "width": width,
            "height": height,
            "steps": steps,
            "negative_prompt": "",
            "seed": random.randint(1, 2**32 - 1)  # let deAPI generate a random seed
        }
        headers = {"Authorization": f"Bearer {DEAPI_API_KEY}"}

        async with session.post(
            "https://api.deapi.ai/api/v1/client/txt2img",
            json=payload,
            headers=headers
        ) as resp:
            if resp.status == 422:
                text = await resp.text()
                print(f"❌ API validation error: {text}")
            resp.raise_for_status()
            data = await resp.json()

        request_id = data.get("data", {}).get("request_id")
        if not request_id:
            raise RuntimeError(f"deAPI did not return a request_id: {data}")

        # 2️⃣ Poll for the result
        for _ in range(60):  # wait max ~30s (0.5s interval)
            async with session.get(
                f"https://api.deapi.ai/api/v1/client/txt2img/{request_id}",
                headers=headers
            ) as poll_resp:
                poll_data = await poll_resp.json()
                status = poll_data.get("data", {}).get("status")
                if status == "succeeded":
                    image_base64 = poll_data["data"]["result"]["image_base64"]
                    return io.BytesIO(base64.b64decode(image_base64)).getvalue()
                elif status == "failed":
                    raise RuntimeError(f"deAPI image generation failed: {poll_data}")
            await asyncio.sleep(0.5)

        raise RuntimeError("deAPI image generation timed out")
