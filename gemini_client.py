# gemini_client.py
import aiohttp
import os

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Correct Gemini-2.5-Flash endpoint
API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

async def call_gemini(prompt: str) -> str:
    """
    Calls Gemini-2.5-Flash API asynchronously.
    Returns generated text, or a safe placeholder if the API/network fails.
    """
    if not GEMINI_API_KEY:
        return "(missing API key)"

    params = {"key": GEMINI_API_KEY}
    headers = {"Content-Type": "application/json"}

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ]
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(API_URL, params=params, headers=headers, json=payload) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    print(f"[Gemini API] HTTP error {resp.status}: {text}")
                    return f"(api error: {resp.status})"

                data = await resp.json()

                # Parse Gemini-2.5-Flash response correctly
                return (
                    data.get("candidates", [{}])[0]
                    .get("content", {})
                    .get("parts", [{}])[0]
                    .get("text", "(empty response)")
                )

    except aiohttp.ClientConnectorError as e:
        print(f"[Gemini API] Connection error: {e}")
        return "(network error)"
    except Exception as e:
        print(f"[Gemini API] Unexpected error: {e}")
        return "(unexpected error)"
