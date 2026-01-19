import os
import json
import asyncio
from datetime import date

# ======================================================
# FILE PATHS
# ======================================================

USAGE_FILE = "daily_usage.json"
TOTAL_FILE = "total_usage.json"

PREMIUM_FILE = "tiers_premium.txt"
GOLD_FILE = "tiers_gold.txt"

# ======================================================
# IN-MEMORY STORES
# ======================================================

channel_usage = {}          # daily (resets each day)
total_image_count = {}     # lifetime
total_file_count = {}      # lifetime

# ======================================================
# LIMIT CONFIGS
# ======================================================

LIMITS = {
    "basic": {
        "messages": 50,
        "images": 7,
        "files": 5,
    },
    "premium": {
        "messages": 100,
        "images": 10,
        "files": 10,
    },
    "gold": {
        "messages": float("inf"),
        "images": float("inf"),
        "files": float("inf"),
    },
}

TOTAL_LIMITS = {
    "basic": {
        "images": 30,
        "files": 20,
    },
    "premium": {
        "images": 50,
        "files": 35,
    },
    "gold": {
        "images": float("inf"),
        "files": float("inf"),
    },
}

# ======================================================
# TIER FILE LOADING (SUPPORTS COMMENTS)
# ======================================================

def load_tier_file(path: str) -> set[str]:
    ids = set()
    if not os.path.exists(path):
        return ids

    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # allow inline comments
            if "#" in line:
                line = line.split("#", 1)[0].strip()

            if line:
                ids.add(line)

    return ids


PREMIUM_IDS = load_tier_file(PREMIUM_FILE)
GOLD_IDS = load_tier_file(GOLD_FILE)

# ======================================================
# TIER RESOLUTION (SERVER / DM SAFE)
# ======================================================

def get_tier_key(message) -> str:
    # Server message → server ID
    if message.guild is not None:
        return str(message.guild.id)

    # DM → channel ID
    return str(message.channel.id)


def get_tier_from_message(message) -> str:
    key = get_tier_key(message)

    if key in GOLD_IDS:
        return "gold"
    if key in PREMIUM_IDS:
        return "premium"
    return "basic"

# ======================================================
# DAILY USAGE (RESETS AUTOMATICALLY)
# ======================================================

def get_usage(key: str) -> dict:
    today = date.today().isoformat()

    usage = channel_usage.setdefault(key, {
        "day": today,
        "messages": 0,
        "images": 0,
        "files": 0,
    })

    if usage["day"] != today:
        usage.update({
            "day": today,
            "messages": 0,
            "images": 0,
            "files": 0,
        })

    return usage


def check_limit(message, key: str, kind: str) -> bool:
    tier = get_tier_from_message(message)
    limits = LIMITS[tier]
    usage = get_usage(key)

    return usage[kind] < limits[kind]


def consume(key: str, kind: str):
    usage = get_usage(key)
    usage[kind] += 1

# ======================================================
# TOTAL (LIFETIME) LIMITS
# ======================================================

def check_total_limit(message, key: str, kind: str) -> bool:
    tier = get_tier_from_message(message)
    limit = TOTAL_LIMITS[tier][kind]

    if limit == float("inf"):
        return True

    store = total_image_count if kind == "images" else total_file_count
    return store.get(key, 0) < limit


def consume_total(key: str, kind: str):
    store = total_image_count if kind == "images" else total_file_count
    store[key] = store.get(key, 0) + 1

# ======================================================
# DENY MESSAGE
# ======================================================

async def deny_limit(message, kind: str):
    tier = get_tier_from_message(message)
    await message.reply(
        f"🚫 **{tier.upper()}** limit hit for `{kind}`.\n"
        "Contact **aarav_2022** for an upgrade."
    )

# ======================================================
# SAVE / LOAD (GITHUB ACTIONS SAFE)
# ======================================================

def save_usage():
    try:
        with open(USAGE_FILE, "w") as f:
            json.dump(channel_usage, f)
    except Exception as e:
        print("[SAVE DAILY ERROR]", e)

    try:
        with open(TOTAL_FILE, "w") as f:
            json.dump({
                "images": total_image_count,
                "files": total_file_count,
            }, f)
    except Exception as e:
        print("[SAVE TOTAL ERROR]", e)


def load_usage():
    global channel_usage, total_image_count, total_file_count

    if os.path.exists(USAGE_FILE):
        with open(USAGE_FILE) as f:
            channel_usage = json.load(f)

    if os.path.exists(TOTAL_FILE):
        with open(TOTAL_FILE) as f:
            data = json.load(f)
            total_image_count = data.get("images", {})
            total_file_count = data.get("files", {})

# ======================================================
# AUTOSAVE LOOP
# ======================================================

async def autosave_usage():
    while True:
        save_usage()
        await asyncio.sleep(60)
