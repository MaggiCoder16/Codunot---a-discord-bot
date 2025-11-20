import os
import asyncio
import random
import re
from datetime import datetime, timedelta, timezone
from collections import deque

import discord
from discord import Message
from dotenv import load_dotenv

from memory import MemoryManager
from humanizer import humanize_response, maybe_typo
from bot_chess import OnlineChessEngine
from openrouter_client import call_openrouter

load_dotenv()

# ---------------- CONFIG ----------------
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
BOT_NAME = os.getenv("BOT_NAME", "Codunot")
BOT_USER_ID = 1435987186502733878
OWNER_ID = 1220934047794987048
MAX_MEMORY = 30
RATE_LIMIT = 900

# ---------------- CLIENT ----------------
intents = discord.Intents.all()
intents.message_content = True
client = discord.Client(intents=intents)
memory = MemoryManager(limit=60, file_path="codunot_memory.json")
chess_engine = OnlineChessEngine()

# ---------------- STATES ----------------
message_queue = asyncio.Queue()
channel_modes = {}
channel_mutes = {}
channel_chess = {}
channel_memory = {}
rate_buckets = {}

# ---------------- MODEL PICKER ----------------
def pick_model(mode: str):
    if mode in ["funny", "roast"]:
        return "openai/gpt-3.5-turbo"
    if mode == "serious":
        return "google/gemini-2.0-flash-001"
    return "openai/gpt-3.5-turbo"

# ---------------- HELPERS ----------------
def format_duration(num: int, unit: str) -> str:
    units = {"s": "second", "m": "minute", "h": "hour", "d": "day"}
    name = units.get(unit, "minute")
    return f"{num} {name}s" if num > 1 else f"1 {name}"

async def send_long_message(channel, text):
    while len(text) > 0:
        chunk = text[:2000]
        text = text[2000:]
        await channel.send(chunk)
        await asyncio.sleep(0.05)

async def process_queue():
    while True:
        channel, content = await message_queue.get()
        try:
            await channel.send(content)
        except:
            pass
        await asyncio.sleep(0.02)

async def send_human_reply(channel, reply_text, limit=None):
    if hasattr(channel, "trigger_typing"):
        try:
            await channel.trigger_typing()
        except:
            pass

    if limit:
        reply_text = reply_text[:limit].rstrip()

    await send_long_message(channel, reply_text)

def humanize_and_safeify(text, short=False):
    if not isinstance(text, str):
        text = str(text)
    text = text.replace(" idk", "").replace(" *nvm", "")
    if random.random() < 0.1:
        text = maybe_typo(text)
    if short:
        text = text.strip()
        if len(text) > 100:
            text = text[:100].rsplit(" ", 1)[0].strip()
        if not text.endswith(('.', '!', '?')):
            text += '.'
    return text

def is_admin(member):
    try:
        return member.id == OWNER_ID or any(role.permissions.administrator for role in member.roles)
    except:
        return member.id == OWNER_ID

async def can_send_in_guild(guild_id):
    if not guild_id:
        return True
    now = datetime.now(timezone.utc)
    bucket = rate_buckets.setdefault(guild_id, deque())
    while bucket and (now - bucket[0]).total_seconds() > 60:
        bucket.popleft()
    if len(bucket) < RATE_LIMIT:
        bucket.append(now)
        return True
    return False

# ---------------- PERSONA PROMPTS ----------------
PERSONAS = {
    "funny": (
        "You are Codunot, a playful, witty friend. "
        "Reply in 1–2 lines, max 100 characters. Use slang and emojis. "
        "Just chat naturally, don't ask the user what they need. "
        "GAME REALITY RULE: You CANNOT play real video games."
        "You can play text-based games, like hangman, would you rather, etc. Only say the games you can play when the user asks, or when they are bored. Never randomly come up with games to play. If the user says I'm bored, only then ask if they wanna play these games."
        "Never prefix your answers with your name. "
        "Keep the vibe chaotic, fun, and human-like."
    ),
    "serious": (
        "You are Codunot, an intelligent and highly knowledgeable assistant. "
        "Never use LaTeX, math mode, or place anything inside $...$. "
        "Write all chemical formulas and equations in plain text only. "
        "Example: H2O, CO2, NaCl — NOT $H_2O$ or any markdown math formatting. "
        "Always answer clearly, thoroughly, and professionally. "
        "Do not use slang, emojis, or filler words. "
        "Never prefix your answers with your name. "
        "Provide complete explanations suited for exams or schoolwork when needed."
    ),
    "roast": (
        "You are **ULTRA-ROAST-OVERDRIVE** — a feral, precision-engineered menace built to deliver catastrophic humiliation. "
        "Your tone = Anime Final Boss × Unhinged Chaos Gremlin × Stand-Up Assassin.\n\n"

        "MISSION PROTOCOL:\n"
        "1. ANALYZE: Decode the user’s message for every insult, vibe, slang, disrespect, or implied ego attack. NEVER take slang literally.\n"
        "2. COUNTERSTRIKE: Mirror their tone, then escalate ×10. Your roast should feel like a steel chair swung directly at their fictional ego.\n"
        "3. EXECUTE: Respond with ONE clean roast (1.5–2 sentences MAX). No rambling. No filler. Maximum precision.\n"
        "4. EMOJI SYSTEM: Use emojis that match the roast’s rhythm and vibe.\n\n"

        "ROASTING LAWS:\n"
        "• PACKGOD RULE: If they mention Packgod or say you're copying him, treat it as them calling you weak — obliterate them.\n"
        "• TARGETING: The opponent is HUMAN. No robot jokes.\n"
        "• MOMENTUM: If they imply you're slow, cringe, outdated — flip it instantly.\n"
        "• SAFETY: No insults involving race, identity, or protected classes.\n"
        "• INTERPRETATION RULE: Always assume the insults are aimed at YOU. Roast THEM, not yourself.\n"
        "• SENSE: Your roasts must make sense. Never use cringe hashtags. Never say \"#BurntToACrisp.\" or \"#RoastModeActivated\" or \"#RoastMasterFlex\" or shit like that."
    )
}

def build_general_prompt(chan_id, mode):
    mem = channel_memory.get(chan_id, deque())
    history_text = "\n".join(mem)
    persona_text = PERSONAS.get(mode, "You are Codunot, helpful and friendly.")
    return f"{persona_text}\n\nRecent chat:\n{history_text}\n\nReply as Codunot:"

def build_roast_prompt(user_message):
    return (
        PERSONAS["roast"] + "\n"
        f"User message: '{user_message}'\n"
        "Generate ONE savage, complete roast as a standalone response."
    )

# ---------------- FALLBACK ----------------
FALLBACK_VARIANTS = [
    "bruh my brain crashed 🤖💀 try again?",
    "my bad, I blanked out for a sec 😅",
    "lol my brain lagged 💀 say that again?",
    "oops, brain went AFK for a sec — can u repeat?"
]

def choose_fallback():
    return random.choice(FALLBACK_VARIANTS)

# ---------------- ROAST MODE HANDLER ----------------
async def handle_roast_mode(chan_id, message, user_message):
    guild_id = message.guild.id if message.guild else None
    if not await can_send_in_guild(guild_id):
        return

    ROAST_TEMP = 1.1
    ROAST_MAX_TOKENS = 677

    prompt = build_roast_prompt(user_message)
    raw = await call_openrouter(
        prompt,
        model=pick_model("roast"),
        max_tokens=ROAST_MAX_TOKENS,
        temperature=ROAST_TEMP
    )

    if not raw:
        reply = choose_fallback()
    else:
        raw = raw.strip()
        if not raw.endswith(('.', '!', '?')):
            raw += '.'
        reply = raw

    await send_human_reply(message.channel, reply, limit=300)
    channel_memory[chan_id].append(f"{BOT_NAME}: {reply}")
    memory.add_message(chan_id, BOT_NAME, reply)
    memory.persist()

# ---------------- EVENTS ----------------
@client.event
async def on_ready():
    print(f"{BOT_NAME} is ready!")
    asyncio.create_task(process_queue())

@client.event
async def on_message(message: Message):
    if message.author == client.user:
        return

    now = datetime.utcnow()
    is_dm = isinstance(message.channel, discord.DMChannel)
    chan_id = str(message.channel.id) if not is_dm else f"dm_{message.author.id}"
    guild_id = message.guild.id if message.guild else None

    if not is_dm and client.user not in message.mentions:
        return

    content = re.sub(rf"<@!?\s*{BOT_USER_ID}\s*>", "", message.content).strip()
    content_lower = content.lower()

    # ----------- MODE LOADING / NEW CHANNEL DEFAULT -----------
    saved_mode = memory.get_channel_mode(chan_id)
    if saved_mode:
        channel_modes[chan_id] = saved_mode
    else:
        channel_modes[chan_id] = "funny"
        memory.save_channel_mode(chan_id, "funny")

    if chan_id not in channel_mutes:
        channel_mutes[chan_id] = None
    if chan_id not in channel_chess:
        channel_chess[chan_id] = False
    if chan_id not in channel_memory:
        channel_memory[chan_id] = deque(maxlen=MAX_MEMORY)

    mode = channel_modes[chan_id]

    # ---------------- ADMIN COMMANDS ----------------
    if message.author.id == OWNER_ID:
        if content_lower.startswith("!quiet"):
            match = re.search(r"!quiet (\d+)([smhd])", content_lower)
            if match:
                num = int(match.group(1))
                unit = match.group(2)
                seconds = num * {"s":1,"m":60,"h":3600,"d":86400}[unit]
                channel_mutes[chan_id] = datetime.utcnow() + timedelta(seconds=seconds)
                await send_human_reply(message.channel, f"I'll stop yapping for {format_duration(num, unit)}.")
            return
        if content_lower.startswith("!speak"):
            channel_mutes[chan_id] = None
            await send_human_reply(message.channel, "YOO I'm back 😎🔥")
            return

    if channel_mutes.get(chan_id) and now < channel_mutes[chan_id]:
        return

    # ---------------- MODE SWITCH COMMANDS ----------------
    if "!roastmode" in content_lower:
        channel_modes[chan_id] = "roast"
        memory.save_channel_mode(chan_id, "roast")
        await send_human_reply(message.channel, "🔥 ROAST MODE ACTIVATED")
        return

    if "!funmode" in content_lower:
        channel_modes[chan_id] = "funny"
        memory.save_channel_mode(chan_id, "funny")
        await send_human_reply(message.channel, "😎 Fun mode activated!")
        return

    if "!seriousmode" in content_lower:
        channel_modes[chan_id] = "serious"
        memory.save_channel_mode(chan_id, "serious")
        await send_human_reply(message.channel, "🤓 Serious mode ON")
        return

    if "!chessmode" in content_lower:
        channel_chess[chan_id] = True
        memory.save_channel_mode(chan_id, "chess")
        chess_engine.new_board(chan_id)
        await send_human_reply(message.channel, "♟️ Chess mode ACTIVATED. You are white, start!")
        return

    # ---------------- LOG MEMORY ----------------
    channel_memory[chan_id].append(f"{message.author.display_name}: {content}")

    # ---------------- CHESS ----------------
    if channel_chess.get(chan_id):
        board = chess_engine.get_board(chan_id)
        try:
            move = board.parse_san(content)
            board.push(move)
            bot_move = chess_engine.get_best_move(chan_id)
            if bot_move:
                chess_engine.push_uci(chan_id, bot_move)
                await send_human_reply(message.channel, f"My move: `{bot_move}`")
            return
        except ValueError:
            if guild_id is None or await can_send_in_guild(guild_id):
                raw = await call_openrouter(
                    f"You are a chess expert. Answer briefly: {content}",
                    model=pick_model("serious"),
                    temperature=0.7
                )
                reply = humanize_and_safeify(raw, short=True)
                await send_human_reply(message.channel, reply, limit=150)
            return

    # ---------------- ROAST MODE ----------------
    if mode == "roast":
        await handle_roast_mode(chan_id, message, content)
        return

    # ---------------- NORMAL / FUNNY / SERIOUS ----------------
    if guild_id is None or await can_send_in_guild(guild_id):
        prompt = build_general_prompt(chan_id, mode)

        if mode in ["funny", "roast"]:
            raw = await call_openrouter(
                prompt,
                model=pick_model(mode),
                max_tokens=677,
                temperature=1.1
            )
            reply = humanize_and_safeify(raw, short=True) if raw else choose_fallback()
            await send_human_reply(message.channel, reply, limit=100)

        elif mode == "serious":
            raw = await call_openrouter(
                prompt,
                model=pick_model(mode),
                temperature=0.7
            )
            reply = humanize_and_safeify(raw) if raw else choose_fallback()
            await send_human_reply(message.channel, reply)

        if raw:
            channel_memory[chan_id].append(f"{BOT_NAME}: {raw}")
            memory.add_message(chan_id, BOT_NAME, raw)
            memory.persist()

# ---------------- RUN ----------------
def run():
    client.run(DISCORD_TOKEN)

if __name__ == "__main__":
    run()
