import os
import aiohttp
import asyncio

# ============================================================
# CONFIG
# ============================================================

HF_API_KEY = os.getenv("HUGGINGFACE_API_KEY_IMAGE_GEN")
if not HF_API_KEY:
    raise RuntimeError("HUGGINGFACE_API_KEY_IMAGE_GEN not set")

HEADERS = {
    "Authorization": f"Bearer {HF_API_KEY}",
    "Accept": "image/png",
}

# Primary (best quality, slower)
HF_MODEL_PRIMARY = "stabilityai/stable-diffusion-xl-base-1.0"

# Fallback (faster, more reliable on free tier)
HF_MODEL_FALLBACK = "runwayml/stable-diffusion-v1-5"

HF_TIMEOUT = aiohttp.ClientTimeout(total=120)

# ============================================================
# PROMPT BUILDER (FOR DIAGRAMS)
# ============================================================

def build_diagram_prompt(user_text: str) -> str:
    """
    Converts user intent into a clean educational diagram prompt.
    """
    return (
        "Clean educational diagram, flat vector style, "
        "white background, clear black text labels, arrows, "
        "simple shapes, top-to-bottom layout, "
        "no realism, no shadows, no textures.\n\n"
        f"{user_text}"
    )

# ============================================================
# INTERNAL IMAGE REQUEST
# ============================================================

async def _request_image(
    model: str,
    prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    steps: int,
) -> bytes:
    url = f"https://api-inference.huggingface.co/models/{model}"

    payload = {
        "inputs": prompt,
        "parameters": {
            "negative_prompt": negative_prompt,
            "width": width,
            "height": height,
            "num_inference_steps": steps,
            "guidance_scale": 7.5,
        },
    }

    async with aiohttp.ClientSession(timeout=HF_TIMEOUT) as session:
        async with session.post(url, headers=HEADERS, json=payload) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"{model} failed ({resp.status}): {text}")

            return await resp.read()

# ============================================================
# PUBLIC IMAGE GENERATOR (WITH FALLBACK)
# ============================================================

async def generate_image_hf(
    prompt: str,
    *,
    diagram: bool = False,
    width: int = 1024,
    height: int = 1024,
    steps: int = 28,
) -> bytes:
    """
    Generates an image using Hugging Face.
    Automatically retries with a fallback model.
    """

    negative_prompt = (
        "blurry, low quality, distorted text, watermark, logo, "
        "photorealistic, shadows, textures, extra limbs"
    )

    if diagram:
        prompt = build_diagram_prompt(prompt)

    # --- Try primary model ---
    try:
        return await _request_image(
            HF_MODEL_PRIMARY,
            prompt,
            negative_prompt,
            width,
            height,
            steps,
        )
    except Exception as e:
        print(f"[HF PRIMARY FAILED] {e}")

    # --- Fallback ---
    try:
        return await _request_image(
            HF_MODEL_FALLBACK,
            prompt,
            negative_prompt,
            width,
            height,
            steps,
        )
    except Exception as e:
        print(f"[HF FALLBACK FAILED] {e}")
        raise RuntimeError("All Hugging Face image models failed")
