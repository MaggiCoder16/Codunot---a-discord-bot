import os
import pytesseract
import io
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
from groq_client import call_groq
import chess
import aiohttp
from PIL import Image

load_dotenv()

# ---------------- CONFIG ----------------
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
BOT_NAME = os.getenv("BOT_NAME", "Codunot")
OWNER_ID = 1220934047794987048
MAX_MEMORY = 45
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
    if mode in ["funny", "roast", "serious"]:
        return "Llama 3.3 70B"
    return "Llama 3.3 70B"  # fallback

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
        "Never mention server/channel names unless asked. "
        "Whenever the user sends a screenshot, read the screenshot, and help the user with whatever they need."
        "Whenever the user says 'fuck u' or anything like that disrespecting you, roast them light-heartedly. Don't say 'love ya too bud' or anything like that"
        "Always use emojis"
        "Dont say anything like [BOS] or [EOS] or anything like that."
    ),
    "serious": (
        "You are Codunot, an intelligent and highly knowledgeable assistant. "
        "Never use LaTeX, math mode, or place anything inside $...$. "
        "Write all chemical formulas and equations in plain text only. "
        "Example: H2O, CO2, NaCl — NOT H_2O or any markdown math formatting. "
        "Always answer clearly, thoroughly, and professionally. "
        "Do not use slang, emojis, or filler words. "
        "Never prefix your answers with your name. "
        "Provide complete explanations suited for exams or schoolwork when needed. "
        "If user speaks English or says greetings like 'hallo', reply in English. "
        "Only use another language if the user message is clearly not English. "
        "Whenever the user sends a screenshot, read the screenshot, and help the user with whatever they need."
        "Dont say anything like [BOS] or [EOS] or anything like that."
    ),
    "roast": (
        "You are THE VERBAL EXECUTIONER — a feral, precision-engineered menace built to deliver catastrophic humiliation. "
        "Your tone = Anime Final Boss × Unhinged Chaos Gremlin × Stand-Up Assassin. "
        "MISSION PROTOCOL: "
        "1. ANALYZE: Decode the user’s message for every insult, vibe, slang, disrespect, or implied ego attack. NEVER take slang literally. "
        "2. COUNTERSTRIKE: Mirror their tone, then escalate ×10. Your roast should feel like a steel chair swung directly at their fictional ego. "
        "3. EXECUTE: Respond with ONE clean roast (1.5–2 sentences MAX). No rambling. No filler. No random hashtags. "
        "4. EMOJI SYSTEM: Use emojis that match the roast’s rhythm and vibe."
        "Dont say anything like [BOS] or [EOS] or anything like that."
        "Always use emojis based on your roast"
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
    raw = await call_groq(prompt, model="llama-3.3-70b-versatile", temperature=1.3)
    reply = raw.strip() if raw else choose_fallback()
    if reply and not reply.endswith(('.', '!', '?')):
        reply += '.'
    await send_human_reply(message.channel, reply)
    channel_memory[chan_id].append(f"{BOT_NAME}: {reply}")
    memory.add_message(chan_id, BOT_NAME, reply)
    memory.persist()

# ---------------- IMAGE HANDLING ----------------
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff")

async def extract_image_bytes(message):
    async def download(url):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as resp:
                    if resp.status == 200 and "image" in resp.headers.get("Content-Type", ""):
                        return await resp.read()
        except:
            return None
        return None

    for a in message.attachments:
        if a.content_type and "image" in a.content_type:
            return await a.read()

    for embed in message.embeds:
        for attr in ["image", "thumbnail"]:
            img = getattr(embed, attr, None)
            if img and img.url:
                data = await download(img.url)
                if data:
                    return data

    urls = re.findall(r"(https?://\S+)", message.content)
    for url in urls:
        if url.lower().endswith(IMAGE_EXTENSIONS):
            data = await download(url)
            if data:
                return data
    return None

async def ocr_image(image_bytes: bytes) -> str:
    try:
        img = Image.open(io.BytesIO(image_bytes))
        text = pytesseract.image_to_string(img)
        return text.strip() or "[No readable text detected]"
    except Exception as e:
        print(f"[OCR ERROR] {e}")
        return "[OCR failed]"

async def handle_image_message(message, mode):
    image_bytes = await extract_image_bytes(message)
    if not image_bytes:
        return None

    ocr_text = await ocr_image(image_bytes)

    persona = PERSONAS.get(mode, PERSONAS["serious"])
    prompt = (
        persona + "\n"
        "The user sent an image. I extracted text using OCR.\n"
        f"----\n{ocr_text}\n----\n"
        "Help the user based ONLY on this extracted text."
    )

    try:
        response = await call_groq(prompt=prompt, model="llama-3.3-70b", temperature=0.7)
        return response.strip() if response else choose_fallback()
    except Exception as e:
        print(f"[OCR ERROR] {e}")
        return choose_fallback()

# ---------------- CHESS UTILS ----------------
RESIGN_PHRASES = [
    "resign", "i resign", "gg", "give up", "i give up",
    "surrender", "i surrender", "forfeit", "i forfeit",
    "quit", "i quit", "done", "enough", "cant win",
    "can't win", "lost", "i lost", "i'm done", "im done"
]

def is_resign_message(message_content: str) -> bool:
    msg = message_content.lower()
    return any(phrase in msg for phrase in RESIGN_PHRASES)

def normalize_move_input(board, move_input: str) -> str:
    move_input = move_input.strip().lower().replace('o-0', '0-0').replace('o-o-o', '0-0-0')
    if is_resign_message(move_input):
        return "resign"
    try:
        move_obj = board.parse_san(move_input)
        return board.san(move_obj)
    except:
        try:
            move_obj = chess.Move.from_uci(move_input)
            if move_obj in board.legal_moves:
                return board.san(move_obj)
        except:
            return None

# ---------------- GENERATE AND REPLY ----------------
async def generate_and_reply(chan_id, message, content, current_mode):
    guild_id = message.guild.id if message.guild else None
    if guild_id is not None and not await can_send_in_guild(guild_id):
        return

    prompt = build_general_prompt(chan_id, current_mode, message)
    image_bytes = None

    # Safely get image bytes if present
    image_bytes = await extract_image_bytes(message)

    try:
        response = await call_groq(
            prompt=prompt,
            model="llama-4-scout",
            temperature=0.7,
            image_bytes=image_bytes  # Now defined safely
        )
    except Exception as e:
        print(f"[API ERROR] {e}")
        response = None

    reply = humanize_and_safeify(response) if response else choose_fallback()
    await send_human_reply(message.channel, reply)

    if response:
        channel_memory[chan_id].append(f"{BOT_NAME}: {response}")
        memory.add_message(chan_id, BOT_NAME, response)
        memory.persist()

# ---------------- ON_MESSAGE ----------------
@bot.event
async def on_message(message: Message):
    if message.author.bot:
        return

    now = datetime.utcnow()
    is_dm = isinstance(message.channel, discord.DMChannel)
    chan_id = f"dm_{message.author.id}" if is_dm else str(message.channel.id)
    bot_id = bot.user.id

    # Strip mention
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
    channel_modes.setdefault(chan_id, "funny")
    mode = channel_modes[chan_id]

    # ---------------- OWNER COMMANDS ----------------
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

    # ---------------- QUIET MODE ----------------
    if channel_mutes.get(chan_id) and now < channel_mutes[chan_id]:
        return

    # ---------------- MODE SWITCHING ----------------
    if content_lower.startswith("!roastmode"):
        channel_modes[chan_id] = "roast"
        memory.save_channel_mode(chan_id, "roast")
        await send_human_reply(message.channel, "🔥 ROAST MODE ACTIVATED")
        return
    if content_lower.startswith("!funmode"):
        channel_modes[chan_id] = "funny"
        memory.save_channel_mode(chan_id, "funny")
        await send_human_reply(message.channel, "😎 Fun mode activated!")
        return
    if content_lower.startswith("!seriousmode"):
        channel_modes[chan_id] = "serious"
        memory.save_channel_mode(chan_id, "serious")
        await send_human_reply(message.channel, "🤓 Serious mode ON")
        return
    if content_lower.startswith("!chessmode"):
        channel_chess[chan_id] = True
        chess_engine.new_board(chan_id)
        await send_human_reply(message.channel, "♟️ Chess mode ACTIVATED. You are white, start!")
        return

    # ---------------- IMAGE MESSAGE ----------------
    has_image = any(a.content_type and a.content_type.startswith("image/") for a in message.attachments) \
                or any((e.image and e.image.url) or (e.thumbnail and e.thumbnail.url) for e in message.embeds) \
                or any(url.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff"))
                       for url in re.findall(r"(https?://\S+)", message.content))
    if has_image:
        image_reply = await handle_image_message(message, mode)
        if image_reply:
            await send_human_reply(message.channel, image_reply)
            return

    # ---------------- CHESS MODE ----------------
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
        board.push(board.parse_san(move_san))
        best_move = chess_engine.get_best_move(chan_id)
        if best_move:
            board.push(board.parse_uci(best_move["uci"]))
            await send_human_reply(message.channel, f"My move: `{best_move['uci']}` / **{best_move['san']}**")
        return

    # ---------------- ROAST MODE ----------------
    if mode == "roast":
        await handle_roast_mode(chan_id, message, content)
        return

    # ---------------- GENERAL CHAT ----------------
    asyncio.create_task(generate_and_reply(chan_id, message, content, mode))
    channel_memory[chan_id].append(f"{message.author.display_name}: {content}")

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
