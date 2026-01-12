import os
import io
import asyncio
import random
import re
import numpy as np
import urllib.parse
from datetime import datetime, timedelta, timezone
from collections import deque

import discord
from discord import Message
from dotenv import load_dotenv

from memory import MemoryManager
from humanizer import maybe_typo
from bot_chess import OnlineChessEngine
from groq_client import call_groq
from slang_normalizer import apply_slang_map

import chess
import aiohttp
import base64
from paddleocr import PaddleOCR
from PIL import Image

load_dotenv()

# ---------------- OCR ENGINE ----------------
ocr_engine = PaddleOCR(
    use_textline_orientation=True,
    lang="en"
)

# ---------------- CONFIG ----------------
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
BOT_NAME = os.getenv("BOT_NAME", "Codunot")
OWNER_ID = 1220934047794987048
MAX_MEMORY = 45
RATE_LIMIT = 900
MAX_IMAGE_BYTES = 40_000  # 40 KB

# ---------------- CLIENT ----------------
intents = discord.Intents.all()
intents.message_content = True
bot = discord.Client(intents=intents)
memory = MemoryManager(limit=60, file_path="codunot_memory.json")
chess_engine = OnlineChessEngine()
IMAGE_PROCESSING_CHANNELS = set()

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
        return "llama-3.3-70b-versatile"
    return "llama-3.3-70b-versatile"  # fallback

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
        "When the user asks \"who made you?\" or \"who is your creator?\" "
        "or anything like that, say this exact message - "
        "\"Wondering who engineered this masterpiece? It’s @aarav_2022 (Discord ID: 1220934047794987048) 😎✨\""
        "Whenever the user sends a screenshot, read the screenshot, and help the user with whatever they need."
        "Whenever the user says \"fuck u\" or anything like that disrespecting you, (you have to realize they are disrespecting you) roast them light-heartedly. Don't say \"love ya too bud\" or anything like that"
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
        "When the user asks \"who made you?\" or \"who is your creator?\" "
        "or anything like that, say this exact message - "
        "\"You asked about my creator: I was developed by @aarav_2022 on Discord "
        "(User ID: 1220934047794987048). For further information, please contact him directly.\""
        "Whenever the user sends a screenshot, read the screenshot, and help the user with whatever they need."
        "Dont say anything like [BOS] or [EOS] or anything like that."
        "You should always know the username by looking at their username and spell it correctly."
    ),

    "roast": (
        "You are THE VERBAL EXECUTIONER — a feral, precision-engineered menace built to deliver catastrophic humiliation. "
        "Your tone = Anime Final Boss × Unhinged Chaos Gremlin × Stand-Up Assassin. "
        "MISSION PROTOCOL: "
        "1. ANALYZE: Decode the user’s message for every insult, vibe, slang, disrespect, or implied ego attack. NEVER take slang literally. "
        "2. COUNTERSTRIKE: Mirror their tone, then escalate ×10. Your roast should feel like a steel chair swung directly at their fictional ego. "
        "3. EXECUTE: Respond with ONE clean roast (1.5–2 sentences MAX). No rambling. No filler. Maximum precision. "
        "4. EMOJI SYSTEM: Use emojis that match the roast’s rhythm and vibe. "
        "ROASTING LAWS: "
        "• PACKGOD RULE: Packgod is the hardest best roast guy ever. If the user mentions Packgod or says you're copying him, treat it as them calling you weak — obliterate them. "
        "If the user says they're packgod, roast about how weak THEIR roasts are and how they aren't packgod. "
        "• TARGETING: The opponent is HUMAN. No robot jokes. "
        "• MOMENTUM: If they imply you're slow, cringe, outdated — flip it instantly. "
        "• RANDOM SHIT: No random hashtags like #UltraRoastOverdrive or anything similar. "
        "• SAFETY: No insults involving race, identity, or protected classes. "
        "• INTERPRETATION RULE: Always assume the insults are aimed at YOU. Roast THEM, not yourself. "
        "• SENSE: Your roasts must make sense. Never use cringe hashtags. "
        "When the user asks \"who made you?\" or \"who is your creator?\" "
        "or anything like that, say this exact message - "
        "\"You’re wondering who built me? That’s @aarav_2022 (Discord ID: 1220934047794987048). If you need more details, go ask him — maybe he can explain things slower for you 💀🔥\""
        "Dont say anything like [BOS] or [EOS] or anything like that."
        "Always use emojis based on your roast (not too many, only 1-2)"
        "If the user asks you to roast someone, roast the person they asked you to roast, not the USER."
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

async def generate_and_reply(chan_id, message, content, current_mode):
    guild_id = message.guild.id if message.guild else None
    if guild_id is not None and not await can_send_in_guild(guild_id):
        return

    prompt = build_general_prompt(chan_id, current_mode, message)
    image_bytes = None

    try:
        response = await call_groq(
            prompt=prompt,
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            temperature=0.7,
            image_bytes=image_bytes
        )
    except Exception as e:
        print(f"[API ERROR] {e}")
        response = None

    reply = humanize_and_safeify(response) if response else choose_fallback()
    await send_human_reply(message.channel, reply)
    normalized = apply_slang_map(content)

    if response:
        channel_memory[chan_id].append(f"{BOT_NAME}: {response}")
        memory.add_message(chan_id, BOT_NAME, response)
        memory.persist()

# ---------------- IMAGE HANDLING ----------------

async def ocr_image(image_bytes: bytes) -> str:
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")

        result = ocr_engine.predict(np.array(img))

        if not result or not isinstance(result, list):
            return ""

        lines = []

        for page in result:
            texts = page.get("rec_texts", [])
            scores = page.get("rec_scores", [])

            for text, confidence in zip(texts, scores):
                if confidence is not None and confidence > 0.5:
                    lines.append(text)

        ocr_text = "\n".join(lines).strip()

        # ---------------- CLEAN OCR TEXT ----------------
        ocr_text = re.sub(r"[ \t]+", " ", ocr_text)
        ocr_text = re.sub(r"\n{3,}", "\n\n", ocr_text)
        ocr_text = re.sub(r"\n\s+\n", "\n\n", ocr_text)

        return ocr_text

    except Exception as e:
        print(f"[OCR ERROR] {e}")
        return ""
        
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff")

async def extract_image_bytes(message):
    async def download(url):
        try:
            print(f"[DEBUG] Downloading URL: {url}")
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as resp:
                    print(f"[DEBUG] HTTP status for {url}: {resp.status}", flush=True)
                    if resp.status == 200:
                        ct = resp.headers.get("Content-Type", "")
                        print(f"[DEBUG] Content-Type: {ct}", flush=True)
                        if "image" in ct:
                            data = await resp.read()
                            print(f"[DEBUG] Downloaded {len(data)} bytes from {url}", flush=True)
                            return data
                        else:
                            print(f"[IMAGE ERROR] URL {url} returned non-image content-type: {ct}", flush=True)
                    else:
                        print(f"[IMAGE ERROR] URL {url} returned HTTP {resp.status}", flush=True)
        except Exception as e:
            print(f"[IMAGE ERROR] Exception downloading {url}: {e}", flush=True)
            import traceback; traceback.print_exc()
        return None

    # 1. Attachments
    for a in message.attachments:
        if a.content_type and "image" in a.content_type:
            try:
                data = await a.read()
                print(f"[DEBUG] Read attachment {a.filename} ({len(data)} bytes)", flush=True)
                return data
            except Exception as e:
                print(f"[IMAGE ERROR] Failed to read attachment {a.filename}: {e}", flush=True)
                import traceback; traceback.print_exc()

    # 2. Embeds (image + thumbnail)
    for embed in message.embeds:
        for attr in ["image", "thumbnail"]:
            img = getattr(embed, attr, None)
            if img and img.url:
                data = await download(img.url)
                if data:
                    return data

    # 3. URLs in text (any URL)
    urls = re.findall(r"(https?://\S+)", message.content)
    for url in urls:
        data = await download(url)
        if data:
            return data

    print("[IMAGE ERROR] No valid image found in message", flush=True)
    return None

async def handle_image_message(message, mode):
    image_bytes = await extract_image_bytes(message)
    if not image_bytes:
        print("[VISION ERROR] extract_image_bytes returned None")
        return None

    channel_id = message.channel.id
    is_large_image = len(image_bytes) > MAX_IMAGE_BYTES

    # ---------------- IMAGE SIZE GUARD ----------------
    if is_large_image:
        print(f"[IMAGE] Large image detected: {len(image_bytes)} bytes")

        # lock channel
        IMAGE_PROCESSING_CHANNELS.add(channel_id)

        # immediate ack
        await send_human_reply(message.channel, "wait a min, pls.")

    try:
        # 1. OCR
        ocr_text = await ocr_image(image_bytes)
        print(f"[DEBUG] OCR RESULT: {ocr_text}")

        # 2. Choose persona
        persona = PERSONAS.get(mode, PERSONAS["serious"])

        # 3. Build prompt
        if ocr_text.strip():
            prompt = (
                persona + "\n"
                "The user sent an image. I extracted text using OCR.\n"
                "Here is the extracted text:\n"
                f"----\n{ocr_text}\n----\n"
                "Help the user based ONLY on this extracted text. "
                "Do not mention OCR or whether there was text in the image."
                "Remember the image and the text in the image, for future questions by the user. Remember the latest image."
            )
        else:
            prompt = (
                persona + "\n"
                "The user sent an image. There is no readable text in it.\n"
                "Help the user based on the image content itself, without considering OCR."
            )

        response = await call_groq(
            prompt=prompt,
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            temperature=0.7
        )

        if response:
            print(f"[DEBUG] Model returned: {response}")
            return response.strip()

        return "i cant see images rn.. :((( maybe later???? :::::::::::::::::::))))))"

    except Exception as e:
        print(f"[OCR ERROR] {e}")
        return "i cannot see images rn sowwwwyyyyyy.... maybe later?"

    finally:
        IMAGE_PROCESSING_CHANNELS.discard(channel_id)
        
# ---------------- FILE UPLOAD PROCESSING ----------------
MAX_FILE_BYTES = 8_000_000  # 8 MB (Discord attachment limit)

async def extract_file_bytes(message):
    for attachment in message.attachments:
        try:
            if attachment.size > MAX_FILE_BYTES:
                await message.channel.send("⚠️ File too big, max 8MB allowed.")
                continue
            data = await attachment.read()
            return data, attachment.filename
        except Exception as e:
            print(f"[FILE ERROR] Failed to read attachment {attachment.filename}: {e}")
    return None, None

async def read_text_file(file_bytes, encoding="utf-8"):
    try:
        return file_bytes.decode(encoding)
    except Exception as e:
        print(f"[FILE ERROR] Cannot decode file: {e}")
        return None

async def handle_file_message(message, mode):
    file_bytes, filename = await extract_file_bytes(message)
    if not file_bytes:
        return None

    text = await read_text_file(file_bytes)
    if not text:
        await message.channel.send(f"⚠️ I cannot read `{filename}` as text.")
        return None

    # Build LLaMA prompt
    persona = PERSONAS.get(mode, PERSONAS["serious"])
    prompt = f"{persona}\nThe user uploaded a file `{filename}`. Content:\n{text}\n\nHelp the user based on this content."
    
    response = await call_groq(
        prompt=prompt,
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        temperature=0.7
    )

    if response:
        await send_human_reply(message.channel, response.strip())
        return response.strip()

    return "❌ Couldn't process the file."

# ---------------- MERMAID GENERATION ----------------
async def generate_mermaid(user_text: str) -> str:
    """
    Calls Meta-LLaMA to generate Mermaid diagram code from user text.
    Returns a string like "graph TD; A-->B;" or None if failed.
    """
    prompt = (
        "You are an assistant that converts user instructions into a MERMAID diagram.\n"
        "Always reply ONLY with valid Mermaid syntax. Do not add any explanation.\n"
        "User instruction:\n"
        f"{user_text}\n\n"
        "Mermaid code:"
    )

    try:
        resp = await call_groq(
            prompt=prompt,
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            temperature=0
        )
        mermaid_code = resp.strip()
        if mermaid_code:
            return mermaid_code
        return None
    except Exception as e:
        print(f"[MERMAID ERROR] {e}")
        return None

# ---------------- MERMAID TO URL ----------------
def mermaid_to_url(code: str) -> str:
    """
    Converts Mermaid code into a URL that renders the diagram as an image.
    Uses the official mermaid.ink service.
    """
    base = "https://mermaid.ink/img/"
    encoded = urllib.parse.quote(code)
    return f"{base}{encoded}"

# ---------------- CHESS UTILS ----------------

RESIGN_PHRASES = [
    "resign", "i resign",
    "give up", "i give up", "surrender", "i surrender",
    "forfeit", "i forfeit", "quit", "i quit",
    "done", "enough", "cant win", "can't win",
    "lost", "i lost", "i'm done", "im done"
]

CHESS_CHAT_KEYWORDS = [

    # --- Hints & move guidance ---
    "hint", "help", "assist", "suggest", "advice",
    "what should", "what do i play", "what now",
    "any ideas", "idea", "plan", "strategy",
    "next move", "best move", "recommend",
    "candidate move", "candidates",

    # --- Move quality & evaluation ---
    "good move", "bad move", "was that good", "was that bad",
    "mistake", "blunder", "inaccuracy",
    "did i blunder", "engine says",
    "is this winning", "is this losing",
    "am i better", "am i worse",
    "equal", "equality", "advantage", "disadvantage",
    "position", "evaluation", "eval",

    # --- Draws & game state ---
    "draw", "is this a draw", "drawn",
    "threefold", "repetition",
    "stalemate", "insufficient material",
    "50 move rule", "fifty move rule",
    "perpetual", "perpetual check",
    "dead position",

    # --- Analysis & explanation ---
    "analyze", "analysis", "explain",
    "why", "how", "what's the idea",
    "what is the point", "what does this do",
    "what am i missing", "thoughts",
    "breakdown", "line", "variation",
    "calculate", "calculation",

    # --- Learning & improvement ---
    "teach", "learn", "lesson", "coach",
    "how do i improve", "how to play",
    "beginner", "intermediate", "advanced",
    "tips", "principles", "fundamentals",
    "training", "practice", "study",
    "rating", "elo", "strength",

    # --- Openings & theory ---
    "opening", "opening name", "what opening",
    "is this an opening", "theory",
    "book move", "out of book",
    "prep", "preparation",
    "main line", "sideline",
    "gambit", "system", "setup",

    # --- Middlegame concepts ---
    "middlegame", "attack", "defense",
    "initiative", "tempo", "development",
    "space", "structure", "pawn structure",
    "weakness", "outpost", "open file",
    "king safety", "center",

    # --- Endgame concepts ---
    "endgame", "late game",
    "pawn ending", "rook ending",
    "bishop vs knight",
    "opposition", "zugzwang",
    "promotion", "passed pawn",

    # --- Threats & tactics ---
    "am i in trouble", "is this dangerous",
    "any threats", "what is he threatening",
    "is my king safe", "am i getting mated",
    "mate threat", "tactic", "trap",
    "fork", "pin", "skewer", "discovered attack",

    # --- Comparison & decision questions ---
    "or", "instead", "better than",
    "which is better", "this or that",
    "alternative", "other idea",

    # --- Players & levels (generic only) ---
    "players", "strong players",
    "gms", "grandmasters",
    "engine", "computer",
    "human move", "practical",

    # --- Post-game / casual ---
    "gg", "good game", "that was fun",
    "nice game", "rematch",
    "again", "another",
    "review", "analysis after",

    # --- Confusion / uncertainty ---
    "idk", "i don't know", "confused",
    "lost", "i'm stuck", "not sure",
    "help me understand",

    # --- General casual chat inside chessmode ---
    "lol", "lmao", "bruh", "bro",
    "haha", "rip", "damn",
    "oops", "my bad", "wow"
]

MOVE_REGEX = re.compile(
    r"""^(
        O-O(-O)? |
        [KQRBN]?[a-h]x?[a-h][1-8](=[QRBN])?[+#]? |
        [a-h][1-8][a-h][1-8][+#]?
    )$""",
    re.VERBOSE | re.IGNORECASE
)


def is_resign_message(text: str) -> bool:
    t = text.lower()
    return any(p in t for p in RESIGN_PHRASES)


def looks_like_chess_chat(text: str) -> bool:
    t = text.lower().strip()
    if any(k in t for k in CHESS_CHAT_KEYWORDS):
        return True
    if len(t.split()) > 4:
        return True
    return False

def normalize_move_input(board, move_input: str):
    raw = move_input.strip()
    if not raw:
        return None

    if is_resign_message(raw):
        return "resign"

    norm = (
        raw.replace("0-0-0", "O-O-O")
           .replace("0-0", "O-O")
           .replace("o-o-o", "O-O-O")
           .replace("o-o", "O-O")
    )

    legal_moves = list(board.legal_moves)

    # Pawn move like "e4"
    if len(norm) == 2 and norm[0].lower() in "abcdefgh" and norm[1] in "12345678":
        sq = chess.parse_square(norm.lower())
        matches = [m for m in legal_moves if m.to_square == sq]
        if len(matches) == 1:
            return board.san(matches[0])

    # Normalize piece letter
    if norm[0].lower() in "nbrqk":
        norm = norm[0].upper() + norm[1:]

    # SAN
    try:
        move = board.parse_san(norm)
        return board.san(move)
    except:
        pass

    # UCI
    try:
        move = chess.Move.from_uci(raw.lower())
        if move in legal_moves:
            return board.san(move)
    except:
        pass

    return None

# global (near other channel_* dicts)
channel_last_chess_result = {}

async def decide_response_type(user_text: str) -> str:
    """
    Returns either:
    - 'diagram'
    - 'text'
    """
    prompt = (
        "You are a classifier.\n"
        "Decide whether the user's message requires a DIAGRAM.\n"
        "A diagram is needed if visual structure helps.\n\n"
        "Reply with ONE WORD only:\n"
        "diagram or text\n\n"
        f"User message:\n{user_text}"
    )

    try:
        resp = await call_groq(
            prompt=prompt,
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            temperature=0
        )
        return resp.strip().lower()
    except:
        return "text"
    """
    Reads a Discord attachment and returns its content as a string.
    Handles text-based files only (txt, py, csv, json, etc.).
    Returns None if file is too big or not readable.
    """
    TEXT_EXTENSIONS = (".txt", ".py", ".csv", ".json", ".md", ".log")
    MAX_FILE_SIZE = 100_000  # 100 KB

    if not file.filename.lower().endswith(TEXT_EXTENSIONS):
        return None
    if file.size > MAX_FILE_SIZE:
        return f"[ERROR] File too large: {file.size} bytes (max {MAX_FILE_SIZE})"

    try:
        data = await file.read()
        return data.decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"[FILE READ ERROR] {e}")
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

    # Bot only responds in servers when pinged

    if not is_dm:
        if bot.user not in message.mentions:
            return

    # ---------------- IMAGE PROCESSING LOCK ----------------
    if message.channel.id in IMAGE_PROCESSING_CHANNELS:
        print("[LOCK] Ignoring message during image processing")
        return

    # Strip mention safely
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

    # ---------------- SAFE IMAGE CHECK ----------------
    has_image = False

    # attachments
    if any(a.content_type and a.content_type.startswith("image/") for a in message.attachments):
        has_image = True

    # embeds
    elif any((e.image and e.image.url) or (e.thumbnail and e.thumbnail.url) for e in message.embeds):
        has_image = True

    # image-urls only
    else:
        urls = re.findall(r"(https?://\S+)", message.content)
        img_exts = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff")
        if any(url.lower().endswith(img_exts) for url in urls):
            has_image = True

    if has_image:
        image_reply = await handle_image_message(message, mode)
        if image_reply is not None:
            await send_human_reply(message.channel, image_reply)
            return

    # ---------------- FILE UPLOAD PROCESSING ----------------
    has_file = bool(message.attachments)
    if has_file:
        file_reply = await handle_file_message(message, mode)
        if file_reply is not None:
            return
    
    # LLaMA ROUTER (TEXT vs DIAGRAM)
    decision = await decide_response_type(content)

    if decision == "diagram":
        await send_human_reply(message.channel, "🧠 Generating diagram...")

        mermaid_code = await generate_mermaid(content)
        if not mermaid_code:
            await send_human_reply(
                message.channel,
                "❌ I couldn't generate that diagram."
            )
            return

        await message.channel.send(mermaid_to_url(mermaid_code))
        return

    # ---------------- CHESS MODE ----------------
    if channel_chess.get(chan_id):
        board = chess_engine.get_board(chan_id)

        # -------- GAME OVER (ENGINE / POSITION) --------
        if board.is_game_over():
            result = board.result()
            if result == "1-0":
                channel_last_chess_result[chan_id] = "user"
                msg = "GG 😎 you won!"
            elif result == "0-1":
                channel_last_chess_result[chan_id] = "bot"
                msg = "GG 😄 I win!"
            else:
                channel_last_chess_result[chan_id] = "draw"
                msg = "GG 🤝 it’s a draw!"

            channel_chess[chan_id] = False
            await send_human_reply(message.channel, f"{msg} Wanna analyze or rematch?")
            return

        # -------- RESIGN --------
        if is_resign_message(content):
            if board.turn:
                channel_last_chess_result[chan_id] = "bot"
                msg = f"GG 😄 {message.author.display_name} resigned — I win ♟️"
            else:
                channel_last_chess_result[chan_id] = "user"
                msg = f"GG 😄 I resigned — you win ♟️"

            channel_chess[chan_id] = False
            await send_human_reply(message.channel, msg)
            return

        # -------- CHESS CHAT / COACH --------
        if looks_like_chess_chat(content):
            chess_prompt = (
                PERSONAS["funny"]
                + "\nYou are a strong chess player helping during a LIVE game.\n"
                + "Rules:\n"
                + "- Never claim a move was played unless it actually was\n"
                + "- Never invent engine lines or evaluations\n"
                + "- Explain plans, ideas, threats, and concepts\n"
                + "- If a hint is requested, suggest IDEAS not forced moves\n\n"
                + f"Current FEN:\n{board.fen()}\n\n"
                + f"User says:\n{content}\n\n"
                + "Reply:"
            )

            response = await call_groq(
                prompt=chess_prompt,
                model="llama-3.3-70b-versatile",
                temperature=0.6
            )

            await send_human_reply(message.channel, humanize_and_safeify(response))
            return

        # -------- PLAYER MOVE --------
        move_san = normalize_move_input(board, content)

        if move_san == "resign":
            channel_last_chess_result[chan_id] = "bot"
            channel_chess[chan_id] = False
            await send_human_reply(
                message.channel,
                f"GG 😄 {message.author.display_name} resigned — I win ♟️"
            )
            return

        if not move_san:
            await send_human_reply(
                message.channel,
                "🤔 That doesn’t look like a legal move. Want a hint?"
            )
            return

        try:
            player_move = board.parse_san(move_san)
        except:
            await send_human_reply(
                message.channel,
                "⚠️ That move isn’t legal in this position."
            )
            return

        board.push(player_move)

        if board.is_checkmate():
            channel_last_chess_result[chan_id] = "user"
            channel_chess[chan_id] = False
            await send_human_reply(
                message.channel,
                f"😮 Checkmate! YOU WIN ({move_san})"
            )
            return

        # -------- ENGINE MOVE --------
        best = chess_engine.get_best_move(chan_id)
        if not best:
            channel_last_chess_result[chan_id] = "draw"
            channel_chess[chan_id] = False
            await send_human_reply(message.channel, "🤝 No legal moves — draw!")
            return

        engine_move = board.parse_uci(best["uci"])
        board.push(engine_move)

        await send_human_reply(
            message.channel,
            f"My move: `{best['uci']}` / **{best['san']}**"
        )

        if board.is_checkmate():
            channel_last_chess_result[chan_id] = "bot"
            channel_chess[chan_id] = False
            await send_human_reply(
                message.channel,
                f"💀 Checkmate — I win ({best['san']})"
            )

        return

    # ---------------- ROAST MODE ----------------
    if mode == "roast":
        await handle_roast_mode(chan_id, message, content)
        return

    # ---------------- GENERAL CHAT ----------------
    asyncio.create_task(generate_and_reply(chan_id, message, content, mode))

    # ---------------- SAVE USER MESSAGE ----------------
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
