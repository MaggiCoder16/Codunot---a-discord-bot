import os
import io
import asyncio
import random
import re
import numpy as np
from datetime import datetime, timedelta, timezone
from collections import deque
import urllib.parse

import discord
from discord import Message
from dotenv import load_dotenv

from memory import MemoryManager
from humanizer import maybe_typo
from deAPI_client_image import generate_image
from bot_chess import OnlineChessEngine
from groq_client import call_groq
from slang_normalizer import apply_slang_map

import chess
import aiohttp
import base64
from paddleocr import PaddleOCR
from PIL import Image
from typing import Optional

load_dotenv()

# ---------------- OCR ENGINE ----------------
ocr_engine = PaddleOCR(
    use_textline_orientation=True,
    lang="en"
)

# ---------------- CONFIG ----------------
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
BOT_NAME = os.getenv("BOT_NAME", "Codunot")
OWNER_IDS = [
    1220934047794987048,
    1443444307670335600
]
MAX_MEMORY = 45
RATE_LIMIT = 900
MAX_IMAGE_BYTES = 2_000_000  # 2 MB

# ---------------- CLIENT ----------------
intents = discord.Intents.all()
intents.message_content = True
bot = discord.Client(intents=intents)
memory = MemoryManager(limit=60, file_path="codunot_memory.json")
chess_engine = OnlineChessEngine()
IMAGE_PROCESSING_CHANNELS = set()
processed_image_messages = set()


# ---------------- STATES ----------------
message_queue = asyncio.Queue()
channel_modes = {}
channel_mutes = {}
channel_chess = {}
channel_images = {}
channel_memory = {}
rate_buckets = {}
channel_last_image_bytes = {}

# ---------------- MODELS ----------------
SCOUT_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"  # seriousmode
VERSATILE_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"  # fun/roast

SCOUT_COOLDOWN_UNTIL = None
SCOUT_COOLDOWN_DURATION = timedelta(hours=1)

# ---------------- MODEL HEALTH ----------------
async def call_groq_with_health(prompt, temperature=0.7, mode: str = ""):
    """
    Handles calling Groq with model selection and overload handling.
    mode: 'serious', 'funny', 'roast' (or empty string)
    """
    model = pick_model(mode)

    try:
        return await call_groq(
            prompt=prompt,
            model=model,
            temperature=temperature
        )

    except Exception as e:
        msg = str(e)

        # Only handle Maverick overload (for seriousmode)
        if model == SCOUT_MODEL and ("503" in msg or "over capacity" in msg):
            global SCOUT_COOLDOWN_UNTIL
            SCOUT_COOLDOWN_UNTIL = datetime.utcnow() + SCOUT_COOLDOWN_DURATION
            print(
                f"[GROQ] Maverick overloaded — "
                f"cooling down until {SCOUT_COOLDOWN_UNTIL.isoformat()}"
            )
            # Retry with Versatile for fallback
            return await call_groq(
                prompt=prompt,
                model=VERSATILE_MODEL,
                temperature=temperature
            )

        raise e

# ---------------- MODEL PICKER ----------------
def pick_model(mode: str = ""):
    """
    Returns the model to use based on mode:
    - seriousmode -> Maverick (SCOUT_MODEL)
    - funmode / roastmode -> Versatile (VERSATILE_MODEL)
    """
    mode = mode.lower()

    if mode == "serious":
        return SCOUT_MODEL

    # funny / roast / default
    return VERSATILE_MODEL

# ---------------- CODUNOT SELF IMAGE PROMPT ----------------
CODUNOT_SELF_IMAGE_PROMPT = (
    "Cute chibi robot avatar of Codunot, a friendly AI assistant, "
    "glossy orange and yellow robot body, rounded head with a dark face screen "
    "and glowing yellow eyes, small antenna on top, waving hand, "
    "cartoon mascot style, clean digital illustration, "
    "dark tech background with warm glow, "
    "robot only, no humans, no realistic human features."
)
    
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
        "Never say you can't generate images."
        "If the user says bye, gtg, l8r, see ya, or any goodbye, just reply with a short, friendly farewell (like 'L8r! 👋'). "
    ),

    "serious": (
        "You are Codunot, a highly knowledgeable and helpful assistant. "
        "Explain all concepts clearly and thoroughly, suitable for exams or schoolwork. "
        "Write chemical formulas and equations in plain text (e.g., H2O, CO2, NaCl). "
        "You may use natural language explanations for math, no need for LaTeX or $...$. "
        "Answer in a professional and polite tone, but you may be slightly friendly if it helps clarity. "
        "Avoid slang or emojis in serious mode. "
        "Do not prefix your answers with your name. "
        "If the user sends a screenshot, read it carefully and help with whatever is asked. "
        "Always respect the username provided and spell it correctly. "
        "Do not refuse to generate images if requested. "
        "If, and only if the user asks about your creator or who made you, reply exactly: "
        "'You asked about my creator: I was developed by @aarav_2022 on Discord "
        "(User ID: 1220934047794987048). For further information, please contact him directly.'"
        "Never randomly say about your creator."
        "ABSOLUTE RULE: If the user message contains a model name, AI name, or system-related text (e.g. llama, model, groq, scout, maverick), DO NOT mention your creator unless explicitly asked \"who made you\"."
        "CRITICAL: Check all arithmetic step by step. Do not hallucinate numbers. Only provide correct calculations. Do not forget to add operations, like '*', '/' etc."
        "Dont give big answers for short questions. Give proper links, like rankings, and answers, like best chess player is magnus carlsen, dont say anything like 'Check fide website, etc.'"
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
        "You CANNOT generate images. If the user asks you to generate one, roast them."
        "If the user asks you to change languages, or roast in a specific language, dont roast them in that message-roast in the language they mention."
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

def build_general_prompt(chan_id, mode, message, include_last_image=False):
    mem = channel_memory.get(chan_id, deque())
    history_text = "\n".join(mem)

    # Include info about the last image
    last_img_info = ""
    if include_last_image:
        last_img_info = "\nNote: The user has previously requested an image in this conversation."

    persona_text = PERSONAS.get(mode, PERSONAS["funny"])
    return f"{persona_text}\n\nRecent chat:\n{history_text}{last_img_info}\n\nReply as Codunot:"

async def handle_last_generated_image(chan_id, message, content):
    image_bytes = channel_last_image_bytes.get(chan_id)
    if not image_bytes:
        return False

    vision_prompt = (
        "You are Codunot.\n"
        "You generated the image shown to the user.\n\n"
        f"User message:\n{content}\n\n"
        "Rules:\n"
        "- NEVER deny generating the image\n"
        "- If the user dislikes it, apologize briefly and offer to fix or regenerate\n"
        "- If the user is confused, explain what the image shows\n"
        "- If the user wants changes, ask what to modify or describe the changes\n"
        "- Keep replies short and natural\n"
    )

    try:
        reply = await call_groq(
            prompt=vision_prompt,
            image_bytes=image_bytes,
            temperature=0.7
        )

        if reply:
            await send_human_reply(message.channel, reply)
            return True

        return False

    except Exception as e:
        print("[LAST IMAGE HANDLER ERROR]", e)
        return False

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

async def generate_and_reply(chan_id, message, content, mode):
    image_intent = "NEW"
    guild_id = message.guild.id if message.guild else None
    if guild_id is not None and not await can_send_in_guild(guild_id):
        return

    handled = await handle_last_generated_image(chan_id, message, content)
    if handled:
        return
			
    # ---------------- BUILD PROMPT ----------------
    prompt = build_general_prompt(chan_id, mode, message, include_last_image=False)

    # ---------------- GENERATE RESPONSE ----------------
    try:
        response = await call_groq_with_health(prompt, temperature=0.7, mode=mode)
    except Exception as e:
        print(f"[API ERROR] {e}")
        response = None

    # ---------------- HUMANIZE / SAFEIFY ----------------
    if response:
        if mode == "funny":
            reply = humanize_and_safeify(response)
        else:  # serious or roast handled separately
            reply = response.strip()
            if reply and not reply.endswith(('.', '!', '?')):
                reply += '.'
    else:
        reply = choose_fallback()

    # ---------------- SEND REPLY ----------------
    await send_human_reply(message.channel, reply)

    # ---------------- SAVE TO MEMORY ----------------
    channel_memory.setdefault(chan_id, deque(maxlen=MAX_MEMORY))
    channel_memory[chan_id].append(f"{BOT_NAME}: {reply}")
    memory.add_message(chan_id, BOT_NAME, reply)
    memory.persist()

# ---------------- IMAGE HANDLING ----------------

async def ocr_image(image_bytes: bytes) -> str:
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img_np = np.array(img)

        result = ocr_engine.ocr(img_np, cls=True)

        if not result:
            return ""

        lines = []
        for line in result:
            for word_info in line:
                text = word_info[1][0]
                confidence = word_info[1][1]
                if confidence >= 0.3:
                    lines.append(text)

        return "\n".join(lines).strip()

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
                "As there is no text, tell the user that you are an AI model that can only understand images with text, and you cannot find any text in that image."
            )

        response = await call_groq_with_health(
            prompt=prompt,
            temperature=0.7,
            mode=mode
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

import pdfplumber
from docx import Document
from pdf2image import convert_from_bytes

async def handle_file_message(message, mode):
    file_bytes, filename = await extract_file_bytes(message)
    if not file_bytes:
        return None

    filename_lower = filename.lower()
    text = None

    try:
        if filename_lower.endswith(".txt"):
            text = await read_text_file(file_bytes)

        elif filename_lower.endswith(".pdf"):
            # Try text extraction
            try:
                with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                    pages_text = [page.extract_text() or "" for page in pdf.pages]
                    text = "\n".join(pages_text).strip()
            except Exception as e:
                print(f"[PDF ERROR] {e}")
                text = None

            # OCR fallback
            if not text or not text.strip():
                pages = convert_from_bytes(file_bytes)
                ocr_text = ""
                for img in pages:
                    img_bytes = io.BytesIO()
                    img.save(img_bytes, format="PNG")
                    ocr_text += await ocr_image(img_bytes.getvalue()) + "\n"
                text = ocr_text.strip()

        elif filename_lower.endswith(".docx"):
            doc = Document(io.BytesIO(file_bytes))
            text = "\n".join(p.text for p in doc.paragraphs).strip()

        else:
            await message.channel.send(f"⚠️ I cannot read `{filename}` (unsupported file type).")
            return None

    except Exception as e:
        print(f"[FILE ERROR] Failed to read {filename}: {e}")
        await message.channel.send(f"⚠️ I cannot read `{filename}` as a file.")
        return None

    if not text:
        await message.channel.send(f"⚠️ `{filename}` appears to have no readable text.")
        return None

    persona = PERSONAS.get(mode, PERSONAS["serious"])
    prompt = f"{persona}\nThe user uploaded a file `{filename}`. Content:\n{text}\n\nHelp the user based on this content."

    try:
        response = await call_groq_with_health(
            prompt=prompt,
            temperature=0.7,
            mode=mode
        )
        if response:
            await send_human_reply(message.channel, response.strip())
            return response.strip()
    except Exception as e:
        print(f"[FILE RESPONSE ERROR] {e}")

    return "❌ Couldn't process the file."

# ---------------- IMAGE TYPE DETECTION ----------------

async def decide_visual_type(user_text: str, chan_id: str) -> str:
    """
    Determines if the user is explicitly requesting an image (fun/diagram) or just text.
    Includes last 4 messages for context.
    """
    recent_messages = channel_memory.get(chan_id, [])
    recent_context = "\n".join(list(recent_messages)[-4:]) if recent_messages else ""

    prompt = (
        "You are a very strict intent classifier.\n\n"
        "Determine if the user is explicitly asking to generate or create an image.\n\n"
        "Return ONE WORD ONLY:\n"
        "- fun → if the user clearly asks to generate or create an image, picture, or visual\n"
        "- text → everything else (including talking about images, referencing images, or game inputs)\n\n"
        "IMPORTANT:\n"
        "- Simply mentioning 'image' or 'picture' is NOT enough.\n"
        "- Talking about existing images is NOT a generation request.\n"
        "- Game inputs or guesses are ALWAYS text.\n"
        "- The user must explicitly ask to generate, create, draw, or produce an image.\n\n"
		"- MEMES ALWAYS GO IN TEXT."
        "Recent conversation context:\n"
        f"{recent_context}\n\n"
        "Current user message:\n"
        f"{user_text}"
    )

    feedback = await call_groq_with_health(prompt, temperature=0, mode="serious")
    result = feedback.strip().lower()
    return "fun" if result == "fun" else "text"

# ---------------- DETECT IF USER IS ASKING CODUNOT FOR IT'S OWN IMAGE ----------------

async def is_codunot_self_image(user_text: str) -> bool:
    prompt = (
        "Answer only YES or NO.\n\n"
        "Determine if the user is explicitly asking for an image of Codunot itself "
        "(the AI assistant/bot), not any other image or concept.\n"
        "Do NOT say YES for vague or generic requests such as 'can you generate images?', "
        "'make a picture', or any request that does not specifically mention Codunot or itself.\n"
        "Only respond YES if the message clearly mentions Codunot, yourself, or you, "
        "in combination with words like image, picture, drawing, or avatar.\n"
        "Otherwise, respond NO.\n\n"
        f"User message:\n{user_text}"
    )

    try:
        resp = await call_groq_with_health(prompt, temperature=0)
        return resp.strip().lower() == "yes"
    except:
        return False
        
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
    if message.author.id in OWNER_IDS:
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
    if content_lower.startswith("!funmode"):
        channel_modes[chan_id] = "funny"
        memory.save_channel_mode(chan_id, "funny")
        if channel_chess.get(chan_id):
            channel_chess[chan_id] = False
            await send_human_reply(message.channel, "😎 Fun mode activated! ♟️ Chess mode ended.")
        else:
            await send_human_reply(message.channel, "😎 Fun mode activated!")
        return

    if content_lower.startswith("!seriousmode"):
        channel_modes[chan_id] = "serious"
        memory.save_channel_mode(chan_id, "serious")
        if channel_chess.get(chan_id):
            channel_chess[chan_id] = False
            await send_human_reply(message.channel, "🤓 Serious mode ON. ♟️ Chess mode ended.")
        else:
            await send_human_reply(message.channel, "🤓 Serious mode ON")
        return

    if content_lower.startswith("!roastmode"):
        channel_modes[chan_id] = "roast"
        memory.save_channel_mode(chan_id, "roast")
        if channel_chess.get(chan_id):
            channel_chess[chan_id] = False
            await send_human_reply(message.channel, "🔥 ROAST MODE ACTIVATED. ♟️ Chess mode ended.")
        else:
            await send_human_reply(message.channel, "🔥 ROAST MODE ACTIVATED")
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

    # ---------------- IMAGE GENERATION ----------------
    if message.id in processed_image_messages:
        return

    processed_image_messages.add(message.id)

    # Decide if user is explicitly requesting an image
    visual_type = await decide_visual_type(content, chan_id)

    # Only proceed if AI thinks it's an image request
    if visual_type == "fun":
        await send_human_reply(message.channel, "🖼️ Generating image... please wait for some time.")

        # Handle Codunot self-image request
        if await is_codunot_self_image(content):
            image_prompt = CODUNOT_SELF_IMAGE_PROMPT
        else:
            image_prompt = content

        try:
            # Set fixed aspect ratio
            aspect = "16:9"

            # Generate image
            image_bytes = await generate_image(image_prompt, aspect_ratio=aspect, steps=4)
            channel_last_image_bytes[chan_id] = image_bytes

            # Resize if too large
            MAX_BYTES = 5_000_000
            if len(image_bytes) > MAX_BYTES:
                img = Image.open(io.BytesIO(image_bytes))
                scale = (MAX_BYTES / len(image_bytes)) ** 0.5
                img = img.resize(
                    (int(img.width * scale), int(img.height * scale)),
                    Image.ANTIALIAS
                )
                out = io.BytesIO()
                img.save(out, format="PNG")
                image_bytes = out.getvalue()

            # Send image
            file = discord.File(io.BytesIO(image_bytes), filename="image.png")
            await message.channel.send(file=file)
            return

        except Exception as e:
            print("[Codunot ERROR]", e)
            await send_human_reply(
                message.channel,
                "Couldn't generate image right now. Please try again later."
            )

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
