import asyncio
import os

import aiohttp
from dotenv import load_dotenv

load_dotenv()

GOOGLE_AI_STUDIO_API_KEY = os.getenv("GOOGLE_AI_STUDIO_API_KEY") or os.getenv("GEMINI_API_KEY")
GOOGLE_API_BASE = "https://generativelanguage.googleapis.com/v1beta"

SESSION: aiohttp.ClientSession | None = None


def clean_log(text: str) -> str:
	if not text:
		return text
	if GOOGLE_AI_STUDIO_API_KEY:
		text = text.replace(GOOGLE_AI_STUDIO_API_KEY, "***")
	return text


async def get_session():
	global SESSION
	if SESSION is None or SESSION.closed:
		SESSION = aiohttp.ClientSession()
	return SESSION


async def call_google_ai_studio(
	prompt: str,
	model: str = "gemini-2.5-flash-lite",
	temperature: float = 0.7,
	retries: int = 3,
) -> str | None:
	"""
	Call Google AI Studio Gemini API via generateContent endpoint.
	"""
	if not GOOGLE_AI_STUDIO_API_KEY:
		print("[GOOGLE AI STUDIO] Missing GOOGLE_AI_STUDIO_API_KEY (or GEMINI_API_KEY)")
		return None

	session = await get_session()
	url = f"{GOOGLE_API_BASE}/models/{model}:generateContent?key={GOOGLE_AI_STUDIO_API_KEY}"
	payload = {
		"contents": [{"role": "user", "parts": [{"text": prompt}]}],
		"generationConfig": {
			"temperature": temperature,
		},
	}

	backoff = 1
	for attempt in range(1, retries + 1):
		try:
			async with session.post(url, json=payload, timeout=60) as resp:
				text = await resp.text()

				if resp.status == 200:
					data = await resp.json()
					candidates = data.get("candidates") or []
					if not candidates:
						return None

					parts = candidates[0].get("content", {}).get("parts", [])
					response_text = "".join(part.get("text", "") for part in parts).strip()
					return response_text or None

				print("\n===== GOOGLE AI STUDIO ERROR =====")
				print(f"Attempt {attempt}/{retries}, Status: {resp.status}")
				print(clean_log(text))
				print("==================================\n")

				if resp.status in (400, 401, 403):
					return None

				if resp.status in (429, 500, 503):
					await asyncio.sleep(backoff)
					backoff = min(backoff * 2, 8)
					continue

		except Exception as e:
			print(f"[GOOGLE AI STUDIO ERROR] Attempt {attempt}/{retries}: {clean_log(str(e))}")
			if attempt == retries:
				return None
			await asyncio.sleep(backoff)
			backoff = min(backoff * 2, 8)

	return None
