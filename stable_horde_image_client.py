import aiohttp
import io
import base64
import os

STABLE_HORDE_URL = "https://stablehorde.net/api/v2/generate/text2img"
STABLE_HORDE_API_KEY = os.getenv("STABLE_HORDE_API_KEY", "")

async def generate_image_horde(prompt: str, *, diagram: bool = False) -> bytes:
    """
    Generate an image using Stable Horde (free).
    
    Args:
        prompt (str): The text prompt for image generation.
        diagram (bool): If True, modifies the prompt to create a clean educational diagram.

    Returns:
        bytes: PNG image bytes.
    """
    # Optional diagram style
    if diagram:
        prompt = (
            "Clean educational diagram, flat vector style, "
            "white background, clear black text labels, arrows, "
            "simple shapes, top-to-bottom layout, "
            "no realism, no shadows, no textures.\n\n"
            f"{prompt}"
        )

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
                raise RuntimeError(f"Stable Horde failed with status {resp.status}: {text}")
            data = await resp.json()

    # Decode base64 image
    try:
        image_b64 = data["generations"][0]["img"]
    except (KeyError, IndexError):
        raise RuntimeError("No image returned from Stable Horde")

    return base64.b64decode(image_b64)
