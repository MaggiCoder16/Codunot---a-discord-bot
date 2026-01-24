import os
import aiohttp
import asyncio

DEAPI_API_KEY = os.getenv("DEAPI_API_KEY_TTS", "").strip()
BASE_URL = "https://api.deapi.ai/api/v1/client"
TTS_ENDPOINT = f"{BASE_URL}/txt2audio"

class TextToSpeechError(Exception):
    pass

async def text_to_speech(
    *,
    text: str,
    model: str = "Kokoro",
    voice: str = "male_hero",  # male voice
    lang: str = "en-us",
    speed: float = 2.0,        # 2x speed
    format: str = "flac",
    sample_rate: int = 24000,
    poll_delay: float = 10.0,
):
    """
    Generate speech from text using the Text-to-Speech API.
    Returns the URL to the generated audio file.
    """

    if not text or not text.strip():
        raise TextToSpeechError("Text is required")

    headers = {
        "Authorization": f"Bearer {DEAPI_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "text": text,
        "model": model,
        "voice": voice,
        "lang": lang,
        "speed": speed,
        "format": format,
        "sample_rate": sample_rate,
    }

    async with aiohttp.ClientSession(headers=headers) as session:
        # ── SUBMIT JOB ──
        async with session.post(TTS_ENDPOINT, json=payload, timeout=aiohttp.ClientTimeout(total=60)) as resp:
            if resp.status != 200:
                raise TextToSpeechError(f"txt2audio submit failed ({resp.status}): {await resp.text()}")
            response_data = await resp.json()
            request_id = response_data.get("data", {}).get("request_id")
            if not request_id:
                raise TextToSpeechError("No request_id returned")
            print(f"[TTS] Request submitted. request_id = {request_id}")

        # ── POLL FOR RESULT ──
        await asyncio.sleep(poll_delay)
        async with session.get(f"{BASE_URL}/results/{request_id}") as resp:
            if resp.status != 200:
                raise TextToSpeechError(f"Failed to fetch result ({resp.status}) for request_id={request_id}")
            result = await resp.json()

        status = result.get("data", {}).get("status")
        if status == "completed":
            audio_url = result.get("data", {}).get("output", {}).get("audio_url")
            if not audio_url:
                raise TextToSpeechError("Completed but no audio_url")
            return audio_url
        elif status in ("failed", "error"):
            raise TextToSpeechError(f"txt2audio failed: {result}")
        else:
            raise TextToSpeechError(f"Audio not ready after polling, status={status}")
