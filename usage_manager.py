import os
import json
import asyncio
from datetime import date, datetime, timedelta

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

channel_usage = {}          # daily usage
attachment_history = {}     # rolling timestamps (per channel/guild)

# ======================================================
# LIMIT CONFIGS
# ======================================================

# daily limits

LIMITS = {
    "basic": {
        "messages": 50,
        "attachments": 7,
    },
    "premium": {
        "messages": 100,
        "attachments": 10,
    },
    "gold": {
        "messages": float("inf"),
        "attachments": 15,
    },
}

# per 2 months

TOTAL_LIMITS = {
    "basic": 30,
    "premium": 50,
    "gold": 80,
}

ROLLING_WINDOW = timedelta(days=60)

# ======================================================
# TIER FILE LOADING
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
            if "#" in line:
                line = line.split("#", 1)[0].strip()
            if line:
                ids.add(line)
    return ids


PREMIUM_IDS = load_tier_file(PREMIUM_FILE)
GOLD_IDS = load_tier_file(GOLD_FILE)

# ======================================================
# TIER RESOLUTION
# ======================================================

def get_tier_key(message) -> str:
    if message.guild is not None:
        return str(message.guild.id)
    return str(message.channel.id)


def get_tier_from_message(message) -> str:
    key = get_tier_key(message)
    if key in GOLD_IDS:
        return "gold"
    if key in PREMIUM_IDS:
        return "premium"
    return "basic"

# ======================================================
# DAILY USAGE
# ======================================================

def get_usage(key: str) -> dict:
    today = date.today().isoformat()

    usage = channel_usage.setdefault(key, {
        "day": today,
        "messages": 0,
        "attachments": 0,
    })

    if usage["day"] != today:
        usage.update({
            "day": today,
            "messages": 0,
            "attachments": 0,
        })

    return usage


def check_limit(message, kind: str) -> bool:
    key = get_tier_key(message)
    tier = get_tier_from_message(message)
    usage = get_usage(key)
    limit = LIMITS[tier][kind]
    return usage[kind] < limit


def consume(message, kind: str):
    key = get_tier_key(message)
    usage = get_usage(key)
    usage[kind] += 1

# ======================================================
# ROLLING 2-MONTH TOTAL LIMITS
# ======================================================

def _prune(history: list[float]) -> list[float]:
    now = datetime.utcnow().timestamp()
    cutoff = now - ROLLING_WINDOW.total_seconds()
    return [t for t in history if t >= cutoff]


def check_total_limit(message, kind: str) -> bool:
    if kind != "attachments":
        return True

    key = get_tier_key(message)
    tier = get_tier_from_message(message)
    limit = TOTAL_LIMITS[tier]

    history = attachment_history.get(key, [])
    history = _prune(history)
    attachment_history[key] = history

    return len(history) < limit


def consume_total(message, kind: str):
    if kind != "attachments":
        return

    key = get_tier_key(message)
    history = attachment_history.setdefault(key, [])
    history.append(datetime.utcnow().timestamp())

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
# SAVE / LOAD
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
                "attachments": attachment_history
            }, f)
    except Exception as e:
        print("[SAVE TOTAL ERROR]", e)


def load_usage():
    global channel_usage, attachment_history

    if os.path.exists(USAGE_FILE):
        with open(USAGE_FILE) as f:
            channel_usage = json.load(f)

    if os.path.exists(TOTAL_FILE):
        with open(TOTAL_FILE) as f:
            data = json.load(f)
            attachment_history = data.get("attachments", {})

# ======================================================
# AUTOSAVE
# ======================================================

async def autosave_usage():
    while True:
        save_usage()
        await asyncio.sleep(60)
