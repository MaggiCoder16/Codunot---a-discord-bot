import json
import os
from datetime import datetime

CACHE_FILE = "chat_cache.json"


def save_to_cache(user_text: str, bot_reply: str):
    entry = {
        "user": user_text.strip().lower(),
        "reply": bot_reply.strip(),
        "timestamp": datetime.utcnow().isoformat()
    }

    if not os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "w") as f:
            json.dump([], f)

    try:
        with open(CACHE_FILE, "r") as f:
            data = json.load(f)
    except json.JSONDecodeError:
        data = []

    data.append(entry)

    with open(CACHE_FILE, "w") as f:
        json.dump(data, f, indent=2)
