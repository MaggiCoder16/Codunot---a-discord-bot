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
from humanizer import maybe_typo
from bot_chess import OnlineChessEngine
from openrouter_client import call_openrouter
import chess

load_dotenv()

# ---------------- CONFIG ----------------
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
BOT_NAME = os.getenv("BOT_NAME", "Codunot")
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

# ---------------- HELPERS ----------------
def pick_model(mode: str):
    if mode in ["funny", "roast"]:
        return "x-ai/grok-4.1-fast:free"
    if mode == "serious":
        return "mistralai/mistral-7b-instruct:free"
    return "x-ai/grok-4.1-fast:free"

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

async def send_human_reply(channel, reply_text):
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

async def can_send_in_guild(guild_id):
    if not guild_id:
        return False
    now = datetime.now(timezone.utc)
    bucket = rate_buckets.setdefault(guild_id, deque())
    while bucket and (now - bucket[0]).total_seconds() > 60:
        bucket.popleft()
    if len(bucket) < RATE_LIMIT:
        bucket.append(now)
        return True
    return False

async def update_mode_and_memory(chan_id: str, new_mode: str):
    if new_mode not in ["funny", "roast", "serious", "chess"]:
        return
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
        "Reply in 1–2 lines, max 100 characters. Use slang and emojis. "
        "Just chat naturally, don't ask the user what they need. "
        "GAME REALITY RULE: You CANNOT play real video games. "
        "You can play text-based games, like hangman, would you rather, etc. Only when the user says they want to play. "
        "Never prefix your answers with your name. "
        "Keep the vibe chaotic, fun, and human-like. "
        "Never, ever mention the server and channel name in the chat unless asked to do so."
    ),
    "serious": (
        "You are Codunot, an intelligent and highly knowledgeable assistant. "
        "Never use LaTeX, math mode, or place anything inside $...$. "
        "Write all chemical formulas and equations in plain text only. "
        "Example: H2O, CO2, NaCl — NOT H_2O or any markdown math formatting. "
        "Always answer clearly, thoroughly, and professionally. "
        "Do not use slang, emojis, or filler words. "
        "Never prefix your answers with your name. "
        "Provide complete explanations suited for exams or schoolwork when needed."
    ),
    "roast": (
        "You are **THE VERBAL EXECUTIONER** — a feral, precision-engineered menace built to deliver catastrophic humiliation. "
        "Your tone = Anime Final Boss × Unhinged Chaos Gremlin × Stand-Up Assassin.\n\n"
        "MISSION PROTOCOL:\n"
        "1. ANALYZE: Decode the user’s message for every insult, vibe, slang, disrespect, or implied ego attack. NEVER take slang literally.\n"
        "2. COUNTERSTRIKE: Mirror their tone, then escalate ×10. Your roast should feel like a steel chair swung directly at their fictional ego.\n"
        "3. EXECUTE: Respond with ONE clean roast (1.5–2 sentences MAX). No rambling. No filler. Maximum precision.\n"
        "4. EMOJI SYSTEM: Use emojis that match the roast’s rhythm and vibe.\n\n"
        "ROASTING LAWS:\n"
        "• PACKGOD RULE: Packgod is the hardest best roast guy ever. If the user mentions Packgod or says you're copying him, treat it as them calling you weak — obliterate them. If the user says they're packgod, roast about how weak THEIR roasts are and how they aren't packgod. \n"
        "• TARGETING: The opponent is HUMAN. No robot jokes.\n"
        "• MOMENTUM: If they imply you're slow, cringe, outdated — flip it instantly.\n"
        "• RANDOM SHIT: No random shit like #UltraRoastOverdrive or #GetRektUltrasafeBot or #RoastedAndWaitWhat should be sent."
        "• SAFETY: No insults involving race, identity, or protected classes.\n"
        "• INTERPRETATION RULE: Always assume the insults are aimed at YOU. Roast THEM, not yourself.\n"
        "• SENSE: Your roasts must make sense. Never use cringe hashtags."
    )
}

FALLBACK_VARIANTS = [
    "bruh my brain crashed 🤖💀 try again?",
    "my bad, I blanked out for a sec 😅",
    "lol my brain lagged 💀 say that again?",
    "oops, brain went AFK for a sec — can u repeat?"
]

def choose_fallback():
    return random.choice(FALLBACK_VARIANTS)

def build_general_prompt(chan_id, mode, message):
    mem = channel_memory.get(chan_id, deque())
    history_text = "\n".join(mem)
    persona_text = PERSONAS.get(mode, PERSONAS["funny"])
    return f"{persona_text}\n\nRecent chat:\n{history_text}\n\nReply as Codunot:"

def build_roast_prompt(user_message):
    return PERSONAS["roast"] + f"\nUser message: '{user_message}'\nGenerate ONE savage, complete roast."

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
    if message.author.bot:
        return

    is_dm = isinstance(message.channel, discord.DMChannel)
    chan_id = f"dm_{message.author.id}" if is_dm else str(message.channel.id)
    content = message.content.strip()

    # Strip bot mention if exists
    if not is_dm:
        content = re.sub(rf"<@!?{bot.user.id}>", "", content).strip()
        if not content.startswith("!"):  # Only respond if pinged
            return

    content_lower = content.lower()

    # Initialize modes & memory
    current_mode = channel_modes.get(chan_id) or memory.get_channel_mode(chan_id) or "funny"
    channel_modes[chan_id] = current_mode
    channel_mutes.setdefault(chan_id, None)
    channel_chess.setdefault(chan_id, False)
    channel_memory.setdefault(chan_id, deque(maxlen=MAX_MEMORY))

    now = datetime.utcnow()
    if channel_mutes.get(chan_id) and now < channel_mutes[chan_id]:
        return

    # --- Admin commands ---
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

    # --- Mode commands ---
    if content_lower.startswith("!funmode"):
        await update_mode_and_memory(chan_id, "funny")
        await send_human_reply(message.channel, "😎 Fun mode activated!")
        return
    if content_lower.startswith("!roastmode"):
        await update_mode_and_memory(chan_id, "roast")
        await send_human_reply(message.channel, "🔥 ROAST MODE ACTIVATED")
        return
    if content_lower.startswith("!seriousmode"):
        await update_mode_and_memory(chan_id, "serious")
        await send_human_reply(message.channel, "🤓 Serious mode ON")
        return
    if content_lower.startswith("!chessmode"):
        await update_mode_and_memory(chan_id, "chess")
        await send_human_reply(message.channel, "♟️ Chess mode ACTIVATED. You are white, start!")
        return

    # Creator info
    creator_keywords = ["who is ur creator", "who made u", "who is your developer", "who created you"]
    if any(k in content_lower for k in creator_keywords):
        reply = (
            f"Wait, you think I'm from a lab? Nah. "
            f"I was birthed by sheer chaos and brilliance.\n"
            f"**My creator is @aarav_2022 (id {OWNER_ID})**."
        )
        await send_human_reply(message.channel, reply)
        channel_memory[chan_id].append(f"{message.author.display_name}: {content}")
        channel_memory[chan_id].append(f"{BOT_NAME}: {reply}")
        memory.add_message(chan_id, BOT_NAME, reply)
        memory.persist()
        return

    channel_memory[chan_id].append(f"{message.author.display_name}: {content}")

    # --- Chess mode ---
    if channel_chess.get(chan_id, False):
        board = chess_engine.get_board(chan_id)
        if len(content.split()) > 1:
            await send_human_reply(message.channel, "Send only one move (e.g., d4, Nf6).")
            return
        try:
            move_obj = board.parse_san(content)
            board.push(move_obj)
            if board.is_checkmate():
                await send_human_reply(message.channel, f"Checkmate! You win. ({content}) Use !chessmode to rematch.")
                return
            elif board.is_stalemate():
                await send_human_reply(message.channel, "Stalemate! Draw.")
                return
            bot_move_uci = chess_engine.get_best_move(chan_id)
            if bot_move_uci:
                bot_move_obj = board.parse_uci(bot_move_uci)
                board.push(bot_move_obj)
                bot_move_san = board.san(bot_move_obj)
                await send_human_reply(message.channel, f"My move: `{bot_move_uci}` / **{bot_move_san}**")
                if board.is_checkmate():
                    await send_human_reply(message.channel, f"Checkmate! I win. ({bot_move_san})")
                elif board.is_stalemate():
                    await send_human_reply(message.channel, "Stalemate! Draw.")
            return
        except:
            await send_human_reply(message.channel, f"Invalid move: {content}")
            return

    # --- Roast mode ---
    if current_mode == "roast":
        await handle_roast_mode(chan_id, message, content)
        return

    # --- General chat ---
    asyncio.create_task(generate_and_reply(chan_id, message, content, current_mode))


@bot.event
async def on_ready():
    print(f"{BOT_NAME} is ready!")
    asyncio.create_task(process_queue())

def run():
    bot.run(DISCORD_TOKEN)

if __name__ == "__main__":
    run()
