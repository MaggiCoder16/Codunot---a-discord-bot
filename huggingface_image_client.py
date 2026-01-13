import os
import asyncio
from huggingface_hub import InferenceClient

# ============================================================
# CONFIG
# ============================================================

HF_API_KEY = os.getenv("HUGGINGFACE_API_KEY_IMAGE_GEN")
if not HF_API_KEY:
    raise RuntimeError("HUGGINGFACE_API_KEY_IMAGE_GEN not set")

HF_MODEL_PRIMARY = "stabilityai/stable-diffusion-xl-base-1.0"
HF_MODEL_FALLBACK = "runwayml/stable-diffusion-v1-5"

# ============================================================
# PROMPT BUILDER (FOR DIAGRAMS)
# ============================================================

def build_diagram_prompt(user_text: str) -> str:
    return (
        "Clean educational diagram, flat vector style, "
        "white background, clear black text labels, arrows, "
        "simple shapes, top-to-bottom layout, "
        "no realism, no shadows, no textures.\n\n"
        f"{user_text}"
    )

# ============================================================
# PUBLIC IMAGE GENERATOR (FIXED)
# ============================================================

async def generate_image_hf(
    prompt: str,
    *,
    diagram: bool = False,
    width: int = 1024,
    height: int = 1024,
    steps: int = 28,
    negative_prompt: str = (
        "blurry, low quality, distorted text, watermark, logo, "
        "photorealistic, shadows, textures, extra limbs"
    )
) -> bytes:
    """
    Generates an image using Hugging Face InferenceClient.
    Supports diagram prompts, width/height, steps, and negative prompts.
    Automatically falls back to a secondary model.
    Returns raw PNG bytes.
    """
    if diagram:
        prompt = build_diagram_prompt(prompt)

    client = InferenceClient(api_key=HF_API_KEY)

    # --- Primary model ---
    try:
        results = client.text_to_image(
            prompt=prompt,
            model=HF_MODEL_PRIMARY,
            width=width,
            height=height,
            num_inference_steps=steps,
            negative_prompt=negative_prompt,
            guidance_scale=7.5
        )
        return results[0].content
    except Exception as e:
        print(f"[HF PRIMARY FAILED] {e}")

    # --- Fallback model ---
    try:
        results = client.text_to_image(
            prompt=prompt,
            model=HF_MODEL_FALLBACK,
            width=width,
            height=height,
            num_inference_steps=steps,
            negative_prompt=negative_prompt,
            guidance_scale=7.5
        )
        return results[0].content
    except Exception as e:
        print(f"[HF FALLBACK FAILED] {e}")
        raise RuntimeError("All Hugging Face image models failed")
