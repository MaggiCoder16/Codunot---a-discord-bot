import os
import io
import base64
import aiohttp
import asyncio
from PIL import Image

# ============================================================
# CONFIG
# ============================================================
STABLE_HORDE_API_KEY = os.getenv("STABLE_HORDE_API_KEY", "")
STABLE_HORDE_URL = "https://stablehorde.net/api/v2/generate/async"
STABLE_HORDE_CHECK_URL = "https://stablehorde.net/api/v2/generate/check"

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
# IMAGE GENERATOR (WAIT UNTIL FINISHED)
# ============================================================
async def generate_image_horde(prompt: str, *, diagram: bool = False, timeout: int = 120) -> bytes:
    if diagram:
        prompt = build_diagram_prompt(prompt)

    headers = {"Content-Type": "application/json"}
    if STABLE_HORDE_API_KEY:
        headers["apikey"] = STABLE_HORDE_API_KEY

    payload = {
        "prompt": prompt,
        "params": {
            "steps": 25,
            "width": 512,
            "height": 512,
            "cfg_scale": 7.0,
            "sampler_name": "k_euler"
        },
        "nsfw": False
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(STABLE_HORDE_URL, json=payload, headers=headers, timeout=timeout) as resp:
            data = await resp.json()
            job_id = data.get("id")
            if not job_id:
                raise RuntimeError(f"No job ID returned: {data}")

        start_time = asyncio.get_event_loop().time()
        while True:
            await asyncio.sleep(2)
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > timeout:
                raise RuntimeError("Timeout waiting for image")

            try:
                async with session.get(f"{STABLE_HORDE_CHECK_URL}/{job_id}", headers=headers, timeout=30) as check_resp:
                    if check_resp.status in (404, 202):
                        continue  # Job not ready yet

                    check_data = await check_resp.json()
                    generations = check_data.get("generations", [])
                    if generations:
                        img_b64 = generations[0].get("img")
                        if img_b64:
                            return base64.b64decode(img_b64)
            except Exception as e:
                print("[Stable Horde ERROR] Polling failed:", e)
