import os
import asyncio
import random
import re
from datetime import datetime, timedelta

import discord
from discord import Message
from dotenv import load_dotenv

from memory import MemoryManager
from humanizer import humanize_response, random_typing_delay, maybe_typo
from gemini_client import call_gemini
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEN_API_KEY = os.getenv("GEMINI_API_KEY")
BOT_NAME = os.getenv("BOT_NAME", "Codunot")
CONTEXT_LENGTH = int(os.getenv("CONTEXT_LENGTH", "18"))

if not DISCORD_TOKEN or not GEN_API_KEY:
    raise SystemExit("Set DISCORD_TOKEN and GEMINI_API_KEY before running.")

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

analyzer = SentimentIntensityAnalyzer()
memory = MemoryManager(limit=60, file_path="codunot_memory.json")

# ---------- channels for dead chat messages ----------
DEAD_CHAT_CHANNELS = {
    "ROYALRACER FANS": ["testing", "coders", "general"],
    "OPEN TO ALL": ["general"]
}

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
    await client.wait_until_ready()
    while True:
        for guild in client.guilds:
            for channel in guild.text_channels:
                if guild.name in DEAD_CHAT_CHANNELS and channel.name in DEAD_CHAT_CHANNELS[guild.name]:
                    last_msg_time = memory.get_last_timestamp(str(channel.id))
                    if not last_msg_time or datetime.utcnow() - last_msg_time > timedelta(minutes=3):
                        msg = "its dead in here... anyone wanna talk?"
                        await send_human_reply(channel, msg)
        await asyncio.sleep(180)

# ---------- on_ready ----------
@client.event
async def on_ready():
    print(f"{BOT_NAME} is ready!")
    asyncio.create_task(dead_channel_check())

# ---------- message handler ----------
@client.event
async def on_message(message: Message):
    if message.author == client.user or message.author.bot:
        return

    chan_id = str(message.channel.id)
    memory.add_message(chan_id, message.author.display_name, message.content)

    # Roast logic
    is_roast = bool(re.search(r"\broast\b", message.content, re.I) or "ardunot" in message.content.lower())
    if is_roast:
        roast_target = "Ardunot"
        roast_prompt = build_roast_prompt(memory, chan_id, roast_target)
        raw = await call_gemini(roast_prompt)
        roast_text = humanize_and_safeify(raw)
        if len(roast_text) > 200:
            roast_text = roast_text[:200] + "..."
        await send_human_reply(message.channel, roast_text, message)
        memory.add_message(chan_id, BOT_NAME, roast_text)
        return

    # Normal conversation
    prompt = build_general_prompt(memory, chan_id)
    raw_resp = await call_gemini(prompt)
    reply = humanize_response(raw_resp) if raw_resp.strip() else random.choice(["lol", "huh?", "true", "omg", "bruh"])
    if len(reply) > 200:
        reply = reply[:200] + "..."
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
    return f"{persona}\n\nRecent chat:\n{history_text}\n\nReply as Codunot (one short message):"

def build_roast_prompt(mem_manager: MemoryManager, channel_id: str, target_name: str | None):
    recent = mem_manager.get_recent_flat(channel_id, n=12)
    history_text = "\n".join(recent)
    target_line = f"Target: {target_name}\n" if target_name else ""
    persona = (
        "You are Codunot, a witty human friend who can roast playfully. "
        "Write a short, funny, non-malicious roast. "
        "Never attack protected classes or someone's identity. "
        "Use slang and emoji. Keep it short (1-2 lines)."
    )
    return f"{persona}\n{target_line}\nRecent chat:\n{history_text}\n\nGive one playful roast as Codunot:"

def humanize_and_safeify(text: str) -> str:
    t = maybe_typo(text)
    if random.random() < 0.45:
        t = random.choice(["lol", "bruh", "ngl"]) + " " + t
    return t

# ---------- graceful shutdown ----------
async def _cleanup():
    await memory.close()
    await asyncio.sleep(0.1)

# ---------- run bot ----------
def run():
    client.run(DISCORD_TOKEN)

if __name__ == "__main__":
    run()
