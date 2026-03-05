import asyncio
import base64
import re
from puter import Puter


puter_client = Puter()


async def puter_generate_image(prompt: str, model: str = "gpt-image-1.5", quality: str = "low") -> bytes:
    loop = asyncio.get_running_loop()
    
    def _generate():
        result = puter_client.ai.txt2img(
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
    
    data_url = image_element.src
    match = re.search(r'base64,(.*)', data_url)
    if not match:
        raise ValueError("Could not extract image bytes from data URL")
    
    return base64.b64decode(match.group(1))


async def puter_text_to_speech(text: str, voice: str = "21m00Tcm4TlvDq8ikWAM", model: str = "eleven_v3") -> str:
    if len(text) > 3000:
        raise ValueError("Text must be less than 3000 characters")
    
    loop = asyncio.get_running_loop()
    
    def _generate():
        audio = puter_client.ai.txt2speech(
            text=text,
            options={
                "provider": "elevenlabs",
                "model": model,
                "voice": voice,
                "output_format": "mp3_44100_128"
            }
        )
        return audio.src
    
    return await loop.run_in_executor(None, _generate)


async def puter_chat(messages: list, model: str = "gpt-5.2-chat", temperature: float = 0.7) -> str:
    loop = asyncio.get_running_loop()
    
    def _generate():
        response = puter_client.ai.chat(
            messages=messages,
            options={
                "model": model,
                "temperature": temperature
            }
        )
        return response.message.content
    
    return await loop.run_in_executor(None, _generate)
