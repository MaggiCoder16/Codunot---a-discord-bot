import asyncio
import os
import time
import requests

BASE_URL = "https://imggen-api-production.up.railway.app"
REQUEST_TIMEOUT = 300
MAX_RETRIES = 3

ASPECT_RATIO_DIMENSIONS = {
    "1:1": (1024, 1024),
    "2:3": (832, 1216),
    "3:2": (1216, 832),
    "3:4": (832, 1088),
    "4:3": (1088, 832),
    "4:5": (832, 1024),
    "5:4": (1024, 832),
    "9:16": (1088, 1920),
    "16:9": (1920, 1088),
    "21:9": (2016, 864),
}
ALLOWED_ASPECT_RATIOS = set(ASPECT_RATIO_DIMENSIONS.keys())


class ImageAPIError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        super().__init__(f"API request failed ({status_code}): {message}")
        self.status_code = status_code


def _generate_image_bytes(prompt, aspect_ratio="16:9"):
    api_key = os.getenv("TEST_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing TEST_API_KEY environment variable")
    if not prompt.strip():
        raise ValueError("Prompt must not be empty")
    if aspect_ratio not in ALLOWED_ASPECT_RATIOS:
        raise ValueError(f"Invalid aspect ratio: {aspect_ratio}")

    width, height = ASPECT_RATIO_DIMENSIONS[aspect_ratio]
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.post(
                f"{BASE_URL}/flux2max",
                headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                json={"prompt": prompt, "width": width, "height": height, "safety_tolerance": 5},
                timeout=REQUEST_TIMEOUT,
            )
            if response.status_code != 200:
                try:
                    error = response.json().get("error", response.text)
                except ValueError:
                    error = response.text
                raise ImageAPIError(response.status_code, error)
            if not response.headers.get("Content-Type", "").startswith("image/"):
                raise RuntimeError(f"Unexpected content type: {response.headers.get('Content-Type', 'unknown')}")
            return response.content
        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError) as e:
            last_exc = e
            print(f"[IMGGEN] Attempt {attempt}/{MAX_RETRIES} failed: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(2 ** attempt)
        except ImageAPIError as e:
            if 500 <= e.status_code < 600 or (e.status_code == 400 and '"current":"failed"' in str(e)):
                last_exc = e
                print(f"[IMGGEN] Attempt {attempt}/{MAX_RETRIES} server error: {e}")
                if attempt < MAX_RETRIES:
                    time.sleep(2 ** attempt)
            else:
                raise
    raise last_exc


def _get_imggen_balance(api_key):
    response = requests.get(
        f"{BASE_URL}/balance",
        headers={"X-API-Key": api_key},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return float(response.json()["balance"])


async def generate_image(prompt, aspect_ratio="16:9"):
    image_bytes = await asyncio.to_thread(_generate_image_bytes, prompt, aspect_ratio)
    api_key = os.getenv("TEST_API_KEY", "").strip()
    balance = None
    if api_key:
        try:
            balance = await asyncio.to_thread(_get_imggen_balance, api_key)
        except requests.RequestException:
            pass
    return image_bytes, balance
