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
# PUBLIC IMAGE GENERATOR (DEBUG-READY)
# ============================================================
async def generate_image_horde(prompt: str, *, diagram: bool = False) -> bytes:
    """
    Generate an image using Stable Horde.
    Returns raw PNG bytes.
    Logs request, response, and errors for debugging.
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

    # --- Log payload ---
    print("[Stable Horde] Sending payload:", payload)

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(STABLE_HORDE_URL, json=payload, headers=headers, timeout=120) as resp:
                text = await resp.text()
                if resp.status != 200:
                    print(f"[Stable Horde ERROR] Status {resp.status}: {text}")
                    raise RuntimeError(f"[Stable Horde] Failed with status {resp.status}: {text}")

                # Try parsing JSON
                try:
                    data = await resp.json()
                except Exception as e:
                    print("[Stable Horde ERROR] Failed to parse JSON:", e, "Response text:", text)
                    raise

                # --- Log raw response ---
                print("[Stable Horde] Raw response:", data)

        except Exception as e:
            print("[Stable Horde ERROR] Request failed:", e)
            raise

    # Extract and decode image
    try:
        img_b64 = data["generations"][0]["img"]
        if not img_b64:
            print("[Stable Horde ERROR] 'img' field empty in response:", data)
            raise RuntimeError("[Stable Horde] Image field is empty")

        print("[Stable Horde] Image generated successfully")
        return base64.b64decode(img_b64)

    except (KeyError, IndexError) as e:
        print(f"[Stable Horde ERROR] {e} - full response: {data}")
        raise RuntimeError("[Stable Horde] No image returned from API")
