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

client = replicate.Client(api_token=REPLICATE_API_TOKEN)

DEFAULT_MODEL = "google/imagen-4-ultra"

# ============================================================
# PROMPT HELPER (for diagrams)
# ============================================================
def build_diagram_prompt(user_text: str) -> str:
    return (
        "Simple clean diagram, flat vector style, white background, "
        "clear labels, arrows, minimal design, educational, no realism.\n\n"
        f"{user_text}"
    )

# ============================================================
# IMAGE GENERATION
# ============================================================
async def generate_image_replicate(prompt: str, width: int = 512, height: int = 512, steps: int = 20) -> bytes | None:
    """
    Generate an image using Replicate. Returns PNG bytes or None on failure.
    """
    loop = asyncio.get_event_loop()

    def sync_call():
        try:
            # New API: get model, version, then predict
            model = client.models.get(DEFAULT_MODEL)
            version = model.versions.list()[0]  # latest version
            output_urls = version.predict(
                prompt=prompt,
                width=width,
                height=height,
                num_inference_steps=steps
            )
            if not output_urls:
                print("[Replicate ERROR] No output returned")
                return None

            # The model returns a list of URLs
            img_url = output_urls[0]
            resp = requests.get(img_url)
            if resp.status_code != 200:
                print("[Replicate ERROR] Failed to fetch image:", resp.status_code)
                return None

            return resp.content

        except Exception as e:
            print("[Replicate ERROR]", e)
            return None

    return await loop.run_in_executor(None, sync_call)
