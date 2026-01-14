# replicate_client_image.py
import os
import replicate
import asyncio

# ============================================================
# CONFIG
# ============================================================

REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN", "")
DEFAULT_MODEL = "stability-ai/stable-diffusion"  # SD model, you can change
TIMEOUT_SECONDS = 60  # max wait per generation

# ============================================================
# PROMPT HELPER
# ============================================================

def build_diagram_prompt(user_text: str) -> str:
    """
    Returns a diagram-style prompt (vector, educational, clean)
    """
    return (
        "Simple clean diagram, flat vector style, white background, "
        "clear labels, arrows, minimal design, educational, no realism.\n\n"
        f"{user_text}"
    )

# ============================================================
# PUBLIC FUNCTION
# ============================================================

async def generate_image_replicate(prompt: str) -> bytes | None:
    """
    Async-friendly image generation with Replicate.
    Returns image bytes (PNG) or None on failure.
    """
    if not REPLICATE_API_TOKEN:
        print("[Replicate ERROR] REPLICATE_API_TOKEN not set")
        return None

    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _sync_generate, prompt)
    except Exception as e:
        print("[Replicate ERROR]", e)
        return None

# ============================================================
# INTERNAL SYNC FUNCTION
# ============================================================

def _sync_generate(prompt: str) -> bytes | None:
    """
    Blocking call to Replicate API, returns PNG bytes.
    """
    try:
        client = replicate.Client(api_token=REPLICATE_API_TOKEN)
        model = client.models.get(DEFAULT_MODEL)

        output = model.predict(
            prompt=prompt,
            width=512,
            height=512,
            num_inference_steps=20
        )

        if not output or len(output) == 0:
            print("[Replicate ERROR] no image returned")
            return None

        # Get first image URL and fetch bytes
        import requests
        img_url = output[0]
        resp = requests.get(img_url, timeout=TIMEOUT_SECONDS)
        if resp.status_code == 200:
            return resp.content

        print("[Replicate ERROR] failed to download image")
        return None

    except Exception as e:
        print("[Replicate ERROR]", e)
        return None
