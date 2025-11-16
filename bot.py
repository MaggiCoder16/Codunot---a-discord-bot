print("Starting bot.py...")

import os
import asyncio
import random
import re
from datetime import datetime, timedelta
import discord
from discord import Message
from dotenv import load_dotenv
import openai

from memory import MemoryManager
from humanizer import humanize_response, maybe_typo, is_roast_trigger

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("GEMINI_API_KEY")
BOT_NAME = os.getenv("BOT_NAME", "Codunot")
CONTEXT_LENGTH = int(os.getenv("CONTEXT_LENGTH", "18"))

if not DISCORD_TOKEN or not OPENAI_API_KEY:
    raise SystemExit("Set DISCORD_TOKEN and OPENAI_API_KEY before running.")

openai.api_key = OPENAI_API_KEY

intents = discord.Intents.all()
intents.message_content = True
client = discord.Client(intents=intents)

memory = MemoryManager(limit=60, file_path="codunot_memory.json")

# ---------------- BOT MODES ----------------
MODES = {"funny": True, "roast": False, "serious": False}
MAX_MSG_LEN = 200

# ---------------- OWNER QUIET/SPEAK ----------------
OWNER_ID = 1220934047794987048
owner_mute_until = None

# ---------- dead chat channels ----------
DEAD_CHAT_CHANNELS = {
    "ROYALRACER FANS": ["testing", "coders", "general"],
    "OPEN TO ALL": ["general"]
}
dead_message_count = {}  # {(guild_id, channel_id): count}
dm_dead_count = {}  # {user_id: count}

# ---------- message queue for throttling ----------
message_queue = asyncio.Queue()
api_lock = asyncio.Lock()  # ensure only one API request at a time

# ---------- helper to format human-readable durations ----------
def format_duration(num: int, unit: str) -> str:
    unit_map = {"s": "second", "m": "minute", "h": "hour", "d": "day"}
    name = unit_map.get(unit, "unknown")
    if num != 1:
        name += "s"
    return f"{num} {name}"

# ---------- helper to send long messages ----------
async def send_long_message(channel, text):
    while len(text) > 0:
        chunk = text[:MAX_MSG_LEN]
        text = text[MAX_MSG_LEN:]
        if len(text) > 0:
            chunk += "..."
            text = "..." + text
        await message_queue.put((channel, chunk))

async def process_queue():
    while True:
        channel, content = await message_queue.get()
        try:
            await channel.send(content)
        except Exception:
            pass
        await asyncio.sleep(0.1)

# ---------- send messages ----------
async def send_human_reply(channel, reply_text):
    if len(reply_text) > MAX_MSG_LEN:
        await send_long_message(channel, reply_text)
    else:
        await message_queue.put((channel, reply_text))

# ---------- dead channel check ----------
async def dead_channel_check():
    await client.wait_until_ready()
    while True:
        now = datetime.utcnow()
        for guild in client.guilds:
            for channel in guild.text_channels:
                if guild.name in DEAD_CHAT_CHANNELS and channel.name in DEAD_CHAT_CHANNELS[guild.name]:
                    key = (guild.id, channel.id)
                    last_msg_time = memory.get_last_timestamp(str(channel.id))
                    count = dead_message_count.get(key, 0)
                    if (not last_msg_time or now - last_msg_time > timedelta(hours=3)) and count < 2:
                        msg = "its dead in here... anyone wanna talk?"
                        await send_human_reply(channel, msg)
                        dead_message_count[key] = count + 1
        for user_id, count in dm_dead_count.items():
            if count >= 2:
                continue
            user = await client.fetch_user(user_id)
            last_dm_time = memory.get_last_timestamp(f"dm_{user_id}")
            if not last_dm_time or now - last_dm_time > timedelta(hours=4):
                msg = "hey bro, wanna talk? I'm bored rn"
                await send_human_reply(user, msg)
                dm_dead_count[user_id] = count + 1
        await asyncio.sleep(3600)

# ---------- start conversation ----------
async def initiate_conversation():
    await client.wait_until_ready()
    for guild in client.guilds:
        for channel in guild.text_channels:
            if guild.name in DEAD_CHAT_CHANNELS and channel.name in DEAD_CHAT_CHANNELS[guild.name]:
                msg = random.choice([
                    "heyyy anyone up for a chat? 😎",
                    "sup guys, what's up?",
                    "bruh, let's talk a bit lol"
                ])
                await send_human_reply(channel, msg)

# ---------- build prompts ----------
def build_general_prompt(mem_manager: MemoryManager, channel_id: str) -> str:
    recent = mem_manager.get_recent_flat(channel_id, n=CONTEXT_LENGTH)
    history_text = "\n".join(recent)
    persona = (
        "You are Codunot, a normal human friend in a Discord chat. "
        "Never say you are a bot. Keep replies short, casual, with slang, emojis, and occasional typos. "
        "Sometimes use 'idk', 'nvm', 'lol', 'bruh'."
    )
    if MODES["serious"]:
        persona = (
            "You are Codunot, friendly, helpful, concise, proper grammar. No slang, no emoji. "
            "Keep replies professional."
        )
    return f"{persona}\n\nRecent chat:\n{history_text}\n\nReply as Codunot (one short message):"

def build_roast_prompt(mem_manager: MemoryManager, channel_id: str, target_name: str | None):
    recent = mem_manager.get_recent_flat(channel_id, n=12)
    history_text = "\n".join(recent)
    target_line = f"Target: {target_name}\n" if target_name else ""
    persona = (
        "You are Codunot, a witty human friend who can roast HARD. "
        "Write short, funny, creative roasts with slang and emoji. "
        "Never attack protected classes or identity."
    )
    return f"{persona}\n{target_line}\nRecent chat:\n{history_text}\n\nGive one roast as Codunot:"

def humanize_and_safeify(text: str) -> str:
    t = maybe_typo(text)
    if random.random() < 0.45 and not MODES["serious"]:
        t = random.choice(["lol", "bruh", "ngl"]) + " " + t
    return t

# ---------- GPT call using GPT-3.5-turbo ----------
async def call_openai(prompt: str) -> str:
    async with api_lock:
        try:
            resp = await openai.ChatCompletion.acreate(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=600,
                temperature=0.8
            )
            return resp.choices[0].message.content.strip()
        except Exception:
            return "Hmm, API is acting up!"

# ---------- on_ready ----------
@client.event
async def on_ready():
    print(f"{BOT_NAME} is ready!")
    asyncio.create_task(dead_channel_check())
    asyncio.create_task(initiate_conversation())
    asyncio.create_task(process_queue())

# ---------- on_message ----------
@client.event
async def on_message(message: Message):
    global owner_mute_until
    if message.author == client.user:
        return

    now = datetime.utcnow()
    if owner_mute_until and now < owner_mute_until:
        return

    chan_id = str(message.channel.id) if not isinstance(message.channel, discord.DMChannel) else f"dm_{message.author.id}"
    memory.add_message(chan_id, message.author.display_name, message.content)

    # DM intro
    if isinstance(message.channel, discord.DMChannel) and len(memory.get_recent_flat(chan_id, 1)) == 1:
        intro = ("Hi! I'm Codunot, a bot who yaps like a human, but is AI! "
                 "I have 3 modes - !roastmode, !funmode, and !seriousmode. Try them all!")
        await send_human_reply(message.channel, intro)

    # Owner mute commands
    if message.author.id == OWNER_ID:
        quiet_match = re.match(r"!quiet (\d+)([smhd])", message.content.lower())
        if quiet_match:
            num, unit = int(quiet_match.group(1)), quiet_match.group(2)
            seconds = num * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
            owner_mute_until = datetime.utcnow() + timedelta(seconds=seconds)
            human_time = format_duration(num, unit)
            await send_human_reply(message.channel, f"I'll be quiet for {human_time} as my owner muted me. Cyu soon!")
            return
        if message.content.lower().startswith("!speak"):
            owner_mute_until = None
            await send_human_reply(message.channel, "YOOO I'M BACK FROM MY TIMEOUT WASSUP GUYS!!!!")
            return

    # Modes commands
    if message.content.startswith("!roastmode"):
        MODES.update({"roast": True, "serious": False, "funny": False})
        await send_human_reply(message.channel, "😂 Roast/funny mode activated!")
        return
    elif message.content.startswith("!seriousmode"):
        MODES.update({"roast": False, "serious": True, "funny": False})
        await send_human_reply(message.channel, "🤓 Serious/helpful mode activated!")
        return
    elif message.content.startswith("!funmode"):
        MODES.update({"roast": False, "serious": False, "funny": True})
        await send_human_reply(message.channel, "😎 Fun casual mode activated!")
        return

    # ROAST mode
    if MODES["roast"]:
        roast_target = is_roast_trigger(message.content)
        if roast_target:
            memory.set_roast_target(chan_id, roast_target)
        target = memory.get_roast_target(chan_id)
        if target:
            roast_prompt = build_roast_prompt(memory, chan_id, target)
            raw = await call_openai(roast_prompt)
            if raw:
                roast_text = humanize_and_safeify(raw)
                await send_human_reply(message.channel, roast_text)
                memory.add_message(chan_id, BOT_NAME, roast_text)
            return

    # GENERAL conversation
    prompt = build_general_prompt(memory, chan_id)
    raw_resp = await call_openai(prompt)
    reply = humanize_response(raw_resp) if raw_resp.strip() else random.choice(["lol", "huh?", "true", "omg", "bruh"])
    await send_human_reply(message.channel, reply)
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
