import argparse
import asyncio
import os
import requests

BASE_URL = "https://imggen-api-production.up.railway.app"
REQUEST_TIMEOUT = 60
ALLOWED_ASPECT_RATIOS = {"1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"}


def _generate_image_bytes(prompt, aspect_ratio="16:9"):
    """Call imggen txt2img API and return image bytes."""
    api_key = os.getenv("TEST_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing TEST_API_KEY environment variable")
    if not prompt.strip():
        raise ValueError("Prompt must not be empty")
    if aspect_ratio not in ALLOWED_ASPECT_RATIOS:
        raise ValueError(f"Invalid aspect ratio: {aspect_ratio}")

    response = requests.post(
        f"{BASE_URL}/generate",
        headers={"X-API-Key": api_key, "Content-Type": "application/json"},
        json={"prompt": prompt, "aspect_ratio": aspect_ratio},
        timeout=REQUEST_TIMEOUT,
    )

    if response.status_code != 200:
        try:
            error = response.json().get("error", response.text)
        except ValueError:
            error = response.text
        raise RuntimeError(f"API request failed ({response.status_code}): {error}")
    if not response.headers.get("Content-Type", "").startswith("image/"):
        raise RuntimeError(f"Unexpected content type: {response.headers.get('Content-Type', 'unknown')}")
    return response.content


def _get_imggen_balance(api_key):
    response = requests.get(
        f"{BASE_URL}/balance",
        headers={"X-API-Key": api_key},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()
    return float(data["balance"])


async def generate_image(prompt, aspect_ratio="16:9"):
    """Async wrapper for slash command integration."""
    image_bytes = await asyncio.to_thread(_generate_image_bytes, prompt, aspect_ratio)
    api_key = os.getenv("TEST_API_KEY", "").strip()
    balance = None
    if api_key:
        try:
            balance = await asyncio.to_thread(_get_imggen_balance, api_key)
        except requests.RequestException:
            pass
    return image_bytes, balance


def text_to_image(prompt, filename="txt2img_output.jpg", aspect_ratio="16:9"):
    image_bytes = _generate_image_bytes(prompt, aspect_ratio)

    with open(filename, "wb") as f:
        f.write(image_bytes)
    return filename


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test txt2img generation API")
    parser.add_argument("prompt", help="Text prompt for image generation")
    parser.add_argument("--output", default="txt2img_output.jpg", help="Output image filename")
    parser.add_argument(
        "--aspect-ratio",
        default="16:9",
        choices=sorted(ALLOWED_ASPECT_RATIOS),
        help="Aspect ratio",
    )
    args = parser.parse_args()

    output = text_to_image(args.prompt, filename=args.output, aspect_ratio=args.aspect_ratio)
    print(f"Saved image: {output}")
