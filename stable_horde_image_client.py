import os
import base64
import aiohttp
import asyncio

STABLE_HORDE_API_KEY = os.getenv("STABLE_HORDE_API_KEY", "")

SUBMIT_URL = "https://stablehorde.net/api/v2/generate/async"
CHECK_URL = "https://stablehorde.net/api/v2/generate/check"

FAST_MODELS = [
    "AlbedoBase XL 3.1",
    "AbsoluteReality"
    "Flux.1-Schnell fp8 (Compact)"
]

def build_diagram_prompt(user_text: str) -> str:
    return (
        "Simple clean diagram, flat vector style, white background, "
        "clear labels, arrows, minimal design, educational.\n\n"
        f"{user_text}"
    )

async def _submit_and_wait(prompt: str, model: str, timeout: int) -> bytes | None:
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
            "sampler_name": "k_euler_a"
        },
        "models": [model],
        "nsfw": False,
        "shared": True,
        "trusted_workers": False,
        "slow_workers": True
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(SUBMIT_URL, json=payload, headers=headers) as resp:
            if resp.status not in (200, 202):
                print(f"[Stable Horde] {model} submit failed {resp.status}")
                return None

            data = await resp.json()
            job_id = data.get("id")
            if not job_id:
                print(f"[Stable Horde] {model} no job id")
                return None

            print(f"[Stable Horde] {model} job submitted:", job_id)

        start = asyncio.get_event_loop().time()

        while True:
            await asyncio.sleep(2)

            if asyncio.get_event_loop().time() - start > timeout:
                print(f"[Stable Horde] {model} timeout")
                return None

            async with session.get(f"{CHECK_URL}/{job_id}", headers=headers) as r:
                if r.status != 200:
                    continue

                data = await r.json()
                waiting = data.get("waiting", 0)
                queue = data.get("queue_position", 0)
                print(f"[Stable Horde] {model} waiting:{waiting} queue:{queue}")

                if not data.get("done"):
                    continue

                gens = data.get("generations", [])
                if not gens:
                    print(f"[Stable Horde] {model} no generations")
                    return None

                img_b64 = gens[0].get("img")
                if not img_b64:
                    print(f"[Stable Horde] {model} empty image")
                    return None

                print(f"[Stable Horde] {model} image ready")
                return base64.b64decode(img_b64)

async def generate_image_horde(prompt: str) -> bytes | None:
    """
    Attempt fastest free models in order with short timeouts.
    """
    for model in FAST_MODELS:
        print(f"[Stable Horde] Trying model {model}")
        image = await _submit_and_wait(prompt, model, timeout=30)
        if image:
            return image
        print(f"[Stable Horde] {model} failed or slow, trying next")

    print("[Stable Horde] All fast models failed")
    return None
