import os
import asyncio
import aiohttp
import io
import re
import random
import base64

# ============================================================
# CONFIG
# ============================================================

DEAPI_API_KEY = os.getenv("DEAPI_API_KEY")
if not DEAPI_API_KEY:
    raise RuntimeError("DEAPI_API_KEY not set")

MODEL_NAME = "Flux1schnell"  # slug from deAPI
DEFAULT_STEPS = 4
MAX_STEPS = 10  # hard limit enforced by deAPI
DEFAULT_WIDTH = 768
DEFAULT_HEIGHT = 768

TXT2IMG_URL = "https://api.deapi.ai/api/v1/client/txt2img"
POLL_URL = "https://api.deapi.ai/api/v1/client/inference"

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
        return "A clean, simple diagram"
    prompt = re.sub(r"[\r\n]+", " ", prompt.strip())
    return prompt[:900]

# ============================================================
# IMAGE GENERATION
# ============================================================

async def generate_image(
    prompt: str,
    aspect_ratio: str = "1:1",
    steps: int = DEFAULT_STEPS,
) -> bytes:
    """
    Generate image using deAPI (Flux1schnell).
    Returns raw PNG bytes.
    """

    prompt = clean_prompt(prompt)

    # Enforce step limit (CRITICAL)
    steps = min(int(steps), MAX_STEPS)

    # Determine width/height
    width = height = DEFAULT_WIDTH
    if aspect_ratio == "16:9":
        width, height = 768, 432
    elif aspect_ratio == "9:16":
        width, height = 432, 768
    elif aspect_ratio == "1:2":
        width, height = 384, 768

    headers = {
        "Authorization": f"Bearer {DEAPI_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "width": width,
        "height": height,
        "steps": steps,
        "negative_prompt": "",
        "seed": random.randint(1, 2**32 - 1),
    }

    async with aiohttp.ClientSession() as session:
        # ---------------- SEND REQUEST ----------------
        async with session.post(
            TXT2IMG_URL,
            json=payload,
            headers=headers,
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(
                    f"deAPI txt2img failed ({resp.status}): {text}"
                )

            data = await resp.json()

        request_id = data.get("data", {}).get("request_id")
        if not request_id:
            raise RuntimeError(f"No request_id returned: {data}")

        # ---------------- POLL RESULT ----------------
        # 2 minutes max (safe for Flux under load)
        for _ in range(120):
            async with session.get(
                f"{POLL_URL}/{request_id}",
                headers=headers,
            ) as poll_resp:
                if poll_resp.status == 404:
                    await asyncio.sleep(1)
                    continue

                poll_data = await poll_resp.json()
                status = poll_data.get("data", {}).get("status")

                # Debug aid (comment out if noisy)
                # print("[deAPI STATUS]", status)

                if status == "succeeded":
                    image_base64 = (
                        poll_data["data"]["result"]["image_base64"]
                    )
                    return base64.b64decode(image_base64)

                if status == "failed":
                    raise RuntimeError(
                        f"deAPI image generation failed: {poll_data}"
                    )

                # queued / processing / running → keep waiting
            await asyncio.sleep(1)

        raise RuntimeError("deAPI image generation timed out")
