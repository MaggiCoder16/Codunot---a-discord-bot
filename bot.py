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
OWNER_ID = 1220934047794987048
CONTEXT_LENGTH = int(os.getenv("CONTEXT_LENGTH", "18"))

if not DISCORD_TOKEN or not GEN_API_KEY:
    raise SystemExit("Set DISCORD_TOKEN and GEMINI_API_KEY before running.")

intents = discord.Intents.all()
intents.message_content = True
client = discord.Client(intents=intents)

memory = MemoryManager(limit=60, file_path="codunot_memory.json")

# ---------------- BOT MODES ----------------
MODES_DEFAULT = {"funny": True, "roast": False, "serious": False}
MAX_MSG_LEN = 3000  # for serious mode

# ---------------- PER-CHANNEL TIMEOUTS ----------------
# key = channel_id or "dm_<user_id>", value = datetime when unmuted
channel_mute_until = {}

# ---------------- PER-CHANNEL MODES ----------------
# key = channel_id or "dm_<user_id>", value = mode dict
channel_modes = {}

# ---------- allowed channels ----------
ALLOWED_SERVER_ID = 1435926772972519446
GENERAL_CHANNEL_ID = 1436339326509383820
TALK_WITH_BOTS_ID = 1439269712373485589

message_queue = asyncio.Queue()


# ---------- helpers ----------
def format_duration(num: int, unit: str) -> str:
    unit_map = {"s": "second", "m": "minute", "h": "hour", "d": "day"}
    name = unit_map.get(unit, "minute")
    return f"{num} {name}s" if num > 1 else f"1 {name}"


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
        await asyncio.sleep(0.1)  # send faster (instant-ish)


async def send_human_reply(channel, reply_text, limit=None):
    if limit:
        reply_text = reply_text[:limit].rstrip()
    if len(reply_text) > MAX_MSG_LEN:
        await send_long_message(channel, reply_text)
    else:
        await message_queue.put((channel, reply_text))


def humanize_and_safeify(text, short=False):
    if not isinstance(text, str):
        text = str(text)
    text = text.replace(" idk", "").replace(" *nvm", "")
    if random.random() < 0.1:
        text = maybe_typo(text)
    if short:
        # limit to 100 chars, ensure sentence completes
        text = text.strip()[:100]
        if not text.endswith(('.', '!', '?')):
            text += '.'
    return text


def get_channel_mode(chan_id):
    return channel_modes.get(chan_id, MODES_DEFAULT.copy())


# ---------- PROMPTS ----------
def build_general_prompt(mem_manager, channel_id):
    recent = mem_manager.get_recent_flat(channel_id, n=CONTEXT_LENGTH)
    history_text = "\n".join(recent)
    mode = get_channel_mode(channel_id)
    persona_self_protect = (
        "Never roast or attack yourself (Codunot). "
        "If asked to roast Codunot, gently refuse or redirect."
    )
    if mode["serious"]:
        persona = (
            "You are Codunot, a precise and knowledgeable helper. "
            "You answer with direct factual information. No emojis, no slang."
        )
    elif mode["roast"] or mode["funny"]:
        persona = (
            "You are Codunot, a witty, sharp friend. "
            "Reply in 1–2 lines, max 100 characters. Complete sentences. No romance except to owner. "
            "Use slang and emojis for fun/roast mode. Hard roast if roast mode."
        )
    else:
        persona = (
            "You are Codunot, a playful, funny Discord friend. "
            "Light roasts, friendly jokes, emojis allowed."
        )
    return (
        f"{persona}\n"
        f"{persona_self_protect}\n"
        f"My user ID is {BOT_USER_ID}.\n\n"
        f"Recent chat:\n{history_text}\n\nReply as Codunot:"
    )


def build_roast_prompt(mem_manager, channel_id, target_name):
    if str(target_name).lower() in ["codunot", str(BOT_USER_ID)]:
        return "Refuse to roast yourself in a funny way."
    recent = mem_manager.get_recent_flat(channel_id, n=12)
    history_text = "\n".join(recent)
    mode = get_channel_mode(channel_id)
    if mode["roast"]:
        persona = (
            "You are Codunot, a feral roast-master. Hard roast, 1–2 lines, max 100 chars. "
            "Avoid protected classes, never roast yourself."
        )
    else:
        persona = "Friendly playful one-line roast with emojis, max 100 chars."
    return f"{persona}\nTarget: {target_name}\nRecent chat:\n{history_text}\nRoast:"


# ---------- on_ready ----------
@client.event
async def on_ready():
    print(f"{BOT_NAME} is ready!")
    asyncio.create_task(process_queue())


# ---------- on_message ----------
@client.event
async def on_message(message: Message):
    if message.author == client.user:
        return

    is_dm = isinstance(message.channel, discord.DMChannel)
    chan_id = str(message.channel.id) if not is_dm else f"dm_{message.author.id}"

    now = datetime.utcnow()

    # ---------- OWNER COMMANDS ----------
    if message.author.id == OWNER_ID:
        if message.content.startswith("!quiet"):
            match = re.search(r"!quiet (\d+)([smhd])", message.content.lower())
            if match:
                num = int(match.group(1))
                unit = match.group(2)
                seconds = num * {"s":1, "m":60, "h":3600, "d":86400}[unit]
                channel_mute_until[chan_id] = datetime.utcnow() + timedelta(seconds=seconds)
                await send_human_reply(
                    message.channel,
                    f"I'll stop yapping for {format_duration(num, unit)} as my owner shushed me up. Cyu guys!"
                )
            return
        if message.content.startswith("!speak"):
            channel_mute_until[chan_id] = None
            await send_human_reply(message.channel, "YOOO I'M BACK FROM MY TIMEOUT WASSUP GUYS!!!!")
            return

    # ---------- CHECK TIMEOUT ----------
    mute_until = channel_mute_until.get(chan_id)
    if mute_until and now < mute_until:
        return

    # ---------- SERVER LOGIC ----------
    allowed_channel = False
    if is_dm:
        allowed_channel = True
    elif message.channel.id in [TALK_WITH_BOTS_ID, GENERAL_CHANNEL_ID]:
        allowed_channel = True

    if not allowed_channel:
        return

    memory.add_message(chan_id, message.author.display_name, message.content)

    # ---------- MODE SWITCHING ----------
    content_lower = message.content.lower()
    if "!roastmode" in content_lower:
        channel_modes[chan_id] = {"roast": True, "serious": False, "funny": False}
        await send_human_reply(message.channel, "🔥 Roast mode ACTIVATED. Hide yo egos.")
        return
    if "!funmode" in content_lower:
        channel_modes[chan_id] = {"roast": False, "funny": True, "serious": False}
        await send_human_reply(message.channel, "😎 Fun & light roast mode activated!")
        return
    if "!seriousmode" in content_lower:
        channel_modes[chan_id] = {"roast": False, "funny": False, "serious": True}
        await send_human_reply(message.channel, "🤓 Serious mode activated!")
        return

    # ---------- ROAST/FUN ----------
    mode = get_channel_mode(chan_id)
    short_mode = mode["roast"] or mode["funny"]
    roast_target = is_roast_trigger(message.content)
    if roast_target:
        memory.set_roast_target(chan_id, roast_target)
    target = memory.get_roast_target(chan_id)
    if target:
        roast_prompt = build_roast_prompt(memory, chan_id, target)
        try:
            raw = await call_gemini(roast_prompt)
            reply = humanize_and_safeify(raw, short=short_mode)
            await send_human_reply(message.channel, reply, limit=100 if short_mode else None)
            memory.add_message(chan_id, BOT_NAME, reply)
        except:
            pass
        return

    # ---------- GENERAL CONVERSATION ----------
    try:
        prompt = build_general_prompt(memory, chan_id)
        raw_resp = await call_gemini(prompt)
        reply = humanize_and_safeify(raw_resp, short=short_mode)
        await send_human_reply(message.channel, reply, limit=100 if short_mode else None)
        memory.add_message(chan_id, BOT_NAME, reply)
        memory.persist()
    except:
        pass


# ---------- graceful shutdown ----------
async def _cleanup():
    await memory.close()
    await asyncio.sleep(0.1)


# ---------- run ----------
def run():
    client.run(DISCORD_TOKEN)


if __name__ == "__main__":
    run()
