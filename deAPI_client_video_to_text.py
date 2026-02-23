import os
import aiohttp
import asyncio

DEAPI_API_KEY = os.getenv("DEAPI_API_KEY", "").strip()
VIDEO_TO_TEXT_ENDPOINT = "https://api.deapi.ai/api/v1/client/vid2txt"
RENDER_BASE = "https://deapi-webhook.onrender.com"


class VideoToTextError(Exception):
    pass


async def transcribe_video(*, video_url: str, max_minutes: int = 30) -> str:
    if not DEAPI_API_KEY:
        raise VideoToTextError("DEAPI_API_KEY is not set")

    webhook_url = os.getenv("DEAPI_WEBHOOK_URL")
    if not webhook_url:
        raise VideoToTextError("DEAPI_WEBHOOK_URL is not set")

    headers = {
        "Authorization": f"Bearer {DEAPI_API_KEY}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    payload = {
        "model": "WhisperLargeV3",
        "include_ts": False,
        "return_result_in_response": False,
        "video_url": video_url.strip(),
        "webhook_url": webhook_url,
    }

    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.post(
            VIDEO_TO_TEXT_ENDPOINT,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=120),
        ) as resp:
            if resp.status != 200:
                raise VideoToTextError(
                    f"video-to-text submit failed ({resp.status}): {await resp.text()}"
                )
            response_data = await resp.json()
            request_id = response_data.get("data", {}).get("request_id")
            if not request_id:
                raise VideoToTextError("No request_id returned")
            print(f"[TRANSCRIBE] Submitted | request_id={request_id}")

    await asyncio.sleep(15)

    poll_url = f"{RENDER_BASE}/result/{request_id}"
    async with aiohttp.ClientSession() as session:
        for attempt in range(20):
            await asyncio.sleep(10)
            try:
                async with session.get(poll_url) as r:
                    if r.status != 200:
                        continue
                    data = await r.json()
                    if data.get("status") == "done":
                        result = data.get("data", {})
                        transcript = (
                            result.get("transcription")
                            or result.get("transcript")
                            or result.get("text")
                        )
                        if transcript:
                            return transcript.strip()
                        raise VideoToTextError("Done but no transcript returned")
            except VideoToTextError:
                raise
            except Exception as e:
                print(f"[TRANSCRIBE] Poll error attempt {attempt + 1}: {e}")

    raise VideoToTextError("Transcription timed out after 20 attempts")
