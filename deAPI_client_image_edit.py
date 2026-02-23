import os
import asyncio
import aiohttp

DEAPI_API_KEY = os.getenv("DEAPI_API_KEY")
EDIT_URL = "https://api.deapi.ai/api/generation/image-to-image"
RESULT_BASE = os.getenv("DEAPI_RESULT_BASE")

class Img2ImgError(Exception):
    pass


async def warm_webhook_server():
    if not RESULT_BASE:
        return
    try:
        async with aiohttp.ClientSession() as session:
            await session.get(RESULT_BASE, timeout=5)
    except Exception:
        pass


async def edit_image(image_url: str, prompt: str, model="sdxl", max_retries=60, delay=5):
    headers = {
        "Authorization": f"Bearer {DEAPI_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "image_url": image_url,
        "prompt": prompt,
        "model": model,
        "webhook_url": f"{RESULT_BASE}/webhook" if RESULT_BASE else None,
    }

    async with aiohttp.ClientSession(headers=headers) as session:

        await warm_webhook_server()

        async with session.post(EDIT_URL, json=payload) as resp:
            if resp.status != 200:
                raise Img2ImgError(f"Submission failed: {await resp.text()}")
            data = await resp.json()

        request_id = data.get("request_id")
        if not request_id:
            raise Img2ImgError("No request_id returned")

        print(f"[IMG2IMG] Submitted | request_id={request_id}")

        for attempt in range(max_retries):
            await asyncio.sleep(delay)

            async with session.get(f"{RESULT_BASE}/result/{request_id}") as res:
                if res.status != 200:
                    continue
                status_data = await res.json()

            result_url = (
                status_data.get("result_url")
                or status_data.get("data", {}).get("result_url")
                or status_data.get("raw", {}).get("result_url")
            )

            if result_url:
                print("[IMG2IMG] Result received.")
                return result_url

            print(f"[IMG2IMG] Waiting... {attempt+1}/{max_retries}")

        raise Img2ImgError("Timed out waiting for edited image.")
