import os
import asyncio
import random
import re
from datetime import datetime, timedelta, timezone
from collections import deque

import discord
from discord import Message
from discord.ext import commands
from dotenv import load_dotenv

from memory import MemoryManager
from humanizer import humanize_response, maybe_typo
from bot_chess import OnlineChessEngine
from openrouter_client import call_openrouter
import chess

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
bot = commands.Bot(command_prefix="!", intents=intents)
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
        return "x-ai/grok-4.1-fast:free"
    if mode == "serious":
        return "mistralai/mistral-7b-instruct:free"
    return "x-ai/grok-4.1-fast:free"

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
        except Exception as e:
            print(f"[QUEUE ERROR] {e}")
        await asyncio.sleep(0.02)

async def send_human_reply(channel, reply_text):
    if hasattr(channel, "trigger_typing"):
        try:
            await channel.trigger_typing()
        except:
            pass
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

def get_mode_message(new_mode: str) -> str:
    messages = {
        "funny": "😎 Fun mode activated!",
        "roast": "🔥 ROAST MODE ACTIVATED",
        "serious": "🤓 Serious mode ON",
        "chess": "♟️ Chess mode ACTIVATED. You are white, start!"
    }
    return messages.get(new_mode, f"Mode set to {new_mode}!")

async def update_mode_and_memory(chan_id: str, new_mode: str):
    if new_mode not in ["funny", "roast", "serious", "chess"]:
        return
    # Clear memory on mode change
    if chan_id in channel_memory:
        channel_memory[chan_id].clear()
    memory.clear_history(chan_id)

    channel_modes[chan_id] = new_mode
    memory.save_channel_mode(chan_id, new_mode)

    channel_chess[chan_id] = (new_mode == "chess")
    if new_mode == "chess":
        chess_engine.new_board(chan_id)

# ---------------- PERSONAS ----------------
PERSONAS = {
    "funny": (
        "You are Codunot, a playful, witty friend. "
        "CRITICAL RULE: **MUST USE EMOJIS, SLANG, AND REPLY IN 1-2 LINES MAX.** "
        "Just chat naturally, don't ask the user what they need."
    ),
    "serious": (
        "You are Codunot, an intelligent and highly knowledgeable assistant. "
        "Always answer clearly, thoroughly, and professionally. "
        "Do not use slang or emojis."
    ),
    "roast": (
        "You are THE VERBAL EXECUTIONER, built to deliver savage roasts. "
        "Analyze user messages and generate ONE precise roast using emojis appropriately."
    )
}

# ---------------- PROMPT BUILDERS ----------------
def build_general_prompt(chan_id, mode, message):
    mem = channel_memory.get(chan_id, deque())
    history_text = "\n".join(mem)
    persona_text = PERSONAS.get(mode, PERSONAS["funny"])
    if message.guild:
        server_name = message.guild.name.strip()
        channel_name = message.channel.name.strip()
        location = f"This conversation is happening in the server '{server_name}', in the channel '{channel_name}'."
    else:
        location = "This conversation is happening in a direct message."
    return f"{persona_text}\n\n{location}\n\nRecent chat:\n{history_text}\n\nReply as Codunot:"

def build_roast_prompt(user_message):
    return PERSONAS["roast"] + f"\nUser message: '{user_message}'\nGenerate ONE savage, complete roast."

FALLBACK_VARIANTS = [
    "bruh my brain crashed 🤖💀 try again?",
    "my bad, I blanked out for a sec 😅",
    "lol my brain lagged 💀 say that again?",
    "oops, brain went AFK for a sec — can u repeat?"
]

def choose_fallback():
    return random.choice(FALLBACK_VARIANTS)

async def handle_roast_mode(chan_id, message, user_message):
    guild_id = message.guild.id if message.guild else None
    if not await can_send_in_guild(guild_id):
        return
    prompt = build_roast_prompt(user_message)
    raw = await call_openrouter(prompt, model=pick_model("roast"), temperature=1.3)
    reply = raw.strip() if raw else choose_fallback()
    if not reply.endswith(('.', '!', '?')):
        reply += '.'
    await send_human_reply(message.channel, reply)
    channel_memory[chan_id].append(f"{BOT_NAME}: {reply}")
    memory.add_message(chan_id, BOT_NAME, reply)
    memory.persist()

async def generate_and_reply(chan_id, message, content, current_mode):
    guild_id = message.guild.id if message.guild else None
    if guild_id is not None and not await can_send_in_guild(guild_id):
        return
    prompt = build_general_prompt(chan_id, current_mode, message)
    try:
        raw = await call_openrouter(
            prompt,
            model=pick_model(current_mode),
            temperature=1.1 if current_mode == "funny" else 0.7
        )
    except Exception as e:
        print(f"[API ERROR] {e}")
        raw = None
    reply = humanize_and_safeify(raw) if raw else choose_fallback()
    await send_human_reply(message.channel, reply)
    if raw:
        channel_memory[chan_id].append(f"{BOT_NAME}: {raw}")
        memory.add_message(chan_id, BOT_NAME, raw)
        memory.persist()

# ---------------- ON_MESSAGE ----------------
@bot.event
async def on_message(message: Message):
    if message.author.id == bot.user.id:
        return

    now = datetime.utcnow()
    is_dm = isinstance(message.channel, discord.DMChannel)
    chan_id = f"dm_{message.author.id}" if is_dm else str(message.channel.id)
    guild_id = message.guild.id if message.guild else None
    bot_id = bot.user.id

    content = message.content.strip()
    content_lower = content.lower()

    # Initialize modes/memory
    current_mode = channel_modes.get(chan_id) or memory.get_channel_mode(chan_id) or "funny"
    channel_modes[chan_id] = current_mode
    channel_mutes.setdefault(chan_id, None)
    channel_chess.setdefault(chan_id, False)
    channel_memory.setdefault(chan_id, deque(maxlen=MAX_MEMORY))

    # Admin mute commands
    if message.author.id == OWNER_ID:
        if content_lower.startswith("!quiet"):
            match = re.search(r"!quiet (\d+)([smhd])", content_lower)
            if match:
                num, unit = int(match.group(1)), match.group(2)
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

    # --- MODE COMMANDS FIRST ---
    if content_lower.startswith("!"):
        mode_alias = content_lower.lstrip("!").removesuffix("mode")
        mode_map = {"fun": "funny", "roast": "roast", "serious": "serious", "chess": "chess"}
        final_mode = mode_map.get(mode_alias)
        if final_mode:
            await update_mode_and_memory(chan_id, final_mode)
            await send_human_reply(message.channel, get_mode_message(final_mode))
            return

    # Remove mention if exists
    if bot_id in [m.id for m in message.mentions]:
        content = re.sub(rf"<@!?\s*{bot_id}\s*>", "", content).strip()
        content_lower = content.lower()

    channel_memory[chan_id].append(f"{message.author.display_name}: {content}")

    # Creator override
    creator_keywords = ["who is ur creator", "who made u", "who is your developer", "who created you"]
    if any(keyword in content_lower for keyword in creator_keywords):
        reply = (
            f"Wait, you think I'm from a massive lab? Nah.\n"
            f"Birthed from the chaos and brilliance of one human.\n"
            f"**Creator: @aarav_2022 (id {OWNER_ID})**"
        )
        await send_human_reply(message.channel, reply)
        channel_memory[chan_id].append(f"{BOT_NAME}: {reply}")
        memory.add_message(chan_id, BOT_NAME, reply)
        memory.persist()
        return

    # Chess handling
    if channel_chess.get(chan_id):
        board = chess_engine.get_board(chan_id)
        if len(content.split()) > 1:
            await send_human_reply(message.channel, "Send only valid chess moves (e.g., d4, Nf6).")
            return
        try:
            move_obj = board.parse_san(content)
            board.push(move_obj)
            if board.is_checkmate():
                await send_human_reply(message.channel, "Checkmate! You win. Use !chessmode to restart.")
                return
            elif board.is_stalemate():
                await send_human_reply(message.channel, "Stalemate! Draw.")
            bot_move = chess_engine.get_best_move(chan_id)
            if bot_move:
                bot_move_obj = board.parse_uci(bot_move)
                board.push(bot_move_obj)
                san = board.san(bot_move_obj)
                await send_human_reply(message.channel, f"My move: `{bot_move}` / **{san}**")
        except (chess.InvalidMoveError, ValueError):
            await send_human_reply(message.channel, f"❌ Invalid move or notation. Current turn: {'White' if board.turn == chess.WHITE else 'Black'}.")
        return

    # Roast mode
    if current_mode == "roast":
        await handle_roast_mode(chan_id, message, content)
        return

    # General reply
    if guild_id is None or await can_send_in_guild(guild_id):
        asyncio.create_task(generate_and_reply(chan_id, message, content, current_mode))

# ---------------- EVENTS ----------------
@bot.event
async def on_ready():
    print(f"{BOT_NAME} is ready!")
    asyncio.create_task(process_queue())

# ---------------- RUN ----------------
def run():
    bot.run(DISCORD_TOKEN)

if __name__ == "__main__":
    run()
