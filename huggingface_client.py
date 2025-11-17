# huggingface_client.py
import os
import asyncio
import aiohttp

HF_API_KEY = os.getenv("OPENROUTER_API_KEY")
HF_URL = "https://api.openrouter.ai/v1/chat/completions"
MODEL = "meta-llama/Llama-3.2-3B-Instruct"

async def call_hf(prompt, retry_delay=2, max_retries=3):
    """
    Sends prompt to Hugging Face OpenRouter and returns text response.
    Silently retries if rate-limited (429).
    """
    headers = {
        "Authorization": f"Bearer {HF_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 500,
        "temperature": 0.7
    }

    for attempt in range(max_retries):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(HF_URL, headers=headers, json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        # return content text
                        content = data["choices"][0]["message"]["content"]
                        return content
                    elif resp.status == 429:
                        # Rate-limited: wait and retry silently
                        await asyncio.sleep(retry_delay)
                    else:
                        # Other errors: log and retry
                        text = await resp.text()
                        print(f"Hugging Face API error {resp.status}: {text}")
                        await asyncio.sleep(retry_delay)
        except Exception as e:
            print(f"HF request exception: {e}")
            await asyncio.sleep(retry_delay)
    # If all retries fail, return a fallback
    return "🤖 (Sorry, I couldn't respond due to API limits.)"
