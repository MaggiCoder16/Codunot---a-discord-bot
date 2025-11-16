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
CONTEXT_LENGTH = int(os.getenv("CONTEXT_LENGTH", "18"))

if not DISCORD_TOKEN or not GEN_API_KEY:
    raise SystemExit("Set DISCORD_TOKEN and GEMINI_API_KEY before running.")

intents = discord.Intents.all()
intents.message_content = True
client = discord.Client(intents=intents)

memory = MemoryManager(limit=60, file_path="codunot_memory.json")

# ---------------- BOT MODES ----------------
MODES = {"funny": True, "roast": False, "serious": False}
MAX_MSG_LEN_SERIOUS = 3000
MAX_MSG_LEN_FUNNY = 200

# ---------------- OWNER QUIET/SPEAK ----------------
OWNER_ID = 1220934047794987048
owner_mute_until = None

# ---------- allowed channels ----------
ALLOWED_SERVER = "RoyalRacer Fans"
ALLOWED_OPEN_GENERAL = "general"  # under OPEN TO ALL
ALLOWED_OPEN_CATEGORY = "OPEN TO ALL"
ALWAYS_TALK_CHANNEL = "talk-with-bots"

# ---------- message queue for throttling ----------
message_queue = asyncio.Queue()


# ---------------- HELPER FUNCTIONS ----------------
def format_duration(num: int, unit: str) -> str:
    unit_map = {"s": "second", "m": "minute", "h": "hour", "d": "day"}
    name = unit_map.get(unit, "minute")
    return f"{num} {name}s" if num > 1 else f"1 {name}"


async def send_long_message(channel, text, max_len=MAX_MSG_LEN_SERIOUS):
    while len(text) > 0:
        chunk = text[:max_len]
        text = text[max_len:]
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
    max_len = MAX_MSG_LEN_SERIOUS if MODES["serious"] else MAX_MSG_LEN_FUNNY
    if len(text) > max_len:
        await send_long_message(channel, text, max_len=max_len)
    else:
        await message_queue.put((channel, text))


def humanize_and_safeify(text):
    if not isinstance(text, str):
        text = str(text)
    text = text.replace(" idk", "").replace(" *nvm", "")
    if random.random() < 0.1 and not MODES["serious"]:
        text = maybe_typo(text)
    # truncate for non-serious modes
    if not MODES["serious"]:
        text = text[:MAX_MSG_LEN_FUNNY]
    return text


# ---------------- PROMPTS ----------------
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
            "You answer with direct factual information. No emojis, no slang. "
            "If user asks for code, include it in triple backticks ```."
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
        persona = "Friendly, playful one-line roast with emojis."
    return f"{persona}\nTarget: {target_name}\nChat:\n{history_text}\nRoast:"


# ---------------- EVENTS ----------------
@client.event
async def on_ready():
    print(f"{BOT_NAME} is ready!")
    asyncio.create_task(process_queue())


@client.event
async def on_message(message: Message):
    global owner_mute_until
    if message.author == client.user:
        return

    # ---------------- OWNER COMMANDS ----------------
    if message.author.id == OWNER_ID and message.content.lower().startswith("!speak"):
        owner_mute_until = None
        await send_human_reply(message.channel, "YOOO I'M BACK FROM MY TIMEOUT WASSUP GUYS!!!!")
        return

    now = datetime.utcnow()
    if owner_mute_until and now < owner_mute_until:
        return

    # ---------------- SERVER LOGIC ----------------
    is_dm = isinstance(message.channel, discord.DMChannel)
    allowed_channel = False

    if is_dm:
        allowed_channel = True
    else:
        # Always talk in #talk-with-bots
        if message.channel.id == 1439269712373485589:
            allowed_channel = True
        # Only respond in specific server/channel
        elif (
            message.guild
            and message.guild.id == 1435926772972519446
            and message.channel.id == 1436339326509383820
        ):
            # Check if bot is mentioned or replied to
            mentioned = client.user in message.mentions or f"<@{BOT_USER_ID}>" in message.content
            replied = False
            if message.reference:
                try:
                    ref = message.reference
                    if isinstance(ref.resolved, discord.Message):
                        replied = ref.resolved.author.id == BOT_USER_ID
                    else:
                        ref_msg = await message.channel.fetch_message(ref.message_id)
                        replied = ref_msg.author.id == BOT_USER_ID if ref_msg else False
                except:
                    replied = False
            if mentioned or replied:
                allowed_channel = True

    if not allowed_channel:
        return

    chan_id = str(message.channel.id) if not is_dm else f"dm_{message.author.id}"
    memory.add_message(chan_id, message.author.display_name, message.content)

    # Special creator question
    if "who made you" in message.content.lower():
        await send_human_reply(
            message.channel,
            "@aarav_2022, Discord user ID **1220934047794987048**, made me."
        )
        return

    # MODE SWITCHING (!roastmode / !seriousmode / !funmode / !funnymode)
    msg_lower = message.content.lower()
    if msg_lower.startswith("!roastmode"):
        MODES.update({"roast": True, "serious": False, "funny": False})
        await send_human_reply(message.channel, "🔥 Roast mode ACTIVATED. Hide yo egos.")
        return
    elif msg_lower.startswith("!seriousmode"):
        MODES.update({"serious": True, "roast": False, "funny": False})
        await send_human_reply(message.channel, "🤓 Serious mode activated.")
        return
    elif msg_lower.startswith("!funmode") or msg_lower.startswith("!funnymode"):
        MODES.update({"funny": True, "roast": False, "serious": False})
        await send_human_reply(message.channel, "😎 Fun & light roast mode activated!")
        return

    # ROAST / FUNNY MODE
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
                roast_text = roast_text[:MAX_MSG_LEN_FUNNY]
                await send_human_reply(message.channel, roast_text)
                memory.add_message(chan_id, BOT_NAME, roast_text)
            except Exception:
                pass
            return

    # GENERAL MESSAGE
    try:
        prompt = build_general_prompt(memory, chan_id)
        raw_resp = await call_gemini(prompt)
        reply = humanize_and_safeify(raw_resp)
        await send_human_reply(message.channel, reply)
        memory.add_message(chan_id, BOT_NAME, reply)
        memory.persist()
    except Exception:
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
