import os
import asyncio
import aiohttp

DEAPI_API_KEY = os.getenv("DEAPI_API_KEY", "").strip()
VIDEO_TO_TEXT_ENDPOINT = "https://api.deapi.ai/api/v1/client/vid2txt"
RESULT_URL_BASE = os.getenv("DEAPI_RESULT_BASE", "http://localhost:8000")


class VideoToTextError(Exception):
    pass


async def transcribe_video(*, video_url: str, max_minutes: int = 30) -> str:
    if not DEAPI_API_KEY:
        raise VideoToTextError("DEAPI_API_KEY is not set")

    if not video_url or not video_url.strip():
        raise VideoToTextError("Video URL is required")

    headers = {
        "Authorization": f"Bearer {DEAPI_API_KEY}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    payload = {
        "model": "WhisperLargeV3",
        "include_ts": False,
        "return_result_in_response": True,
        "video_url": video_url.strip(),
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

            # If deAPI returns the transcript directly in submit response,
            # use it immediately (as requested by return_result_in_response=true).
            submit_data = response_data.get("data", {})
            immediate_transcript = (
                submit_data.get("transcription")
                or submit_data.get("transcript")
                or submit_data.get("text")
            )
            if immediate_transcript:
                return immediate_transcript.strip()

            request_id = response_data.get("data", {}).get("request_id")
            if not request_id:
                raise VideoToTextError("No request_id returned from video-to-text")

    poll_url = f"{RESULT_URL_BASE}/result/{request_id}"

    async with aiohttp.ClientSession() as session:
        max_attempts = 72
        delay = 5

        for _ in range(max_attempts):
            async with session.get(poll_url) as r:
                if r.status != 200:
                    await asyncio.sleep(delay)
                    continue

                status_data = await r.json()
                status = status_data.get("status")

                if status == "done":
                    data = status_data.get("data", {})
                    duration_seconds = data.get("duration_seconds")
                    if isinstance(duration_seconds, (int, float)) and duration_seconds > (max_minutes * 60):
                        raise VideoToTextError("Video is longer than 30 minutes")

                    transcript = (
                        data.get("transcription")
                        or data.get("transcript")
                        or data.get("text")
                    )

                    if transcript:
                        return transcript.strip()

                    transcript_url = data.get("result_url") or data.get("transcript_url")
                    if transcript_url:
                        async with session.get(transcript_url) as tresp:
                            if tresp.status != 200:
                                raise VideoToTextError(
                                    f"Failed to download transcript (status {tresp.status})"
                                )
                            return (await tresp.text()).strip()

                    raise VideoToTextError("Transcription completed but no text was returned")

            await asyncio.sleep(delay)

    raise VideoToTextError("Transcription not ready after polling timeout")
