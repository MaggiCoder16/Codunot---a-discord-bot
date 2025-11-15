# bot.py
"""
Codunot - Fully human-like Discord bot with safe Roast Mode.
Run: python bot.py

Environment variables:
  DISCORD_TOKEN   - Discord bot token
  GEN_API_KEY     - Gemini API key
  BOT_NAME        - optional, default "Codunot"
  CONTEXT_LENGTH  - optional, default 18
"""

import os
import asyncio
import random
import re
from datetime import datetime, timedelta

import discord
from discord import Message
from dotenv import load_dotenv

from memory import MemoryManager
from humanize import humanize_response, random_typing_delay, maybe_typo
from gemini_client import call_gemini
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEN_API_KEY = os.getenv("GEN_API_KEY")
BOT_NAME = os.getenv("BOT_NAME", "Codunot")
CONTEXT_LENGTH = int(os.getenv("CONTEXT_LENGTH", "18"))

if not DISCORD_TOKEN or not GEN_API_KEY:
    raise SystemExit("Set DISCORD_TOKEN and GEN_API_KEY environment variables before running.")

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True

client = discord.Client(intents=intents)
analyzer = SentimentIntensityAnalyzer()
memory = MemoryManager(limit=60, file_path="codunot_memory.json")

# ---------- roast config ----------
ROAST_PATTERNS = [
    r"\broast me\b",
    r"\broast\s+<@!?\d+>\b",
    r"\broast (him|her|them|this guy|this girl|this)\b",
    r"\binsult me\b",
    r"\bdiss me\b",
    r"\broast that\b",
    r"\broast (.+)$"
]

PROTECTED_KEYWORDS = [
    "race", "religion", "sexual orientation", "gender", "ethnicity",
    "muslim", "jew", "black", "white", "asian", "trans", "gay", "lesbian",
    "disabled", "disability", "handicap"
]

def triggers_roast(text: str):
    t = text.lower()
    for p in ROAST_PATTERNS:
        if re.search(p, t):
            return True
    return False

def target_is_protected(text: str) -> bool:
    t = text.lower()
    for kw in PROTECTED_KEYWORDS:
        if kw in t:
            return True
    return False

def short_vibe_label(text: str) -> str:
    s = analyzer.polarity_scores(text)["compound"]
    if re.search(r"\b(lol|lmao|xd|😂|🤣|rofl|haha)\b", text, flags=re.I):
        return "funny"
    if s >= 0.5:
        return "happy"
    if s <= -0.4:
        return "sad"
    return "neutral"

# ---------- send messages ----------
async def send_human_reply(channel, reply_text, original_message: Message = None):
    delay = random_typing_delay(len(reply_text))
    try:
        async with channel.typing():
            await asyncio.sleep(delay)
    except Exception:
        await asyncio.sleep(delay)

    if random.random() < 0.08 and len(reply_text) > 80:
        parts = re.split(r'(?<=[.!?])\s+', reply_text, maxsplit=1)
        if len(parts) == 2:
            await channel.send(parts[0].strip())
            await asyncio.sleep(random.uniform(0.4, 1.8))
            await channel.send(parts[1].strip())
            return
    await channel.send(reply_text)

# ---------- dead channel check ----------
async def dead_channel_check():
    while True:
        for channel in client.get_all_channels():
            if isinstance(channel, discord.TextChannel):
                last_msg_time = memory.get_last_timestamp(str(channel.id))
                if not last_msg_time or datetime.utcnow() - last_msg_time > timedelta(minutes=3):
                    await channel.send("its dead in here... anyone wanna talk?")
                    memory.add_message(str(channel.id), BOT_NAME, "its dead in here... anyone wanna talk?")
        await asyncio.sleep(180)

# ---------- message handler ----------
@client.event
async def on_message(message: Message):
    if message.author == client.user or message.author.bot:
        return

    chan_id = str(message.channel.id)
    memory.add_message(chan_id, message.author.display_name, message.content)

    addressed = client.user.mentioned_in(message) or re.search(rf'\b{re.escape(BOT_NAME)}\b', message.content, flags=re.I)
    short_msg = len(message.content.strip()) < 45
    active_chat = len(memory.get_recent_messages(chan_id, n=CONTEXT_LENGTH)) >= 3

    base_prob = 0.18
    if addressed:
        base_prob = 0.98
    if short_msg:
        base_prob = min(0.95, base_prob + 0.22)
    if active_chat:
        base_prob = min(0.92, base_prob + 0.12)

    if re.search(r"\b(don't respond|no bot|quiet|bot-off)\b", message.content, flags=re.I):
        return

    is_roast = triggers_roast(message.content)
    roast_target_name = None

    if is_roast:
        if target_is_protected(message.content):
            reply = random.choice([
                "nah I don't roast people for who they are, that's lame.",
                "I won't roast stuff about someone's identity. pick something else :)"
            ])
            await send_human_reply(message.channel, reply, message)
            memory.add_message(chan_id, BOT_NAME, reply)
            return

        # almost always roast @Ardunot
        roast_target_name = None
        for user in message.mentions:
            if user.display_name.lower() == "ardunot" and random.random() < 0.85:
                roast_target_name = user.display_name
                break
        if not roast_target_name:
            roast_target_name = message.mentions[0].display_name if message.mentions else "you"

        roast_prompt = build_roast_prompt(memory, chan_id, roast_target_name)
        raw = await call_gemini(roast_prompt)
        roast_text = sanitize_roast(raw)
        roast_text = humanize_and_safeify(roast_text)
        await send_human_reply(message.channel, roast_text, message)
        memory.add_message(chan_id, BOT_NAME, roast_text)
        return

    if random.random() > base_prob:
        memory.persist()
        return

    prompt = build_general_prompt(memory, chan_id)
    raw_resp = await call_gemini(prompt)
    if raw_resp.strip().startswith("(api error") or raw_resp.strip() == "":
        fallback = random.choice(["lol", "huh?", "true", "omg", "bruh"])
        reply = fallback
    else:
        reply = humanize_response(raw_resp)
    reply = re.sub(r"\bI am an? (AI|bot)\b", "", reply, flags=re.I).strip()
    if not reply:
        reply = random.choice(["lol", "omg", "true"])
    vibe = short_vibe_label(" ".join(memory.get_recent_flat(chan_id, n=6)))
    if random.random() < 0.38:
        from humanize import pick_emoji_for_vibe
        reply += " " + pick_emoji_for_vibe(vibe)

    await send_human_reply(message.channel, reply, message)
    memory.add_message(chan_id, BOT_NAME, reply)
    memory.persist()

# ---------- prompt builders ----------
def build_general_prompt(mem_manager: MemoryManager, channel_id: str) -> str:
    recent = mem_manager.get_recent_flat(channel_id, n=CONTEXT_LENGTH)
    history_text = "\n".join(recent)
    persona = (
        "You are Codunot, a normal human friend in a Discord chat. "
        "Never say you are a bot. Keep replies short, casual, with slang, emojis, and occasional typos. "
        "Sometimes use 'idk', 'nvm', 'lol', 'bruh'."
    )
    prompt = f"{persona}\n\nRecent chat:\n{history_text}\n\nReply as Codunot (one short message):"
    return prompt

def build_roast_prompt(mem_manager: MemoryManager, channel_id: str, target_name: str|None):
    recent = mem_manager.get_recent_flat(channel_id, n=12)
    history_text = "\n".join(recent)
    target_line = f"Target: {target_name}\n" if target_name else ""
    persona = (
        "You are Codunot, a witty human friend who can roast playfully. "
        "Write a short, funny, non-malicious roast. "
        "Never attack protected classes or someone's identity. "
        "Use slang and emoji. Keep it short (1-2 lines)."
    )
    prompt = f"{persona}\n{target_line}\nRecent chat:\n{history_text}\n\nGive one playful roast as Codunot:"
    return prompt

def sanitize_roast(text: str) -> str:
    t = re.sub(r"\s+", " ", text.strip())
    if len(t) > 200:
        t = t[:190].rsplit(" ",1)[0] + "..."
    return t

def humanize_and_safeify(text: str) -> str:
    t = maybe_typo(text)
    if random.random() < 0.45:
        t = random.choice(["lol", "bruh", "ngl"]) + " " + t
    if target_is_protected(t):
        return "nah I don't roast people for who they are."
    return t

# ---------- graceful shutdown ----------
async def _cleanup():
    await memory.close()
    await asyncio.sleep(0.1)

def run():
    try:
        asyncio.create_task(dead_channel_check())
        client.run(DISCORD_TOKEN)
    finally:
        asyncio.run(_cleanup())

if __name__ == "__main__":
    run()
  
