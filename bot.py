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
from humanizer import humanize_response, maybe_typo, is_roast_trigger
from bot_chess import OnlineChessEngine

# OpenRouter client (your file)
from openrouter_client import call_openrouter

load_dotenv()

# ---------------- CONFIG ----------------
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
BOT_NAME = os.getenv("BOT_NAME", "Codunot")
BOT_USER_ID = 1435987186502733878
OWNER_ID = 1220934047794987048
MAX_MEMORY = 30
MAX_MSG_LEN = 3000
RATE_LIMIT = 900  # msgs per 60 seconds per guild

# ---------------- CLIENT ----------------
intents = discord.Intents.all()
intents.message_content = True
client = discord.Client(intents=intents)
memory = MemoryManager(limit=60, file_path="codunot_memory.json")
chess_engine = OnlineChessEngine()

# ---------------- STATES ----------------
message_queue = asyncio.Queue()
channel_modes = {}     # channel_id -> mode
channel_mutes = {}     # channel_id -> mute_until datetime
channel_chess = {}     # channel_id -> bool
channel_memory = {}    # channel_id -> deque(maxlen=MAX_MEMORY)
rate_buckets = {}      # guild_id -> deque of timestamps for rate-limiting

# ---------------- HELPERS ----------------
def format_duration(num: int, unit: str) -> str:
    units = {"s": "second", "m": "minute", "h": "hour", "d": "day"}
    name = units.get(unit, "minute")
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
            # swallow send errors to avoid crashing queue loop
            pass
        await asyncio.sleep(0.02)

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
    # keep your existing cleaning
    text = text.replace(" idk", "").replace(" *nvm", "")
    if random.random() < 0.1:
        text = maybe_typo(text)
    if short:
        text = text.strip()[:100]
        if not text.endswith(('.', '!', '?')):
            text += '.'
    return text

def is_admin(member: discord.Member):
    try:
        return member.id == OWNER_ID or any(role.permissions.administrator for role in member.roles)
    except Exception:
        return member.id == OWNER_ID

async def can_send_in_guild(guild_id: int) -> bool:
    now = datetime.now(timezone.utc)
    bucket = rate_buckets.setdefault(guild_id, deque())
    # purge old timestamps older than 60s
    while bucket and (now - bucket[0]).total_seconds() > 60:
        bucket.popleft()
    if len(bucket) < RATE_LIMIT:
        bucket.append(now)
        return True
    return False

# ---------------- PROMPTS ----------------
def build_general_prompt(chan_id, mode):
    mem = channel_memory.get(chan_id, deque())
    history_text = "\n".join(mem)
    persona_self_protect = "Never roast or attack yourself (Codunot). If asked to roast Codunot, gently refuse."
    if mode == "serious":
        persona = (
            "You are Codunot, a precise and knowledgeable helper. "
            "You answer with direct factual info. No emojis, no slang."
        )
    else:
        persona = (
            "You are Codunot, a playful, witty friend. "
            "Reply in 1–2 lines, max 100 characters. Use slang and emojis."
        )
    return f"{persona}\n{persona_self_protect}\n\nRecent chat:\n{history_text}\n\nReply as Codunot:"

def build_roast_prompt(chan_id, target, mode):
    if str(target).lower() in ["codunot", str(BOT_USER_ID)]:
        return "Refuse to roast yourself in a funny way."
    mem = channel_memory.get(chan_id, deque())
    history_text = "\n".join(mem)
    if mode == "roast":
        persona = (
            "You are Codunot, a feral, brutal roast-master. "
            "Write a short, 1–2 line roast, max 100 characters. Roast HARD."
        )
    else:
        persona = "Friendly, playful one-line roast with emojis (max 100 characters)."
    return f"{persona}\nTarget: {target}\nRecent chat:\n{history_text}\nRoast:"

# ---------------- FALLBACK STRINGS (mixed funny + chill) ----------------
FALLBACK_VARIANTS = [
    "bruh my brain crashed 🤖💀 try again?",
    "my bad, I blanked out for a sec 😅",
    "lol my brain lagged 💀 say that again?",
    "oops, brain went AFK for a sec — can u repeat?"
]

def choose_fallback():
    # Mix funny + chill (weighted roughly equally)
    return random.choice(FALLBACK_VARIANTS)

# ---------------- EVENTS ----------------
@client.event
async def on_ready():
    print(f"{BOT_NAME} is ready!")
    # start message sender task
    asyncio.create_task(process_queue())

@client.event
async def on_message(message: Message):
    # ignore self
    if message.author == client.user:
        return

    now = datetime.utcnow()
    is_dm = isinstance(message.channel, discord.DMChannel)
    chan_id = str(message.channel.id) if not is_dm else f"dm_{message.author.id}"
    guild_id = message.guild.id if message.guild else None

    # Only respond in servers when mentioned; always respond in DMs
    if not is_dm and client.user not in message.mentions:
        return

    # remove mention(s) for processing
    # handle both <@ID> and <@!ID>
    content = re.sub(rf"<@!?\s*{BOT_USER_ID}\s*>", "", message.content).strip()
    content_lower = content.lower()

    # initialize channel state
    if chan_id not in channel_modes:
        channel_modes[chan_id] = "funny"
    if chan_id not in channel_mutes:
        channel_mutes[chan_id] = None
    if chan_id not in channel_chess:
        channel_chess[chan_id] = False
    if chan_id not in channel_memory:
        channel_memory[chan_id] = deque(maxlen=MAX_MEMORY)
    mode = channel_modes[chan_id]

    # Owner-only commands
    if message.author.id == OWNER_ID:
        if content_lower.startswith("!quiet"):
            match = re.search(r"!quiet (\d+)([smhd])", content_lower)
            if match:
                num = int(match.group(1))
                unit = match.group(2)
                seconds = num * {"s":1, "m":60, "h":3600, "d":86400}[unit]
                channel_mutes[chan_id] = datetime.utcnow() + timedelta(seconds=seconds)
                await send_human_reply(message.channel, f"I'll stop yapping for {format_duration(num, unit)}.")
            return
        if content_lower.startswith("!speak"):
            channel_mutes[chan_id] = None
            await send_human_reply(message.channel, "YOO I'm back 😎🔥")
            return

    # respect per-channel mute
    if channel_mutes.get(chan_id) and now < channel_mutes[chan_id]:
        return

    # Mode switches
    if "!roastmode" in content_lower:
        channel_modes[chan_id] = "roast"
        await send_human_reply(message.channel, "🔥 Roast mode ACTIVATED")
        return
    if "!funmode" in content_lower:
        channel_modes[chan_id] = "funny"
        await send_human_reply(message.channel, "😎 Fun mode activated!")
        return
    if "!seriousmode" in content_lower:
        channel_modes[chan_id] = "serious"
        await send_human_reply(message.channel, "🤓 Serious mode ON")
        return
    if "!chessmode" in content_lower:
        channel_chess[chan_id] = True
        chess_engine.new_board(chan_id)
        await send_human_reply(message.channel, "♟️ Chess mode ACTIVATED. You are white, start the game!")
        return

    # Save memory (short-term channel memory)
    channel_memory[chan_id].append(f"{message.author.display_name}: {content}")

    # ---------------- CHESS MODE ----------------
    if channel_chess.get(chan_id):
        board = chess_engine.get_board(chan_id)
        try:
            move = board.parse_san(content)
            board.push(move)

            bot_move = chess_engine.get_best_move(chan_id)
            if bot_move:
                chess_engine.push_uci(chan_id, bot_move)
                await send_human_reply(message.channel, f"My move: `{bot_move}`")
            else:
                await send_human_reply(message.channel, "Couldn't calculate move 😅")
            return

        except ValueError:
            # Not a SAN move -> treat as chess question (if rate limiter allows)
            if guild_id is None or await can_send_in_guild(guild_id):
                try:
                    raw = await call_openrouter(f"You are a chess expert. Answer briefly: {content}")
                except Exception:
                    raw = None

                if raw:
                    reply = humanize_and_safeify(raw, short=True)
                    await send_human_reply(message.channel, reply, limit=150)
                else:
                    # On failure: 25% chance fallback, else silent
                    if random.random() < 0.25:
                        await send_human_reply(message.channel, choose_fallback())
            return

    # ---------------- ROAST TRIGGER ----------------
    roast_target = is_roast_trigger(content)
    if roast_target:
        # only reply if rate limit allows (or DM)
        if guild_id is None or await can_send_in_guild(guild_id):
            prompt = build_roast_prompt(chan_id, roast_target, mode)
            try:
                raw = await call_openrouter(prompt)
            except Exception:
                raw = None

            if raw:
                reply = humanize_and_safeify(raw, short=True)
                await send_human_reply(message.channel, reply, limit=100)
                channel_memory[chan_id].append(f"{BOT_NAME}: {reply}")
            else:
                # failure behavior: 25% fallback, otherwise silent
                if random.random() < 0.25:
                    await send_human_reply(message.channel, choose_fallback())
        return

    # ---------------- GENERAL ----------------
    if guild_id is None or await can_send_in_guild(guild_id):
        prompt = build_general_prompt(chan_id, mode)
        try:
            raw = await call_openrouter(prompt)
        except Exception:
            raw = None

        if raw:
            reply = humanize_and_safeify(raw, short=(mode != "serious"))
            await send_human_reply(message.channel, reply, limit=100 if mode != "serious" else None)
            channel_memory[chan_id].append(f"{BOT_NAME}: {reply}")
            memory.add_message(chan_id, BOT_NAME, reply)
            memory.persist()
        else:
            # failure behavior: 25% fallback, otherwise silent
            if random.random() < 0.25:
                await send_human_reply(message.channel, choose_fallback())

# ---------------- RUN ----------------
def run():
    client.run(DISCORD_TOKEN)

if __name__ == "__main__":
    run()
