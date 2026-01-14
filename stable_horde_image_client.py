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
async def generate_image_horde(
    prompt: str,
    *,
    diagram: bool = False,
    timeout: int = 300
) -> bytes | None:
    """
    Submits an image job to Stable Horde and waits until it is finished.
    Returns raw image bytes, or None on failure.
    """

    if diagram:
        prompt = build_diagram_prompt(prompt)

    headers = {
        "Content-Type": "application/json"
    }
    if STABLE_HORDE_API_KEY:
        headers["apikey"] = STABLE_HORDE_API_KEY

    payload = {
        "prompt": prompt,
        "params": {
            "steps": 28,
            "width": 512,
            "height": 512,
            "cfg_scale": 7.5,
            "sampler_name": "k_euler",
            "seed": None
        },
        "models": [
            "stable_diffusion",
            "anything-v4",
            "dreamshaper",
            "deliberate"
        ],
        "nsfw": False,
        "r2": True,
        "shared": True,
        "trusted_workers": False,
        "slow_workers": True,
        "workers": 1
    }
    print("[Stable Horde] Submitting job...")
    print("[Stable Horde] Prompt:", prompt)

    async with aiohttp.ClientSession() as session:

        # ----------------------------------------------------
        # Submit job
        # ----------------------------------------------------
        try:
            async with session.post(
                STABLE_HORDE_URL,
                json=payload,
                headers=headers,
                timeout=30
            ) as resp:

                text = await resp.text()
                if resp.status not in (200, 202):
                    print(f"[Stable Horde ERROR] Submission failed ({resp.status}): {text}")
                    return None

                data = await resp.json()
                job_id = data.get("id")

                if not job_id:
                    print("[Stable Horde ERROR] No job ID returned:", data)
                    return None

                print("[Stable Horde] Job submitted successfully! ID:", job_id)

        except Exception as e:
            print("[Stable Horde ERROR] Job submission exception:", e)
            return None

        # ----------------------------------------------------
        # Poll until finished
        # ----------------------------------------------------
        start_time = asyncio.get_event_loop().time()

        while True:
            await asyncio.sleep(3)

            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > timeout:
                print(f"[Stable Horde ERROR] Timeout after {timeout}s waiting for job {job_id}")
                return None

            try:
                async with session.get(
                    f"{STABLE_HORDE_CHECK_URL}/{job_id}",
                    headers=headers,
                    timeout=30
                ) as check_resp:

                    if check_resp.status != 200:
                        print(f"[Stable Horde] Waiting... HTTP {check_resp.status}")
                        continue

                    check_data = await check_resp.json()

                    if not check_data.get("done", False):
                        print(f"[Stable Horde] Job {job_id} still running...")
                        continue

                    generations = check_data.get("generations", [])
                    if not generations:
                        print("[Stable Horde ERROR] Job finished but no generations returned")
                        return None

                    img_b64 = generations[0].get("img")
                    if not img_b64:
                        print("[Stable Horde ERROR] Generation missing image data")
                        return None

                    print("[Stable Horde] Image generated successfully!")
                    return base64.b64decode(img_b64)

            except Exception as e:
                print("[Stable Horde ERROR] Polling exception:", e)
                continue
