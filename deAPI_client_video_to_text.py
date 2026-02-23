import os
import aiohttp
import asyncio
import time

DEAPI_API_KEY = os.getenv("DEAPI_API_KEY", "").strip()
DEAPI_BASE_URL = os.getenv("DEAPI_BASE_URL", "https://api.deapi.ai").strip().rstrip("/")
VIDEO_TO_TEXT_ENDPOINT = f"{DEAPI_BASE_URL}/api/v1/client/vid2txt"
RESULT_ENDPOINT = f"{DEAPI_BASE_URL}/api/v1/client/request-status"


class VideoToTextError(Exception):
    pass


async def wait_for_transcription_text(
    *,
    request_id: str,
    poll_delay: float = 10.0,
    max_wait: float = 900.0,
) -> str:
    if not DEAPI_API_KEY:
        raise VideoToTextError("DEAPI_API_KEY is not set")

    headers = {
        "Authorization": f"Bearer {DEAPI_API_KEY}",
        "Accept": "application/json",
    }

    start_time = time.monotonic()
    async with aiohttp.ClientSession(headers=headers) as session:
        while True:
            async with session.get(
                f"{RESULT_ENDPOINT}/{request_id}",
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status != 200:
                    raise VideoToTextError(
                        f"request-status failed ({resp.status}): {await resp.text()}"
                    )
                payload = await resp.json()

            data = payload.get("data", {})
            status = (data.get("status") or "").lower()

            transcript = (
                data.get("transcription")
                or data.get("transcript")
                or data.get("text")
            )
            if transcript:
                return transcript

            result_url = data.get("result_url")
            if status == "done" and result_url:
                async with session.get(result_url, timeout=aiohttp.ClientTimeout(total=120)) as txt_resp:
                    if txt_resp.status == 200:
                        text = (await txt_resp.text()).strip()
                        if text:
                            return text

            if status in {"failed", "error", "cancelled"}:
                raise VideoToTextError(f"video-to-text failed: {payload}")

            elapsed = time.monotonic() - start_time
            if elapsed >= max_wait:
                raise VideoToTextError(
                    f"Timed out waiting for transcription (status={status or 'unknown'})"
                )

            await asyncio.sleep(poll_delay)


async def transcribe_video(*, video_url: str, max_minutes: int = 30) -> str:
    if not DEAPI_API_KEY:
        raise VideoToTextError("DEAPI_API_KEY is not set")

    webhook_url = os.getenv("DEAPI_WEBHOOK_URL", "").strip()
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
            return request_id
