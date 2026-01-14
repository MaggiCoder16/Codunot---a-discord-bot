import os
import io
import base64
import aiohttp
from PIL import Image

# ============================================================
# CONFIG
# ============================================================
STABLE_HORDE_API_KEY = os.getenv("STABLE_HORDE_API_KEY", "")
STABLE_HORDE_URL = "https://stablehorde.net/api/v2/generate/text2img"

# ============================================================
# PROMPT BUILDER (FOR DIAGRAMS)
# ============================================================
def build_diagram_prompt(user_text: str) -> str:
    """
    Returns a prompt suitable for educational diagrams.
    """
    return (
        "Clean educational diagram, flat vector style, "
        "white background, clear black text labels, arrows, "
        "simple shapes, top-to-bottom layout, "
        "no realism, no shadows, no textures.\n\n"
        f"{user_text}"
    )

# ============================================================
# PUBLIC IMAGE GENERATOR
# ============================================================
async def generate_image_horde(prompt: str, *, diagram: bool = False) -> bytes:
    """
    Generate an image using Stable Horde.
    Returns raw PNG bytes.
    """
    if diagram:
        prompt = build_diagram_prompt(prompt)

    headers = {"Content-Type": "application/json"}
    if STABLE_HORDE_API_KEY:
        headers["apikey"] = STABLE_HORDE_API_KEY

    payload = {
        "prompt": prompt,
        "params": {
            "steps": 25,
            "width": 512,
            "height": 512,
            "cfg_scale": 7.0,
            "sampler_name": "k_euler"
        },
        "nsfw": False
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(STABLE_HORDE_URL, json=payload, headers=headers, timeout=120) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"[Stable Horde] Failed with status {resp.status}: {text}")
            data = await resp.json()

    # Extract and decode image
    try:
        img_b64 = data["generations"][0]["img"]
        return base64.b64decode(img_b64)
    except (KeyError, IndexError):
        raise RuntimeError("[Stable Horde] No image returned from API")
