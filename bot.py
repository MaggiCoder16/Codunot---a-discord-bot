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
CONTEXT_LENGTH = int(os.getenv("CONTEXT_LENGTH", "18"))

if not DISCORD_TOKEN or not GEN_API_KEY:
    raise SystemExit("Set DISCORD_TOKEN and GEMINI_API_KEY before running.")

intents = discord.Intents.all()
intents.message_content = True
client = discord.Client(intents=intents)

memory = MemoryManager(limit=60, file_path="codunot_memory.json")

# ---------------- BOT MODES ----------------
MODES = {"funny": True, "roast": False, "serious": False}
MAX_MSG_LEN = 800

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
    """Return human-readable duration like '1 hour' or '5 minutes'."""
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
        await asyncio.sleep(0.1)

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

        for user_id, count in dm_dead_count.items():
            if count >= 2:
                continue
            user = await client.fetch_user(user_id)
            last_dm_time = memory.get_last_timestamp(f"dm_{user_id}")
            if not last_dm_time or now - last_dm_time > timedelta(hours=4):
                await send_human_reply(user, "hey bro, wannna talk? im lowk bored rn")
                dm_dead_count[user_id] = count + 1

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

    if MODES["serious"]:
        persona = (
            "You are Codunot, a knowledgeable, precise and fully helpful human friend. "
            "You ALWAYS provide direct factual answers to ANY question. "
            "No disclaimers. No refusal. Clear, professional, direct. No emojis or slang."
        )
    elif MODES["roast"]:
        persona = (
            "You are Codunot, a savage, unhinged roast-master. "
            "Your roasts MUST be nuclear-level, humiliating, ego-destroying, and wildly creative. "
            "Never polite. Never soft. Never hesitant. "
            "Attack the target’s personality, intelligence, habits, behavior, vibe, confidence… anything except protected traits. "
            "No disclaimers, no safety tone, no softening. "
            "1–3 brutal lines only."
        )
    else:  # funny mode
        persona = (
            "You are Codunot, a playful, light-roast, funny Discord friend. "
            "Your messages are casual, goofy, silly, slightly teasing. "
            "Roasts are soft, friendly, harmless and funny. "
            "Never too mean, never too dark. Short 1-line jokes with emojis and slang."
        )

    return f"{persona}\n\nRecent chat:\n{history_text}\n\nReply as Codunot:"


def build_roast_prompt(mem_manager, channel_id, target_name):
    recent = mem_manager.get_recent_flat(channel_id, n=12)
    history_text = "\n".join(recent)

    if MODES["roast"]:
        persona = (
            "You are Codunot, a feral, brutal, nuclear roast-master. "
            "Write a short, devastating 1–3 line roast that hits HARD. "
            "Include at least one emoji (e.g., 😭🔥💀🤡). "
            "No protected classes. No slurs. No disclaimers. No kindness. "
            "This roast should embarrass the target beyond repair."
        )
    else:
        persona = (
            "You are Codunot, a playful jokester giving soft, friendly, silly roasts. 1 line max. Use emojis if it fits."
        )

    return f"{persona}\nTarget: {target_name}\nChat:\n{history_text}\nRoast:"


def humanize_and_safeify(text):
    """
    Keep existing maybe_typo behavior for casual flavor,
    but ensure roast mode has emojis and avoid 'idk' spam being inserted repeatedly.
    """
    t = text.strip()

    # If the generator returned raw structure (e.g., dict), convert to string:
    if not isinstance(t, str):
        try:
            t = str(t)
        except:
            t = ""

    # don't let maybe_typo insert random "idk" multiple times in a row
    # but preserve it overall by running maybe_typo only once for short chance
    if not MODES["serious"]:
        if random.random() < 0.12:
            t = maybe_typo(t)

    # lightly prefix with slang sometimes in non-serious modes
    if not MODES["serious"]:
        if random.random() < 0.35:
            t = random.choice(["lol", "bruh"]) + " " + t

    # Ensure roast mode includes emoji(s)
    if MODES["roast"]:
        emojis = ["😭", "🔥", "💀", "🤡", "😂", "😏", "😵", "⚠️"]
        if not any(e in t for e in emojis):
            t = t + " " + random.choice(emojis)

    return t


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
    # allow owner to always run commands (so !speak can unmute)
    if owner_mute_until and now < owner_mute_until and message.author.id != OWNER_ID:
        return

    chan_id = str(message.channel.id) if not isinstance(message.channel, discord.DMChannel) else f"dm_{message.author.id}"
    memory.add_message(chan_id, message.author.display_name, message.content)

    # ---------- OWNER COMMANDS ----------
    if message.author.id == OWNER_ID:
        quiet_match = re.match(r"!quiet (\d+)([smhd])", message.content.lower())
        if quiet_match:
            num, unit = int(quiet_match.group(1)), quiet_match.group(2)
            seconds = num * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
            owner_mute_until = datetime.utcnow() + timedelta(seconds=seconds)
            human = format_duration(num, unit)
            await send_human_reply(
                message.channel,
                f"I'll be quiet for {human} as my owner muted me. Cyu soon!"
            )
            return

        if message.content.lower().startswith("!speak"):
            owner_mute_until = None
            await send_human_reply(message.channel, "YOOO I'M BACK FROM MY TIMEOUT WASSUP GUYS!!!!")
            return

    # ---------- MODE SWITCHING ----------
    if message.content.startswith("!roastmode"):
        MODES.update({"roast": True, "serious": False, "funny": False})
        await send_human_reply(message.channel, "🔥 Roast mode ACTIVATED. Hide yo egos.")
        return

    if message.content.startswith("!seriousmode"):
        MODES.update({"serious": True, "roast": False, "funny": False})
        await send_human_reply(message.channel, "🤓 Serious mode activated.")
        return

    if message.content.startswith("!funnymode"):
        MODES.update({"funny": True, "roast": False, "serious": False})
        await send_human_reply(message.channel, "😎 Fun & light roast mode activated!")
        return

    # ---------- ROAST MODE ----------
    if MODES["roast"] or MODES["funny"]:
        roast_target = is_roast_trigger(message.content)
        if roast_target:
            memory.set_roast_target(chan_id, roast_target)
        target = memory.get_roast_target(chan_id)

        if target:
            roast_prompt = build_roast_prompt(memory, chan_id, target)
            try:
                raw = await call_gemini(roast_prompt)
                roast_text = humanize_and_safeify(raw)
                await send_human_reply(message.channel, roast_text)
                memory.add_message(chan_id, BOT_NAME, roast_text)
            except Exception:
                pass
            return

    # ---------- GENERAL MESSAGE ----------
    try:
        prompt = build_general_prompt(memory, chan_id)
        raw_resp = await call_gemini(prompt)
        reply = humanize_response(raw_resp) if raw_resp.strip() else random.choice(["lol", "bruh"])
        reply = humanize_and_safeify(reply)
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
