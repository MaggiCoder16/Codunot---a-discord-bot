"""
Puter.js API Client
Free & unlimited AI generation (image, TTS, text)
Separate from paid API clients
"""

import puter
import asyncio
import base64
import re


async def puter_generate_image(prompt: str, model: str = "gpt-image-1.5", quality: str = "low") -> bytes:
    """
    Generate image using Puter.js (OpenAI GPT Image 1.5)

    Args:
        prompt: Image description
        model: Model name (default: gpt-image-1.5)
        quality: Image quality - "low" | "medium" | "high"

    Returns:
        bytes: PNG image data

    Example:
        image_bytes = await puter_generate_image("a cat playing piano")
    """
    loop = asyncio.get_running_loop()

    def _generate():
        result = puter.ai.txt2img(
            prompt=prompt,
            options={
                "provider": "openai-image-generation",
                "model": model,
                "quality": quality,
                "ratio": {"w": 1024, "h": 1024}
            }
        )
        return result

    image_element = await loop.run_in_executor(None, _generate)

    # Extract base64 from data URL (data:image/png;base64,...)
    data_url = image_element.src
    match = re.search(r'base64,(.*)', data_url)
    if not match:
        raise ValueError("Could not extract image bytes from data URL")

    return base64.b64decode(match.group(1))


async def puter_text_to_speech(text: str, voice: str = "21m00Tcm4TlvDq8ikWAM", model: str = "eleven_v3") -> str:
    """
    Generate TTS using Puter.js (ElevenLabs v3)

    Args:
        text: Text to convert to speech (max 3000 chars)
        voice: Voice ID (default: ElevenLabs Rachel)
        model: TTS model (default: eleven_v3)

    Returns:
        str: Audio URL (MP3) - download separately with aiohttp

    Example:
        audio_url = await puter_text_to_speech("Hello world")
        # Then download: async with aiohttp.get(audio_url) as resp: ...
    """
    if len(text) > 3000:
        raise ValueError("Text must be less than 3000 characters")

    loop = asyncio.get_running_loop()

    def _generate():
        audio = puter.ai.txt2speech(
            text=text,
            options={
                "provider": "elevenlabs",
                "model": model,
                "voice": voice,
                "output_format": "mp3_44100_128"
            }
        )
        return audio.src  # URL to audio file

    return await loop.run_in_executor(None, _generate)


async def puter_chat(messages: list, model: str = "gpt-5.2-chat", temperature: float = 0.7) -> str:
    """
    Generate text using Puter.js (GPT-5.2 Chat)

    Args:
        messages: List of message dicts with "role" and "content"
            Example: [
                {"role": "system", "content": "You are helpful"},
                {"role": "user", "content": "Hello"}
            ]
        model: Chat model (default: gpt-5.2-chat)
        temperature: Randomness 0-2 (default: 0.7)

    Returns:
        str: Generated text response

    Example:
        response = await puter_chat([
            {"role": "user", "content": "What is 2+2?"}
        ])
    """
    loop = asyncio.get_running_loop()

    def _generate():
        response = puter.ai.chat(
            messages=messages,
            options={
                "model": model,
                "temperature": temperature
            }
        )
        return response.message.content

    return await loop.run_in_executor(None, _generate)
