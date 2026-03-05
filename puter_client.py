import asyncio
import base64
import re
import os
from puter import PuterAI, PuterAuthError, PuterAPIError


PUTER_USERNAME = os.getenv("PUTER_USERNAME", "")
PUTER_PASSWORD = os.getenv("PUTER_PASSWORD", "")

puter_client = None


def _get_client():
    global puter_client
    if puter_client is None:
        if not PUTER_USERNAME or not PUTER_PASSWORD:
            raise Exception("PUTER_USERNAME and PUTER_PASSWORD must be set in .env")
        
        puter_client = PuterAI(username=PUTER_USERNAME, password=PUTER_PASSWORD)
        if not puter_client.login():
            raise PuterAuthError("Failed to login to Puter")
    
    return puter_client


async def puter_generate_image(prompt: str, model: str = "gpt-image-1.5", quality: str = "low") -> bytes:
    loop = asyncio.get_running_loop()
    
    def _generate():
        client = _get_client()
        result = client.generate_image(
            prompt=prompt,
            model=model,
            quality=quality
        )
        return result
    
    try:
        result = await loop.run_in_executor(None, _generate)
        
        if isinstance(result, dict):
            data_url = result.get('src') or result.get('url') or result.get('data')
        else:
            data_url = str(result)
        
        if not data_url:
            raise ValueError("No image data in response")
        
        if data_url.startswith('data:'):
            match = re.search(r'base64,(.*)', data_url)
            if not match:
                raise ValueError("Could not extract image bytes")
            return base64.b64decode(match.group(1))
        else:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(data_url) as resp:
                    if resp.status != 200:
                        raise Exception(f"Failed to download image: HTTP {resp.status}")
                    return await resp.read()
    
    except PuterAuthError as e:
        raise Exception(f"Puter auth error: {e}")
    except PuterAPIError as e:
        raise Exception(f"Puter API error: {e}")


async def puter_text_to_speech(text: str, voice: str = "21m00Tcm4TlvDq8ikWAM", model: str = "eleven_v3") -> str:
    if len(text) > 3000:
        raise ValueError("Text must be less than 3000 characters")
    
    loop = asyncio.get_running_loop()
    
    def _generate():
        client = _get_client()
        result = client.text_to_speech(
            text=text,
            provider="elevenlabs",
            model=model,
            voice=voice
        )
        
        if isinstance(result, dict):
            return result.get('src') or result.get('url')
        return str(result)
    
    try:
        return await loop.run_in_executor(None, _generate)
    except PuterAuthError as e:
        raise Exception(f"Puter auth error: {e}")
    except PuterAPIError as e:
        raise Exception(f"Puter API error: {e}")


async def puter_chat(messages: list, model: str = "gpt-5.2-chat", temperature: float = 0.7) -> str:
    loop = asyncio.get_running_loop()
    
    def _generate():
        client = _get_client()
        
        user_message = messages[-1]['content'] if messages else ""
        
        response = client.chat(user_message)
        return response
    
    try:
        return await loop.run_in_executor(None, _generate)
    except PuterAuthError as e:
        raise Exception(f"Puter auth error: {e}")
    except PuterAPIError as e:
        raise Exception(f"Puter API error: {e}")
