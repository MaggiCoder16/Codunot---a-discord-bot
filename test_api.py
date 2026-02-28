import argparse
import os
import requests

BASE_URL = "https://imggen-api-production.up.railway.app"
REQUEST_TIMEOUT = 60
ALLOWED_ASPECT_RATIOS = {"1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"}


def text_to_image(prompt, filename="txt2img_output.jpg", aspect_ratio="1:1"):
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

    with open(filename, "wb") as f:
        f.write(response.content)
    return filename


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test txt2img generation API")
    parser.add_argument("prompt", help="Text prompt for image generation")
    parser.add_argument("--output", default="txt2img_output.jpg", help="Output image filename")
    parser.add_argument(
        "--aspect-ratio",
        default="1:1",
        choices=sorted(ALLOWED_ASPECT_RATIOS),
        help="Aspect ratio",
    )
    args = parser.parse_args()

    output = text_to_image(args.prompt, filename=args.output, aspect_ratio=args.aspect_ratio)
    print(f"Saved image: {output}")
