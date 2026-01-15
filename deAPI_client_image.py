import os
import asyncio
import requests
import base64

# ============================================================
# CONFIG
# ============================================================

DEAPI_API_KEY = os.getenv("DEAPI_API_KEY")
if not DEAPI_API_KEY:
    raise RuntimeError("DEAPI_API_KEY not set")

MODEL_NAME = "Flux1schnell"

print(f"🔥 USING deAPI model {MODEL_NAME} 🔥")

# ============================================================
# DIAGRAM PROMPT HELPER
# ============================================================

def build_diagram_prompt(user_text: str) -> str:
    return (
        "Simple clean diagram, flat vector style, white background, "
        "clear labels, arrows, minimal design, educational, no realism.\n\n"
        + user_text
    )

# ============================================================
# IMAGE GENERATION (MATCHES groq_bot.py EXACTLY)
# ============================================================

async def generate_image(
    prompt: str,
    aspect_ratio: str = "1:1",
    steps: int = 8  # lower steps by default
) -> bytes:
    """
    Generate image using deAPI (Flux1schnell or other models).
    Returns raw PNG bytes.
    """

    import os, asyncio, requests, io

    DEAPI_API_KEY = os.getenv("DEAPI_API_KEY")
    if not DEAPI_API_KEY:
        raise RuntimeError("DEAPI_API_KEY not set")

    # Set model
    MODEL_NAME = "Flux1schnell"

    # Determine width/height based on model
    if MODEL_NAME == "Flux1schnell":
        width = height = 768  # safe, divisible by 8, inside 256–2048
    else:
        # other models (e.g., ZImageTurbo_INT8)
        if aspect_ratio == "16:9":
            width, height = 768, 432
        elif aspect_ratio == "9:16":
            width, height = 432, 768
        elif aspect_ratio == "1:2":
            width, height = 384, 768
        else:
            width, height = 768, 768

    # Async wrapper
    loop = asyncio.get_event_loop()

    def sync_call():
        try:
            url = "https://api.deapi.ai/api/v1/client/txt2img"
            headers = {"Authorization": f"Bearer {DEAPI_API_KEY}"}
            payload = {
                "model": MODEL_NAME,
                "prompt": prompt,
                "width": width,
                "height": height,
                "steps": steps
            }
            response = requests.post(url, json=payload, headers=headers)
            response.raise_for_status()
            return io.BytesIO(response.content).getvalue()
        except Exception as e:
            print("[deAPI ERROR]", e)
            return None

    image_bytes = await loop.run_in_executor(None, sync_call)

    if not image_bytes:
        raise RuntimeError("deAPI failed to generate image")

    return image_bytes
