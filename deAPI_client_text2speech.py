import os
import aiohttp
import asyncio
import time

DEAPI_API_KEY = os.getenv("DEAPI_API_KEY", "").strip()

BASE_URL = "https://api.deapi.ai/api/v1/client"
TTS_ENDPOINT = f"{BASE_URL}/txt2audio"
RESULT_ENDPOINT = f"{BASE_URL}/request-status"


class TextToSpeechError(Exception):
    pass


async def text_to_speech(
    *,
    text: str,
    voice: str,
    lang: str,
    model: str = "Kokoro",
    speed: float = 1.0,
    format: str = "mp3",
    sample_rate: int = 24000,
    poll_delay: float = 10.0,
    max_wait: float = 120.0,
):

    if not DEAPI_API_KEY:
        raise TextToSpeechError("DEAPI_API_KEY is not set")
    if not text or not text.strip():
        raise TextToSpeechError("Text is required")
    if not voice:
        raise TextToSpeechError("Voice is required")
    if not lang:
        raise TextToSpeechError("Language is required")

    headers = {
        "Authorization": f"Bearer {DEAPI_API_KEY}",
        "Accept": "application/json",
    }

    form = aiohttp.FormData()
    form.add_field("text", text.strip())
    form.add_field("model", model)
    form.add_field("voice", voice)
    form.add_field("lang", lang)
    form.add_field("speed", str(speed))
    form.add_field("format", format)
    form.add_field("sample_rate", str(sample_rate))

    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.post(
            TTS_ENDPOINT,
            data=form,
            timeout=aiohttp.ClientTimeout(total=60),
        ) as resp:
            print(
                "[TTS] "
                f"RPM limit: {resp.headers.get('x-ratelimit-limit')}, "
                f"RPM remaining: {resp.headers.get('x-ratelimit-remaining')} | "
                f"RPD limit: {resp.headers.get('x-ratelimit-daily-limit')}, "
                f"RPD remaining: {resp.headers.get('x-ratelimit-daily-remaining')}"
            )
            if resp.status != 200:
                error_text = await resp.text()
                raise TextToSpeechError(
                    f"txt2audio submit failed ({resp.status}): {error_text}"
                )
            response_data = await resp.json()
            request_id = response_data.get("data", {}).get("request_id")
            if not request_id:
                raise TextToSpeechError("No request_id returned")
            print(f"[TTS] Request submitted. request_id = {request_id}")

        start_time = time.monotonic()
        while True:
            await asyncio.sleep(poll_delay)
            async with session.get(f"{RESULT_ENDPOINT}/{request_id}") as resp:
                if resp.status != 200:
                    raise TextToSpeechError(
                        f"Failed to fetch result ({resp.status}) for request_id={request_id}"
                    )
                result = await resp.json()

            data = result.get("data", {})
            status = data.get("status")
            result_url = data.get("result_url")

            if status == "done" and result_url:
                print(f"[TTS] Audio ready at {result_url}")
                return result_url

            if status in ("failed", "error"):
                raise TextToSpeechError(f"txt2audio failed: {result}")

            elapsed = time.monotonic() - start_time
            print(f"[TTS] Waiting… status={status}, elapsed={elapsed:.1f}s")
            if elapsed >= max_wait:
                raise TextToSpeechError(
                    f"Timed out waiting for result_url (status={status})"
                )
