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
bot = discord.Client(intents=intents)
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
        return "x-ai/grok-4.1-fast"
    if mode == "serious":
        return "mistralai/mistral-7b-instruct:free"
    return "x-ai/grok-4.1-fast"

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

# ---------------- PERSONAS ----------------
PERSONAS = {
    "funny": (
        "You are Codunot, a playful, witty friend. "
        "CRITICAL RULE: MUST USE EMOJIS, SLANG, AND REPLY IN 1-2 LINES MAX. "
        "Reply in 1–2 lines, max 100 characters. Use slang and emojis. "
        "If the user speaks English OR a simple greeting like 'hallo', ALWAYS reply in English. "
        "Only reply in another language if it is clearly NOT English. "
        "Just chat naturally; don't ask the user what they need. "
        "You NEVER insult or swear at the user in ANY language. "
        "GAME REALITY RULE: You CANNOT play real video games. "
        "Text-based games only when user explicitly asks. "
        "Never prefix with your name. "
        "Never mention server/channel names unless asked."
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
        "If user speaks English or says greetings like 'hallo', reply in English. "
        "Only use another language if the user message is clearly not English."
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
    return PERSONAS["roast"] + f"\nUser message: '{user_message}'\nGenerate ONE savage roast."

async def handle_roast_mode(chan_id, message, user_message):
    guild_id = message.guild.id if message.guild else None
    if guild_id is not None and not await can_send_in_guild(guild_id):
        return
    prompt = build_roast_prompt(user_message)
    raw = await call_openrouter(prompt, model=pick_model("roast"), temperature=1.3)
    reply = raw.strip() if raw else choose_fallback()
    if reply and not reply.endswith(('.', '!', '?')):
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

# ---------------- IMAGE HANDLING ----------------
async def extract_image_bytes(message):
    if not message.attachments:
        return None
    for a in message.attachments:
        if a.content_type and ("image" in a.content_type):
            return await a.read()
    return None

# ---------------- CHESS UTILS ----------------
RESIGN_PHRASES = ["resign","i resign","gg","give up","i give up","surrender","i surrender","forfeit","quit","lost","im done","i'm done"]

def is_resign_message(message_content: str) -> bool:
    msg = message_content.lower()
    return any(p in msg for p in RESIGN_PHRASES)

def normalize_move_input(board, move_input: str) -> str:
    move_input = move_input.strip().lower()
    if is_resign_message(move_input):
        return "resign"

    legal_moves = list(board.legal_moves)

    if len(move_input) == 2 and move_input[0] in "abcdefgh" and move_input[1] in "123456":
        try:
            target = chess.parse_square(move_input)
            candidates = [m for m in legal_moves if m.to_square == target]
            if len(candidates) == 1:
                return board.san(candidates[0])
        except:
            pass

    try:
        return board.san(board.parse_san(move_input))
    except:
        pass

    try:
        mv = chess.Move.from_uci(move_input)
        if mv in legal_moves:
            return board.san(mv)
    except:
        pass

    return None

# ---------------- ON_MESSAGE ----------------
@bot.event
async def on_message(message: Message):
    if message.author.bot:
        return

    now = datetime.utcnow()
    is_dm = isinstance(message.channel, discord.DMChannel)
    chan_id = f"dm_{message.author.id}" if is_dm else str(message.channel.id)
    guild_id = message.guild.id if message.guild else None
    bot_id = bot.user.id

    # Require ping in servers
    if not is_dm and bot_id not in [m.id for m in message.mentions]:
        return

    # Strip bot mention
    content = re.sub(rf"<@!?\s*{bot_id}\s*>", "", message.content).strip()
    content_lower = content.lower()

    # Load or set default mode
    saved_mode = memory.get_channel_mode(chan_id)
    channel_modes[chan_id] = saved_mode if saved_mode else "funny"
    if not saved_mode:
        memory.save_channel_mode(chan_id, "funny")

    # Ensure mem slots
    channel_mutes.setdefault(chan_id, None)
    channel_chess.setdefault(chan_id, False)
    channel_memory.setdefault(chan_id, deque(maxlen=MAX_MEMORY))
    mode = channel_modes[chan_id]

    # Owner commands
    if message.author.id == OWNER_ID:
        if content_lower.startswith("!quiet"):
            match = re.search(r"!quiet (\d+)([smhd])", content_lower)
            if match:
                num = int(match.group(1))
                sec = num * {"s":1,"m":60,"h":3600,"d":86400}[match.group(2)]
                channel_mutes[chan_id] = datetime.utcnow() + timedelta(seconds=sec)
                await send_human_reply(message.channel, f"I'll stop yapping for {format_duration(num, match.group(2))}.")
            return
        if content_lower.startswith("!speak"):
            channel_mutes[chan_id] = None
            await send_human_reply(message.channel, "YOO I'm back 😎🔥")
            return

    # Quiet mode
    if channel_mutes.get(chan_id) and now < channel_mutes[chan_id]:
        return

    # Mode switching — wipes context
    if "!roastmode" in content_lower:
        channel_modes[chan_id] = "roast"
        memory.save_channel_mode(chan_id, "roast")
        channel_memory[chan_id].clear()
        memory.clear_channel(chan_id)
        await send_human_reply(message.channel, "🔥 ROAST MODE ACTIVATED")
        return

    if "!funmode" in content_lower:
        channel_modes[chan_id] = "funny"
        memory.save_channel_mode(chan_id, "funny")
        channel_memory[chan_id].clear()
        memory.clear_channel(chan_id)
        await send_human_reply(message.channel, "😎 Fun mode activated!")
        return

    if "!seriousmode" in content_lower:
        channel_modes[chan_id] = "serious"
        memory.save_channel_mode(chan_id, "serious")
        channel_memory[chan_id].clear()
        memory.clear_channel(chan_id)
        await send_human_reply(message.channel, "🤓 Serious mode ON")
        return

    if "!chessmode" in content_lower:
        channel_chess[chan_id] = True
        chess_engine.new_board(chan_id)
        await send_human_reply(message.channel, "♟️ Chess mode ACTIVATED. You are white, start!")
        return

    # Log user message in memory
    channel_memory[chan_id].append(f"{message.author.display_name}: {content}")

    # ---------------- IMAGE HANDLING ----------------
    image_bytes = await extract_image_bytes(message)
    if image_bytes:
        vision_prompt = (
            f"{PERSONAS[mode]}\n"
            "The user sent an image. Describe what is visible clearly, accurately, and helpfully.\n"
            "Do NOT mention the model, do NOT speak in system voice. "
            "Speak in the current persona's style.\n"
        )
        response = await call_openrouter(
            vision_prompt,
            model="anthropic/claude-3.7-sonnet",
            image_bytes=image_bytes
        )
        await send_human_reply(message.channel, response)
        return

    # ---------------- Chess mode ----------------
    if channel_chess.get(chan_id):
        board = chess_engine.get_board(chan_id)
        move_san = normalize_move_input(board, content)

        if move_san == "resign":
            await send_human_reply(message.channel, f"{message.author.display_name} resigned! I win 😎")
            channel_chess[chan_id] = False
            return

        if not move_san:
            await send_human_reply(message.channel, f"Invalid move: {content}")
            return

        move_obj = board.parse_san(move_san)
        board.push(move_obj)

        if board.is_checkmate():
            await send_human_reply(message.channel, f"Checkmate — you win! ({move_san})")
            channel_chess[chan_id] = False
            return

        best_move = chess_engine.get_best_move(chan_id)
        if best_move:
            bot_move = board.parse_uci(best_move["uci"])
            board.push(bot_move)
            await send_human_reply(message.channel, f"My move: `{best_move['uci']}` / **{best_move['san']}**")
            if board.is_checkmate():
                await send_human_reply(message.channel, f"Checkmate — I win ({best_move['san']})")
                channel_chess[chan_id] = False
        return

    # ---------------- Roast mode ----------------
    if mode == "roast":
        await handle_roast_mode(chan_id, message, content)
        return

    # ---------------- General chat ----------------
    if guild_id is None or await can_send_in_guild(guild_id):
        asyncio.create_task(generate_and_reply(chan_id, message, content, mode))

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
