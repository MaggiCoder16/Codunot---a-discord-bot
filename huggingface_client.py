import aiohttp
import os
import asyncio

HF_API_KEY = os.getenv("HF_API_KEY")
HF_URL = "https://router.huggingface.co/v1/chat/completions"
MODEL = "meta-llama/Llama-3.2-3B-Instruct"

async def call_hf(prompt: str, retry_delay=2):
    headers = {"Authorization": f"Bearer {HF_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 220
    }

    for attempt in range(3):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(HF_URL, headers=headers, json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data["choices"][0]["message"]["content"]
                    elif resp.status == 429:
                        await asyncio.sleep(retry_delay)
                    else:
                        return "AI failed to respond."
        except Exception:
            await asyncio.sleep(retry_delay)
    return None
