import json
import os
from datetime import datetime

CACHE_FILE = os.path.join(os.getcwd(), "chat_cache.json")
MAX_CACHE_ENTRIES = 150_000


def save_to_cache(user_text: str, bot_reply: str):
    entry = {
        "user": user_text.strip().lower(),
        "reply": bot_reply.strip(),
        "timestamp": datetime.utcnow().isoformat()
    }

    # Create file if missing
    if not os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "w") as f:
            json.dump([], f)

    # Load existing cache
    try:
        with open(CACHE_FILE, "r") as f:
            data = json.load(f)
    except json.JSONDecodeError:
        data = []

    # Append new entry
    data.append(entry)

    # Trim to last 150,000 entries
    if len(data) > MAX_CACHE_ENTRIES:
        data = data[-MAX_CACHE_ENTRIES:]

    # Save back
    with open(CACHE_FILE, "w") as f:
        json.dump(data, f, indent=2)
    print(f"[CACHE] Entry saved. Current cache size: {len(data)} items.")
    print("[CACHE] File path:", os.path.abspath(CACHE_FILE))
