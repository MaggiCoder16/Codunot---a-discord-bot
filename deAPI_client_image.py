import os
import asyncio
import requests
import io
import re

# ============================================================
# CONFIG
# ============================================================

DEAPI_API_KEY = os.getenv("DEAPI_API_KEY")
if not DEAPI_API_KEY:
    raise RuntimeError("DEAPI_API_KEY not set")

# Replace with a model your account can actually access
MODEL_NAME = "Flux.1 schnell"
print(f"🔥 USING deAPI model {MODEL_NAME} 🔥")

# ============================================================
# DIAGRAM PROMPT HELPER
# ============================================================

def build_diagram_prompt(user_text: str) -> str:
    """
    Builds a clean diagram-style prompt for educational or fun images.
    """
    return (
        "Simple clean diagram, flat vector style, white background, "
        "clear labels, arrows, minimal design, educational, no realism.\n\n"
        + user_text
    )

# ============================================================
# PROMPT CLEANING / FALLBACK
# ============================================================

def clean_prompt(prompt: str) -> str:
    """
    Ensures the prompt is valid: non-empty, no newlines, max 900 chars.
    If empty, returns a safe default.
    """
    if not prompt:
        prompt = ""
    prompt = prompt.strip()
    prompt = re.sub(r'[\r\n]+', ' ', prompt)
    if len(prompt) == 0:
        prompt = "Simple diagram, white background"  # fallback default
    if len(prompt) > 900:
        prompt = prompt[:900]
    return prompt

# ============================================================
# IMAGE GENERATION (MATCHES groq_bot.py EXACTLY)
# ============================================================

async def generate_image(
    prompt: str,
    aspect_ratio: str = "1:1",
    steps: int = 8  # low steps by default
) -> bytes:
    """
    Generate image using deAPI (Flux.1 schnell or other models).
    Returns raw PNG bytes.
    """

    # Always ensure prompt is valid
    prompt = clean_prompt(prompt)

    # Width/height rules
    if MODEL_NAME.lower() == "flux.1 schnell":
        width = height = 768  # safe, divisible by 8, inside 256–2048
    else:
        # Other models like ZImageTurbo_INT8 can support different aspect ratios
        if aspect_ratio == "16:9":
            width, height = 768, 432
        elif aspect_ratio == "9:16":
            width, height = 432, 768
        elif aspect_ratio == "1:2":
            width, height = 384, 768
        else:
            width, height = 768, 768

    # Async wrapper for synchronous requests
    loop = asyncio.get_event_loop()

    def sync_call():
        try:
            url = "https://api.deapi.ai/api/v1/client/txt2img"
            headers = {
                "Authorization": f"Bearer {DEAPI_API_KEY}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": MODEL_NAME,
                "prompt": prompt,
                "width": width,
                "height": height,
                "steps": steps,
                "negative_prompt": ""
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
