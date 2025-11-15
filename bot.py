print("Starting bot.py...")

import os
import asyncio
import random
from datetime import datetime, timedelta
import discord
from discord import Message
from dotenv import load_dotenv

from memory import MemoryManager
from humanizer import humanize_response, maybe_typo, is_roast_trigger
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

# ---------- send messages (instant) ----------
async def send_human_reply(channel, reply_text, original_message: Message = None):
    await channel.send(reply_text)

# ---------- dead channel check ----------
async def dead_channel_check():
    """Checks dead channels every hour and sends a message if no activity in 1h."""
    await client.wait_until_ready()
    while True:
        now = datetime.utcnow()
        for guild in client.guilds:
            for channel in guild.text_channels:
                if guild.name in DEAD_CHAT_CHANNELS and channel.name in DEAD_CHAT_CHANNELS[guild.name]:
                    last_msg_time = memory.get_last_timestamp(str(channel.id))
                    if not last_msg_time or now - last_msg_time > timedelta(hours=1):
                        msg = random.choice([
                            "It's super quiet here... anyone up for a chat? 😎",
                            "Yo! Anyone awake in this channel? 🤔",
                            "Sup folks? Let's chat a bit! 😏"
                        ])
                        await send_human_reply(channel, msg)
                        memory.add_message(str(channel.id), BOT_NAME, msg)
        await asyncio.sleep(3600)  # check every 1 hour

# ---------- start conversation in channels immediately ----------
async def initiate_conversations():
    await client.wait_until_ready()
    for guild in client.guilds:
        for channel in guild.text_channels:
            if guild.name in DEAD_CHAT_CHANNELS and channel.name in DEAD_CHAT_CHANNELS[guild.name]:
                last_msg_time = memory.get_last_timestamp(str(channel.id))
                if not last_msg_time:
                    msg = random.choice([
                        "Heyyy, anyone up for a chat? 😎",
                        "Hello! Who's awake? 🤔",
                        "Sup? Let's start chatting! 😏"
                    ])
                    await send_human_reply(channel, msg)
                    memory.add_message(str(channel.id), BOT_NAME, msg)

# ---------- on_ready ----------
@client.event
async def on_ready():
    print(f"{BOT_NAME} is ready!")
    asyncio.create_task(dead_channel_check())
    asyncio.create_task(initiate_conversations())

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

# ---------- message handler ----------
@client.event
async def on_message(message: Message):
    if message.author == client.user or message.author.bot:
        return

    chan_id = str(message.channel.id)
    memory.add_message(chan_id, message.author.display_name, message.content)

    # Check roast trigger
    roast_target = is_roast_trigger(message.content)
    if roast_target:
        memory.set_roast_target(chan_id, roast_target)

    target = getattr(memory, "get_roast_target", lambda x: None)(chan_id)
    if target:
        roast_prompt = build_roast_prompt(memory, chan_id, target)
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

# ---------- graceful shutdown ----------
async def _cleanup():
    await memory.close()
    await asyncio.sleep(0.1)

# ---------- run bot ----------
def run():
    client.run(DISCORD_TOKEN)

if __name__ == "__main__":
    run()
