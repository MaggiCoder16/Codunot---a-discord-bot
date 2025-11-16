print("Starting bot.py...")

import os
import asyncio
import random
import re
from datetime import datetime, timedelta
import discord
from discord import Message
from dotenv import load_dotenv

from memory import MemoryManager
from humanizer import humanize_response, maybe_typo, is_roast_trigger
from gemini_client import call_gemini  # your Gemini API wrapper

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEN_API_KEY = os.getenv("GEMINI_API_KEY")
BOT_NAME = os.getenv("BOT_NAME", "Codunot")
BOT_USER_ID = 1435987186502733878
CONTEXT_LENGTH = int(os.getenv("CONTEXT_LENGTH", "18"))

if not DISCORD_TOKEN or not GEN_API_KEY:
    raise SystemExit("Set DISCORD_TOKEN and GEMINI_API_KEY before running.")

intents = discord.Intents.all()
intents.message_content = True
client = discord.Client(intents=intents)

memory = MemoryManager(limit=60, file_path="codunot_memory.json")

# ---------------- BOT MODES ----------------
MODES = {"funny": True, "roast": False, "serious": False}
MAX_MSG_LEN = 3000

# ---------------- OWNER QUIET/SPEAK ----------------
OWNER_ID = 1220934047794987048
owner_mute_until = None

# ---------- dead chat channels ----------
DEAD_CHAT_CHANNELS = {
    "ROYALRACER FANS": ["testing", "coders", "general"],
    "OPEN TO ALL": ["general"]
}
dead_message_count = {}
dm_dead_count = {}

message_queue = asyncio.Queue()


# ---------- helper functions ----------
def format_duration(num: int, unit: str) -> str:
    unit_map = {"s": "second", "m": "minute", "h": "hour", "d": "day"}
    name = unit_map.get(unit, "minute")
    if num == 1:
        return f"1 {name}"
    else:
        return f"{num} {name}s"


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
        await asyncio.sleep(0.02)


async def send_human_reply(channel, reply_text):
    if len(reply_text) > MAX_MSG_LEN:
        await send_long_message(channel, reply_text)
    else:
        await message_queue.put((channel, reply_text))


# ---------- dead channel checks ----------
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
                        await send_human_reply(channel, "its dead in here... anyone wanna talk?")
                        dead_message_count[key] = count + 1
        await asyncio.sleep(3600)


# ---------- conversation initiation ----------
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


# ---------- PROMPTS ----------
def build_general_prompt(mem_manager, channel_id):
    recent = mem_manager.get_recent_flat(channel_id, n=CONTEXT_LENGTH)
    history_text = "\n".join(recent)

    persona_self_protect = (
        "Never roast or attack yourself (Codunot). "
        "If asked to roast Codunot, gently refuse or redirect."
    )

    if MODES["serious"]:
        persona = (
            "You are Codunot, a precise and knowledgeable helper. "
            "You answer with direct factual information. No emojis, no slang."
        )
    elif MODES["roast"]:
        persona = (
            "You are Codunot, a savage roast-master. "
            "NEVER roast yourself. Only roast non-bot users. "
            "Roasts are nuclear-level, offensive but NOT targeting protected classes."
        )
    else:
        persona = (
            "You are Codunot, a playful, funny Discord friend. "
            "Light roasts, friendly jokes, emojis allowed."
        )

    return (
        f"{persona}\n"
        f"{persona_self_protect}\n"
        f"My user ID is {BOT_USER_ID}.\n"
        f"If asked 'who made you', ALWAYS answer: '@aarav_2022 (ID: 1220934047794987048) made me.'\n\n"
        f"Recent chat:\n{history_text}\n\nReply as Codunot:"
    )


def build_roast_prompt(mem_manager, channel_id, target_name):
    if str(target_name).lower() in ["codunot", str(BOT_USER_ID)]:
        return "Refuse to roast yourself in a funny way."

    recent = mem_manager.get_recent_flat(channel_id, n=12)
    history_text = "\n".join(recent)

    if MODES["roast"]:
        persona = (
            "You are Codunot, a feral, brutal roast-master. "
            "Roast HARD. 1–3 brutal lines. No protected classes. No self-roasting."
        )
    else:
        persona = (
            "Friendly, playful one-line roast with emojis."
        )

    return f"{persona}\nTarget: {target_name}\nChat:\n{history_text}\nRoast:"


def humanize_and_safeify(text):
    if not isinstance(text, str):
        text = str(text)

    text = text.replace(" idk", "").replace(" *nvm", "")

    if random.random() < 0.1 and not MODES["serious"]:
        text = maybe_typo(text)

    return text


# ---------- on_ready ----------
@client.event
async def on_ready():
    print(f"{BOT_NAME} is ready!")
    asyncio.create_task(dead_channel_check())
    asyncio.create_task(initiate_conversation())
    asyncio.create_task(process_queue())
    asyncio.create_task(check_owner_mute())


# ---------- on_message ----------
@client.event
async def on_message(message: Message):
    global owner_mute_until
    if message.author == client.user:
        return

    now = datetime.utcnow()

    # respect quiet mode
    if owner_mute_until and now < owner_mute_until:
        if message.author.id != OWNER_ID:
            return  # bot does NOT respond while muted

    chan_id = str(message.channel.id) if not isinstance(message.channel, discord.DMChannel) else f"dm_{message.author.id}"
    memory.add_message(chan_id, message.author.display_name, message.content)

    # Special creator question
    if "who made you" in message.content.lower():
        await send_human_reply(
            message.channel,
            "@aarav_2022, Discord user ID **1220934047794987048**, made me."
        )
        return

    # OWNER COMMANDS
    if "!quiet" in message.content:
        if message.author.id != OWNER_ID:
            await send_human_reply(
                message.channel,
                f"Only my owner can shush me up, not you, bozo! My owner - @aarav_2022. Owner ID - {OWNER_ID}"
            )
            return
        quiet_match = re.search(r"!quiet (\d+)([smhd])", message.content.lower())
        if quiet_match:
            num, unit = int(quiet_match.group(1)), quiet_match.group(2)
            seconds = num * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
            owner_mute_until = datetime.utcnow() + timedelta(seconds=seconds)
            await send_human_reply(
                message.channel,
                f"I'll be quiet for {format_duration(num, unit)} as my owner muted me. Cyu soon!"
            )
            return

    if "!speak" in message.content.lower():
        if message.author.id != OWNER_ID:
            await send_human_reply(
                message.channel,
                f"Only my owner can make me speak, not you, bozo! My owner - @aarav_2022. Owner ID - {OWNER_ID}"
            )
            return
        owner_mute_until = None
        await send_human_reply(message.channel, "YOOO I'M BACK FROM MY TIMEOUT WASSUP GUYS!!!!")
        return

    # MODE SWITCHING
    if "!roastmode" in message.content:
        MODES.update({"roast": True, "serious": False, "funny": False})
        await send_human_reply(message.channel, "🔥 Roast mode ACTIVATED. Hide yo egos.")

    if "!seriousmode" in message.content:
        MODES.update({"serious": True, "roast": False, "funny": False})
        await send_human_reply(message.channel, "🤓 Serious mode activated.")

    if "!funnymode" in message.content:
        MODES.update({"funny": True, "roast": False, "serious": False})
        await send_human_reply(message.channel, "😎 Fun & light roast mode activated!")

    # ROAST MODE
    if MODES["roast"] or MODES["funny"]:
        roast_target = is_roast_trigger(message.content)
        if roast_target:
            memory.set_roast_target(chan_id, roast_target)
        target = memory.get_roast_target(chan_id)
        if target and str(target).lower() not in ["codunot", str(BOT_USER_ID)]:
            roast_prompt = build_roast_prompt(memory, chan_id, target)
            try:
                raw = await call_gemini(roast_prompt)
                roast_text = humanize_and_safeify(raw)
                await send_human_reply(message.channel, roast_text)
                memory.add_message(chan_id, BOT_NAME, roast_text)
            except Exception:
                pass
            return

    # GENERAL MESSAGE
    if not owner_mute_until or message.author.id == OWNER_ID:
        try:
            prompt = build_general_prompt(memory, chan_id)
            raw_resp = await call_gemini(prompt)
            reply = humanize_and_safeify(raw_resp)
            await send_human_reply(message.channel, reply)
            memory.add_message(chan_id, BOT_NAME, reply)
            memory.persist()
        except Exception:
            pass


# ---------- owner mute checker ----------
async def check_owner_mute():
    global owner_mute_until
    while True:
        if owner_mute_until and datetime.utcnow() >= owner_mute_until:
            owner_mute_until = None
            for guild in client.guilds:
                for channel in guild.text_channels:
                    await send_human_reply(channel, "YOOO I'M BACK FROM MY TIMEOUT WASSUP GUYS!!!!")
        await asyncio.sleep(1)


# ---------- graceful shutdown ----------
async def _cleanup():
    await memory.close()
    await asyncio.sleep(0.1)


# ---------- run ----------
def run():
    client.run(DISCORD_TOKEN)


if __name__ == "__main__":
    run()
