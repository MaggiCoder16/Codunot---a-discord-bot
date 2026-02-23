import os
import aiohttp

DEAPI_API_KEY = os.getenv("DEAPI_API_KEY", "").strip()
VIDEO_TO_TEXT_ENDPOINT = "https://api.deapi.ai/api/v1/client/vid2txt"


class VideoToTextError(Exception):
    pass


async def transcribe_video(*, video_url: str, max_minutes: int = 30) -> str:
    if not DEAPI_API_KEY:
        raise VideoToTextError("DEAPI_API_KEY is not set")

    webhook_url = os.getenv("DEAPI_VID2TXT_WEBHOOK_URL") or os.getenv("DEAPI_WEBHOOK_URL")
    if not webhook_url:
        raise VideoToTextError("DEAPI_VID2TXT_WEBHOOK_URL (or DEAPI_WEBHOOK_URL fallback) is not set")

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
            return request_id
