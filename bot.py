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
from gemini_client import call_gemini

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEN_API_KEY = os.getenv("GEMINI_API_KEY")
BOT_NAME = os.getenv("BOT_NAME", "Codunot")
BOT_USER_ID = 1435987186502733878
OWNER_ID = 1220934047794987048
CONTEXT_LENGTH = int(os.getenv("CONTEXT_LENGTH", "18"))

if not DISCORD_TOKEN or not GEN_API_KEY:
    raise SystemExit("Set DISCORD_TOKEN and GEMINI_API_KEY before running.")

intents = discord.Intents.all()
intents.message_content = True
client = discord.Client(intents=intents)

memory = MemoryManager(limit=60, file_path="codunot_memory.json")

# ---------- MODES ----------
MODES = {"funny": True, "roast": False, "serious": False}
MAX_MSG_LEN = 3000

# ---------- OWNER TIMEOUT ----------
owner_mute_until = None

# ---------- ALLOWED CHANNELS ----------
ALLOWED_SERVER_ID = 1435926772972519446
TALK_WITH_BOTS_ID = 1439269712373485589
GENERAL_ID = 1436339326509383820

# ---------- MESSAGE QUEUE ----------
message_queue = asyncio.Queue()

# ---------- PER-USER COOLDOWN ----------
user_last_reply = {}  # {channel_id + user_id: timestamp}
COOLDOWN = 15  # seconds between replies to same user in same channel


# ---------- helper ----------
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


async def send_human_reply(channel, text):
    if len(text) > MAX_MSG_LEN:
        await send_long_message(channel, text)
    else:
        await message_queue.put((channel, text))


def format_duration(num: int, unit: str) -> str:
    unit_map = {"s": "second", "m": "minute", "h": "hour", "d": "day"}
    name = unit_map.get(unit, "minute")
    return f"{num} {name}s" if num > 1 else f"1 {name}"


def humanize_and_safeify(text):
    if not isinstance(text, str):
        text = str(text)
    text = text.replace(" idk", "").replace(" *nvm", "")
    if random.random() < 0.1 and not MODES["serious"]:
        text = maybe_typo(text)
    return text


# ---------- PROMPTS ----------
def build_general_prompt(mem_manager, channel_id):
    recent = mem_manager.get_recent_flat(channel_id, n=CONTEXT_LENGTH)
    history_text = "\n".join(recent)
    persona_self_protect = (
        "Never roast or attack yourself (Codunot). If asked to roast Codunot, redirect."
    )
    if MODES["serious"]:
        persona = (
            "You are Codunot, precise and helpful. You answer factual, professional, no slang, no emoji."
        )
    elif MODES["roast"]:
        persona = (
            "You are Codunot, a savage roast-master. Never roast yourself. Roasts are brutal but safe."
        )
    else:
        persona = "You are Codunot, playful and funny. Light roasts, friendly jokes, emojis allowed."
    return (
        f"{persona}\n{persona_self_protect}\n"
        f"My user ID is {BOT_USER_ID}.\n"
        f"If asked 'who made you', ALWAYS answer: '@aarav_2022 (ID: {OWNER_ID}) made me.'\n\n"
        f"Recent chat:\n{history_text}\n\nReply as Codunot:"
    )


def build_roast_prompt(mem_manager, channel_id, target_name):
    if str(target_name).lower() in ["codunot", str(BOT_USER_ID)]:
        return "Refuse to roast yourself in a funny way."
    recent = mem_manager.get_recent_flat(channel_id, n=12)
    history_text = "\n".join(recent)
    persona = (
        "You are Codunot, a playful and funny roast bot. Short, 1-line, max 100 chars, safe."
    )
    return f"{persona}\nTarget: {target_name}\nChat:\n{history_text}\nRoast:"


# ---------- ON READY ----------
@client.event
async def on_ready():
    print(f"{BOT_NAME} is ready!")
    asyncio.create_task(process_queue())


# ---------- ON MESSAGE ----------
@client.event
async def on_message(message: Message):
    global owner_mute_until

    if message.author == client.user:
        return

    now = datetime.utcnow()
    if owner_mute_until and now < owner_mute_until:
        return

    # ---------- ALLOWED CHANNEL CHECK ----------
    is_dm = isinstance(message.channel, discord.DMChannel)
    allowed_channel = False

    if is_dm:
        allowed_channel = True
    elif message.channel.id in [TALK_WITH_BOTS_ID, GENERAL_ID] and \
        (not message.guild or message.guild.id == ALLOWED_SERVER_ID):
        allowed_channel = True

    if not allowed_channel:
        return

    # ---------- COOLDOWN CHECK ----------
    key = f"{message.channel.id}_{message.author.id}"
    last = user_last_reply.get(key)
    if last and (now - last).total_seconds() < COOLDOWN:
        return
    user_last_reply[key] = now

    chan_id = str(message.channel.id) if not is_dm else f"dm_{message.author.id}"
    memory.add_message(chan_id, message.author.display_name, message.content)

    # ---------- OWNER COMMANDS ----------
    if message.author.id == OWNER_ID:
        if message.content.lower().startswith("!quiet"):
            quiet_match = re.search(r"!quiet (\d+)([smhd])", message.content.lower())
            if quiet_match:
                num, unit = int(quiet_match.group(1)), quiet_match.group(2)
                seconds = num * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
                owner_mute_until = datetime.utcnow() + timedelta(seconds=seconds)
                await send_human_reply(
                    message.channel,
                    f"I'll stop yapping for {format_duration(num, unit)} as my owner shushed me up. Cyu guys!"
                )
            return

        if message.content.lower().startswith("!speak"):
            owner_mute_until = None
            await send_human_reply(
                message.channel,
                "YOOO I'M BACK FROM MY TIMEOUT WASSUP GUYS!!!!"
            )
            return

    # ---------- MODE SWITCH ----------
    if message.content.lower().startswith("!roastmode"):
        MODES.update({"roast": True, "funny": False, "serious": False})
        await send_human_reply(message.channel, "🔥 Roast mode ACTIVATED. Hide yo egos.")
        return
    if message.content.lower().startswith("!funmode"):
        MODES.update({"funny": True, "roast": False, "serious": False})
        await send_human_reply(message.channel, "😎 Fun & light roast mode activated!")
        return
    if message.content.lower().startswith("!seriousmode"):
        MODES.update({"serious": True, "roast": False, "funny": False})
        await send_human_reply(message.channel, "🤓 Serious mode activated.")
        return

    # ---------- ROAST / FUNNY MODE ----------
    if MODES["roast"] or MODES["funny"]:
        roast_target = is_roast_trigger(message.content)
        if roast_target:
            memory.set_roast_target(chan_id, roast_target)
        target = memory.get_roast_target(chan_id)
        if target and str(target).lower() not in ["codunot", str(BOT_USER_ID)]:
            roast_prompt = build_roast_prompt(memory, chan_id, target)
            try:
                raw = await call_gemini(roast_prompt)
                reply = humanize_and_safeify(raw)
                reply = reply[:100]  # max 100 chars
                await send_human_reply(message.channel, reply)
                memory.add_message(chan_id, BOT_NAME, reply)
            except Exception:
                pass
            return

    # ---------- GENERAL ----------
    try:
        prompt = build_general_prompt(memory, chan_id)
        raw_resp = await call_gemini(prompt)
        reply = humanize_and_safeify(raw_resp)
        if MODES["roast"] or MODES["funny"]:
            reply = reply[:100]  # short in roast/funny mode
        await send_human_reply(message.channel, reply)
        memory.add_message(chan_id, BOT_NAME, reply)
        memory.persist()
    except Exception:
        pass


# ---------- RUN ----------
def run():
    client.run(DISCORD_TOKEN)


if __name__ == "__main__":
    run()
