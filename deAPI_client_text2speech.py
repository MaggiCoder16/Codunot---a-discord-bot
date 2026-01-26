import os
import aiohttp
import asyncio
import time

DEAPI_API_KEY = os.getenv("DEAPI_API_KEY", "").strip()

# ── API ENDPOINTS ──
BASE_URL = "https://api.deapi.ai/api/v1/client"
TTS_ENDPOINT = f"{BASE_URL}/txt2audio"
RESULT_ENDPOINT = f"{BASE_URL}/request-status"

class TextToSpeechError(Exception):
    pass

async def text_to_speech(
    *,
    text: str,
    model: str = "Kokoro",
    voice: str = "am_michael",
    lang: str = "en-us",
    speed: float = 1.0,
    format: str = "mp3",
    sample_rate: int = 24000,
    poll_delay: float = 10.0,
    max_wait: float = 120.0,
):
    """
    Generate speech from text using the Text-to-Speech API.
    Returns the URL to the generated audio file.
    """

    if not DEAPI_API_KEY:
        raise TextToSpeechError("DEAPI_API_KEY is not set")

    if not text or not text.strip():
        raise TextToSpeechError("Text is required")

    headers = {
        "Authorization": f"Bearer {DEAPI_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "text": text.strip(),
        "model": model,
        "voice": voice,
        "lang": lang,
        "speed": speed,
        "format": format,
        "sample_rate": sample_rate,
    }

    async with aiohttp.ClientSession(headers=headers) as session:
        # ── SUBMIT JOB ──
        async with session.post(
            TTS_ENDPOINT,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=60),
        ) as resp:
            if resp.status != 200:
                raise TextToSpeechError(
                    f"txt2audio submit failed ({resp.status}): {await resp.text()}"
                )

            response_data = await resp.json()
            request_id = response_data.get("data", {}).get("request_id")

            if not request_id:
                raise TextToSpeechError("No request_id returned")

            print(f"[TTS] Request submitted. request_id = {request_id}")

        # ── POLL FOR RESULT ──
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
                print(f"[TTS] Audio ready")
                return result_url

            if status in ("failed", "error"):
                raise TextToSpeechError(f"txt2audio failed: {result}")

            elapsed = time.monotonic() - start_time
            print(f"[TTS] Waiting… status={status}, elapsed={elapsed:.1f}s")

            if elapsed >= max_wait:
                raise TextToSpeechError(
                    f"Timed out waiting for result_url (status={status})"
                )
