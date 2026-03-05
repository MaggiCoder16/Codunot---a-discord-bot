import asyncio
import aiohttp
import base64


PUTER_API_BASE = "https://api.puter.com/drivers/call"


async def _call_puter_api(driver: str, method: str, args: dict) -> dict:
    payload = {
        "interface": driver,
        "method": method,
        "args": args
    }
    
    headers = {
        "Content-Type": "application/json",
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(PUTER_API_BASE, json=payload, headers=headers) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                raise Exception(f"Puter API error ({resp.status}): {error_text}")
            
            return await resp.json()


async def puter_generate_image(prompt: str, model: str = "gpt-image-1.5", quality: str = "low") -> bytes:
    result = await _call_puter_api(
        driver="ai-txt2img",
        method="generate",
        args={
            "prompt": prompt,
            "provider": "openai-image-generation",
            "model": model,
            "quality": quality,
            "ratio": {"w": 1024, "h": 1024}
        }
    )
    
    if "url" in result:
        async with aiohttp.ClientSession() as session:
            async with session.get(result["url"]) as resp:
                if resp.status != 200:
                    raise Exception(f"Failed to download image: HTTP {resp.status}")
                return await resp.read()
    
    elif "data" in result:
        return base64.b64decode(result["data"])
    
    else:
        raise ValueError("Unexpected Puter API response format")


async def puter_text_to_speech(text: str, voice: str = "21m00Tcm4TlvDq8ikWAM", model: str = "eleven_v3") -> str:
    if len(text) > 3000:
        raise ValueError("Text must be less than 3000 characters")
    
    result = await _call_puter_api(
        driver="ai-txt2speech",
        method="generate",
        args={
            "text": text,
            "provider": "elevenlabs",
            "model": model,
            "voice": voice,
            "output_format": "mp3_44100_128"
        }
    )
    
    if "url" in result:
        return result["url"]
    else:
        raise ValueError("Unexpected Puter API response format")


async def puter_chat(messages: list, model: str = "gpt-5.2-chat", temperature: float = 0.7) -> str:
    result = await _call_puter_api(
        driver="ai-chat",
        method="complete",
        args={
            "messages": messages,
            "model": model,
            "temperature": temperature
        }
    )
    
    if "message" in result and "content" in result["message"]:
        return result["message"]["content"]
    elif "content" in result:
        return result["content"]
    else:
        raise ValueError("Unexpected Puter API response format")
