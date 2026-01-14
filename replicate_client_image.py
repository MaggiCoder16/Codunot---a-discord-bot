import os
import io
import asyncio
import replicate
from PIL import Image
import requests

# ============================================================
# CONFIG
# ============================================================

REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN", "")
if not REPLICATE_API_TOKEN:
    raise ValueError("Please set your REPLICATE_API_TOKEN environment variable")

client = replicate.Client(api_token=REPLICATE_API_TOKEN)

DEFAULT_MODEL = "stability-ai/stable-diffusion-2"

# ============================================================
# PROMPT HELPER
# ============================================================

def build_diagram_prompt(user_text: str) -> str:
    """
    Simple, SD-friendly diagram style.
    """
    return (
        "Simple clean diagram, flat vector style, white background, "
        "clear labels, arrows, minimal design, educational, no realism.\n\n"
        f"{user_text}"
    )

# ============================================================
# INTERNAL SYNC CALL
# ============================================================

def _sync_generate(prompt: str, width: int = 512, height: int = 512, steps: int = 20) -> bytes | None:
    try:
        output_urls = client.predict(
            model=DEFAULT_MODEL,
            input={
                "prompt": prompt,
                "width": width,
                "height": height,
                "num_inference_steps": steps
            }
        )
        if not output_urls:
            print("[Replicate ERROR] No output URLs returned")
            return None

        img_url = output_urls[0]
        resp = requests.get(img_url)
        if resp.status_code != 200:
            print("[Replicate ERROR] Failed to fetch image from URL:", resp.status_code)
            return None

        return resp.content
    except Exception as e:
        print("[Replicate ERROR]", e)
        return None

# ============================================================
# ASYNC WRAPPER (for groq_bot.py)
# ============================================================

async def generate_image(prompt: str, diagram: bool = False) -> bytes:
    """
    Wrapper so groq_bot.py can call 'await generate_image(prompt)'
    diagram=True → uses diagram style
    """
    if diagram:
        prompt = build_diagram_prompt(prompt)
    
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _sync_generate, prompt)
    
    if not result:
        raise RuntimeError("Replicate failed to generate an image")
    
    return result
