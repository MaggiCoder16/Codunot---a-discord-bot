import os
import asyncio
import aiohttp

DEAPI_API_KEY = os.getenv("DEAPI_API_KEY")
VIDEO_URL = "https://api.deapi.ai/api/generation/text-to-video"
RESULT_BASE = os.getenv("DEAPI_RESULT_BASE")

class Text2VidError(Exception):
    pass


async def warm_webhook_server():
    if not RESULT_BASE:
        return
    try:
        async with aiohttp.ClientSession() as session:
            await session.get(RESULT_BASE, timeout=5)
        print("[Warmup] Webhook server awake.")
    except Exception as e:
        print("[Warmup] Warmup skipped:", e)


async def generate_video(prompt: str, model="gen4_turbo", max_retries=60, delay=5):
    headers = {
        "Authorization": f"Bearer {DEAPI_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "prompt": prompt,
        "model": model,
        "webhook_url": f"{RESULT_BASE}/webhook" if RESULT_BASE else None,
    }

    async with aiohttp.ClientSession(headers=headers) as session:

        # Wake Railway before job submission
        await warm_webhook_server()

        # Submit job
        async with session.post(VIDEO_URL, json=payload) as resp:
            if resp.status != 200:
                raise Text2VidError(f"Submission failed: {await resp.text()}")
            data = await resp.json()

        request_id = data.get("request_id")
        seed = data.get("seed")

        if not request_id:
            raise Text2VidError("No request_id returned")

        print(f"[VIDEO GEN] Submitted | request_id={request_id}")

        # Poll
        result_url = None

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
                print("[VIDEO GEN] Result received.")
                return result_url, seed

            print(f"[VIDEO GEN] Waiting... {attempt+1}/{max_retries}")

        raise Text2VidError("Timed out waiting for video result.")
