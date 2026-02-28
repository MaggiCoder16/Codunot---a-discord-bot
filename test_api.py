import argparse
import os
import requests

BASE_URL = "https://imggen-api-production.up.railway.app"
API_KEY = os.getenv("TEST_API_KEY", "").strip()
HEADERS = {"X-API-Key": API_KEY}
REQUEST_TIMEOUT = 60


def text_to_image(prompt, filename="txt2img_output.jpg", aspect_ratio="1:1"):
    if not API_KEY:
        raise RuntimeError("Missing TEST_API_KEY environment variable")

    response = requests.post(
        f"{BASE_URL}/generate",
        headers={**HEADERS, "Content-Type": "application/json"},
        json={"prompt": prompt, "aspect_ratio": aspect_ratio},
        timeout=REQUEST_TIMEOUT,
    )

    if response.status_code != 200:
        try:
            error = response.json().get("error", response.text)
        except ValueError:
            error = response.text
        raise RuntimeError(f"API request failed ({response.status_code}): {error}")

    with open(filename, "wb") as f:
        f.write(response.content)
    return filename


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test txt2img generation API")
    parser.add_argument("prompt", help="Text prompt for image generation")
    parser.add_argument("--output", default="txt2img_output.jpg", help="Output image filename")
    parser.add_argument("--aspect-ratio", default="1:1", help="Aspect ratio (e.g. 1:1, 16:9)")
    args = parser.parse_args()

    output = text_to_image(args.prompt, filename=args.output, aspect_ratio=args.aspect_ratio)
    print(f"Saved image: {output}")
