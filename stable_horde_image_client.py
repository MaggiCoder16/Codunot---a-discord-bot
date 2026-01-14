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
# IMAGE GENERATOR (ASYNC FIXED)
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

    print("[Stable Horde] Sending payload:", payload)

    async with aiohttp.ClientSession() as session:
        # Submit job
        async with session.post(STABLE_HORDE_URL, json=payload, headers=headers, timeout=timeout) as resp:
            text = await resp.text()
            if resp.status not in (200, 202):
                print(f"[Stable Horde ERROR] Status {resp.status}: {text}")
                raise RuntimeError(f"[Stable Horde] Failed with status {resp.status}: {text}")

            data = await resp.json()
            print("[Stable Horde] Job response:", data)

        job_id = data.get("id")
        if not job_id:
            raise RuntimeError(f"[Stable Horde] No job ID returned: {data}")

        # Poll until image is ready
        for _ in range(timeout // 2):
            await asyncio.sleep(2)
            try:
                async with session.get(f"{STABLE_HORDE_CHECK_URL}/{job_id}", headers=headers, timeout=30) as check_resp:
                    if check_resp.status == 404:
                        # Job not ready yet
                        continue
                    check_data = await check_resp.json()
                    if "generations" in check_data and check_data["generations"]:
                        img_b64 = check_data["generations"][0].get("img")
                        if img_b64:
                            print("[Stable Horde] Image generated successfully")
                            return base64.b64decode(img_b64)
            except Exception as e:
                print("[Stable Horde ERROR] Polling failed:", e)

        raise RuntimeError("[Stable Horde] Timeout waiting for image")
