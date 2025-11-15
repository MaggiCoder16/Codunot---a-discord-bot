# gemini_client.py
import aiohttp
from config import GEMINI_API_KEY

API_URL = "https://api.genai.google/v1beta2/models/text-bison-001:generate"

async def call_gemini(prompt: str) -> str:
    headers = {
        "Authorization": f"Bearer {GEMINI_API_KEY}",
        "Content-Type": "application/json"
    }
    json_data = {
        "prompt": prompt,
        "temperature": 0.7,
        "max_output_tokens": 150
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(API_URL, headers=headers, json=json_data) as resp:
            if resp.status != 200:
                return "(api error)"
            data = await resp.json()
            # The exact response field depends on Gemini API version
            # Usually: data['candidates'][0]['content'] or data['output_text']
            return data.get("candidates", [{}])[0].get("content", "")

