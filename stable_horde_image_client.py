import os
import base64
import aiohttp
import asyncio

STABLE_HORDE_API_KEY = os.getenv("STABLE_HORDE_API_KEY", "")

SUBMIT_URL = "https://stablehorde.net/api/v2/generate/async"
CHECK_URL = "https://stablehorde.net/api/v2/generate/check"

# ============================================================
# INTERNAL: submit + wait once
# ============================================================

async def _generate_once(prompt: str, timeout: int) -> bytes | None:
    headers = {"Content-Type": "application/json"}
    if STABLE_HORDE_API_KEY:
        headers["apikey"] = STABLE_HORDE_API_KEY

    payload = {
        "prompt": prompt,
        "params": {
            "steps": 20,
            "width": 512,
            "height": 512,
            "cfg_scale": 7,
            "sampler_name": "k_euler"
        },
        "models": ["stable_diffusion"],  # SD 1.5 ONLY
        "nsfw": False,
        "shared": True,
        "trusted_workers": False,
        "slow_workers": True
    }

    async with aiohttp.ClientSession() as session:
        # ---------------- submit ----------------
        async with session.post(SUBMIT_URL, json=payload, headers=headers) as resp:
            if resp.status not in (200, 202):
                print("[Horde ERROR] submit failed:", resp.status)
                return None

            data = await resp.json()
            job_id = data.get("id")
            if not job_id:
                print("[Horde ERROR] no job id")
                return None

            print("[Stable Horde] Job submitted:", job_id)

        # ---------------- poll ----------------
        start = asyncio.get_event_loop().time()

        while True:
            await asyncio.sleep(3)

            if asyncio.get_event_loop().time() - start > timeout:
                print("[Horde ERROR] timeout")
                return None

            async with session.get(f"{CHECK_URL}/{job_id}", headers=headers) as resp:
                if resp.status != 200:
                    continue

                data = await resp.json()

                print(
                    "[Stable Horde]",
                    "waiting:", data.get("waiting"),
                    "queue:", data.get("queue_position")
                )

                if not data.get("done"):
                    continue

                gens = data.get("generations", [])
                if not gens:
                    print("[Horde ERROR] worker failed (no image)")
                    return None

                img_b64 = gens[0].get("img")
                if not img_b64:
                    print("[Horde ERROR] empty image")
                    return None

                print("[Stable Horde] Image generated")
                return base64.b64decode(img_b64)

# ============================================================
# PUBLIC FUNCTION (RETRY WRAPPER)
# ============================================================

async def generate_image_horde(prompt: str) -> bytes | None:
    """
    Fastest + most reliable FREE Stable Horde image generation.
    Retries once if a worker fails.
    """

    for attempt in range(2):
        print(f"[Stable Horde] Attempt {attempt + 1}")
        image = await _generate_once(prompt, timeout=90)
        if image:
            return image

    print("[Stable Horde] All attempts failed")
    return None
