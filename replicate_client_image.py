import os
import asyncio
import replicate

# ============================================================
# CONFIG
# ============================================================

REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
if not REPLICATE_API_TOKEN:
    raise RuntimeError("REPLICATE_API_TOKEN not set")

# Replicate reads token automatically from env
print("🔥 USING REPLICATE Imagen 4 (google/imagen-4) 🔥")

# ============================================================
# DIAGRAM PROMPT HELPER (USED BY groq_bot.py)
# ============================================================

def build_diagram_prompt(user_text: str) -> str:
    return (
        "Simple clean diagram, flat vector style, white background, "
        "clear labels, arrows, minimal design, educational, no realism.\n\n"
        + user_text
    )

# ============================================================
# IMAGE GENERATION (PUBLIC API)
# ============================================================

async def generate_image(prompt: str) -> bytes:
    """
    Generates an image using Google Imagen 4 via Replicate.
    Returns raw PNG bytes.
    """

    loop = asyncio.get_event_loop()

    def sync_call():
        try:
            output = replicate.run(
                "google/imagen-4",
                input={
                    "prompt": prompt,
                    "aspect_ratio": "1:1",  # safe default for Discord
                    "output_format": "png",
                    "safety_filter_level": "block_medium_and_above"
                }
            )

            # Imagen returns a File-like object
            return output.read()

        except Exception as e:
            print("[Replicate ERROR]", e)
            return None

    image_bytes = await loop.run_in_executor(None, sync_call)

    if not image_bytes:
        raise RuntimeError("Replicate failed to generate image")

    return image_bytes
