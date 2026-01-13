import os
import io
from huggingface_hub import InferenceClient
from PIL import Image

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
# PUBLIC IMAGE GENERATOR (ACTUALLY WORKS)
# ============================================================

async def generate_image_hf(
    prompt: str,
    *,
    diagram: bool = False,
) -> bytes:
    """
    Generates an image using Hugging Face InferenceClient.
    Uses ONLY supported arguments.
    Returns raw PNG bytes.
    """

    if diagram:
        prompt = build_diagram_prompt(prompt)

    client = InferenceClient(api_key=HF_API_KEY)

    # ---------- PRIMARY ----------
    try:
        img = client.text_to_image(
            prompt,
            model=HF_MODEL_PRIMARY
        )

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    except Exception as e:
        print(f"[HF PRIMARY FAILED] {e}")

    # ---------- FALLBACK ----------
    try:
        img = client.text_to_image(
            prompt,
            model=HF_MODEL_FALLBACK
        )

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    except Exception as e:
        print(f"[HF FALLBACK FAILED] {e}")
        raise RuntimeError("All Hugging Face image models failed")
