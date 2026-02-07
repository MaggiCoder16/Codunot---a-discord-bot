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
    "gold": 100,
}

ROLLING_WINDOW = timedelta(days=60)

# ======================================================
# TIER FILE LOADING
# ======================================================

def load_tier_file(path: str) -> set[str]:
    """Load server IDs from a tier file, ignoring comments and whitespace."""
    ids = set()
    if not os.path.exists(path):
        return ids

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            # Remove comments and whitespace
            line = line.split("#", 1)[0].strip()
            if line:
                ids.add(line)
    return ids

PREMIUM_IDS = load_tier_file(PREMIUM_FILE)
GOLD_IDS = load_tier_file(GOLD_FILE)

# Debug prints to check what was loaded
print(f"Loaded premium IDs: {sorted(PREMIUM_IDS)}")
print(f"Loaded gold IDs: {sorted(GOLD_IDS)}")

# ======================================================
# TIER RESOLUTION
# ======================================================

def get_tier_key(message) -> str:
    """Returns the key to track usage: guild ID or channel ID."""
    if message.guild is not None:
        return str(message.guild.id)
    return str(message.channel.id)

def get_tier_from_message(message) -> str:
    """Return the tier of the channel/server."""
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
    tier = get_tier_from_message(message)
    usage = get_usage(key)

    if usage[kind] >= LIMITS[tier][kind]:
        print(
            "[BLOCKED] daily limit hit but consume() was called",
            "key=", key,
            "tier=", tier,
            "kind=", kind,
            "count=", usage[kind]
        )
        return

    usage[kind] += 1
    # Save immediately after consuming
    save_usage()

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

    ts = datetime.utcnow().timestamp()
    history.append(ts)

    daily = get_usage(key)["attachments"]
    tier = get_tier_from_message(message)
    daily_limit = LIMITS[tier]["attachments"]
    total_limit = TOTAL_LIMITS[tier]

    print(
        "[ATTACHMENT LOGGED]",
        "key=", key,
        f"daily={daily}/{daily_limit}",
        f"rolling={len(_prune(history))}/{total_limit}",
        "time=", datetime.utcfromtimestamp(ts).isoformat()
    )
    
    # Save immediately after consuming total
    save_usage()


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
    """Save usage data to JSON files"""
    try:
        with open(USAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(channel_usage, f, indent=2)
    except Exception as e:
        print("[SAVE DAILY ERROR]", e)

    try:
        with open(TOTAL_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "attachments": attachment_history
            }, f, indent=2)
    except Exception as e:
        print("[SAVE TOTAL ERROR]", e)

def load_usage():
    """Load usage data from JSON files"""
    global channel_usage, attachment_history

    if os.path.exists(USAGE_FILE):
        try:
            with open(USAGE_FILE, encoding="utf-8") as f:
                channel_usage = json.load(f)
            print(f"[LOAD] Loaded daily usage from {USAGE_FILE}")
        except Exception as e:
            print(f"[LOAD DAILY ERROR] {e}")

    if os.path.exists(TOTAL_FILE):
        try:
            with open(TOTAL_FILE, encoding="utf-8") as f:
                data = json.load(f)
                attachment_history = data.get("attachments", {})
            print(f"[LOAD] Loaded total usage from {TOTAL_FILE}")
        except Exception as e:
            print(f"[LOAD TOTAL ERROR] {e}")

# ======================================================
# AUTOSAVE (periodic backup every 5 minutes)
# ======================================================

async def autosave_usage():
    """Periodically save usage data as a backup"""
    while True:
        await asyncio.sleep(300)  # 5 minutes instead of 1 minute
        save_usage()
