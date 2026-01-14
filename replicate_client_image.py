import os
import io
import asyncio
import replicate
import requests
from PIL import Image

# ============================================================
# CONFIG
# ============================================================

REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN", "")
if not REPLICATE_API_TOKEN:
    raise ValueError("Please set your REPLICATE_API_TOKEN environment variable")

# Initialize client
client = replicate.Client(api_token=REPLICATE_API_TOKEN)

# ============================================================
# GOOGLE IMAGEN 4 FLAGSHIP
# ============================================================

# Specific version ID for Imagen 4
IMAGEN4_VERSION_ID = "573cdf74dfdf9b1a42fc327a3887f96caa6f1bf90d086511b486792152abb9d9"

# ============================================================
# PROMPT HELPER (for diagrams)
# ============================================================

def build_diagram_prompt(user_text: str) -> str:
    """
    Builds a clean, SD-style diagram prompt suitable for Imagen 4.
    """
    return (
        "Simple clean diagram, flat vector style, white background, "
        "clear labels, arrows, minimal design, educational, no realism.\n\n"
        f"{user_text}"
    )

# ============================================================
# ASYNC IMAGE GENERATION
# ============================================================

async def generate_image_replicate(prompt: str, aspect_ratio: str = "1:1", steps: int = 20) -> bytes | None:
    """
    Generate an image using Google Imagen 4 on Replicate.
    Returns raw PNG bytes, or None on failure.
    """
    loop = asyncio.get_event_loop()

    def sync_call():
        try:
            # Predict using the specific version ID
            version = client.models.get(IMAGEN4_VERSION_ID)
            output_urls = version.predict(
                prompt=prompt,
                aspect_ratio=aspect_ratio,
                num_inference_steps=steps
            )

            if not output_urls:
                print("[Replicate ERROR] No output URLs returned")
                return None

            # Take first URL
            img_url = output_urls[0]
            resp = requests.get(img_url)
            if resp.status_code != 200:
                print("[Replicate ERROR] Failed to fetch image from URL:", resp.status_code)
                return None

            return resp.content

        except Exception as e:
            print("[Replicate ERROR]", e)
            return None

    return await loop.run_in_executor(None, sync_call)
