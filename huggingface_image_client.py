import os
import aiohttp
import asyncio
import base64

HF_API_KEY = os.getenv("HUGGINGFACE_API_KEY_IMAGE_GEN")
if not HF_API_KEY:
    raise RuntimeError("HUGGINGFACE_API_KEY_IMAGE_GEN not set")

HEADERS = {
    "Authorization": f"Bearer {HF_API_KEY}",
}

HF_MODEL_PRIMARY = "stabilityai/stable-diffusion-xl-base-1.0"
HF_MODEL_FALLBACK = "runwayml/stable-diffusion-v1-5"
HF_TIMEOUT = aiohttp.ClientTimeout(total=120)

def build_diagram_prompt(user_text: str) -> str:
    return (
        "Clean educational diagram, flat vector style, "
        "white background, clear black text labels, arrows, "
        "simple shapes, top-to-bottom layout, "
        "no realism, no shadows, no textures.\n\n"
        f"{user_text}"
    )

async def _request_image(model: str, prompt: str, width=1024, height=1024, steps=28) -> bytes:
    url = f"https://router.huggingface.co/models/{model}"

    payload = {
        "inputs": prompt,
        "parameters": {
            "width": width,
            "height": height,
            "num_inference_steps": steps,
            "guidance_scale": 7.5,
        },
    }

    async with aiohttp.ClientSession(timeout=HF_TIMEOUT) as session:
        async with session.post(url, headers=HEADERS, json=payload) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"{model} failed ({resp.status}): {text}")

            data = await resp.json()
            if "generated_image" in data:
                return base64.b64decode(data["generated_image"])
            else:
                raise RuntimeError(f"{model} returned unexpected JSON: {data}")


async def generate_image_hf(prompt: str, *, diagram=False, width=1024, height=1024, steps=28) -> bytes:
    if diagram:
        prompt = build_diagram_prompt(prompt)

    # --- Primary ---
    try:
        return await _request_image(HF_MODEL_PRIMARY, prompt, width, height, steps)
    except Exception as e:
        print(f"[HF PRIMARY FAILED] {e}")

    # --- Fallback ---
    try:
        return await _request_image(HF_MODEL_FALLBACK, prompt, width, height, steps)
    except Exception as e:
        print(f"[HF FALLBACK FAILED] {e}")
        raise RuntimeError("All Hugging Face image models failed")
