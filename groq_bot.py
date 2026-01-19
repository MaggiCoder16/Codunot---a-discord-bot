import os
import io
import asyncio
import random
import re
import numpy as np
from datetime import datetime, timedelta, timezone, date
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
from typing import Optional

from usage_manager import (
    load_usage,
    save_usage,
    check_limit,
    consume,
    check_total_limit,
    consume_total
)

load_dotenv()
load_usage()
print("[USAGE] Loaded daily and total counts")

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

# ---------------- DAILY LIMITS ----------------
LIMITS = {
    "basic": {
        "messages": 50,
        "images": 7,
        "files": 5
    },
    "premium": {
        "messages": 100,
        "images": 10,
        "files": 10
    },
    "gold": {
        "messages": float("inf"),
        "images": float("inf"),
        "files": float("inf")
    }
}

# ---------------- TOTAL LIMITS (LIFETIME) ----------------
TOTAL_LIMITS = {
    "basic": {
        "images": 30,
        "files": 20
    },
    "premium": {
        "images": 50,
        "files": 35
    },
    "gold": {
        "images": float("inf"),
        "files": float("inf")
    }
}

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
channel_usage = {}
total_image_count = {}
total_file_count = {}

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

def load_channels(path):
    if not os.path.exists(path):
        return set()
    with open(path, "r") as f:
        return {line.strip() for line in f if line.strip()}

PREMIUM_CHANNELS = load_channels("tiers_premium.txt")
GOLD_CHANNELS = load_channels("tiers_gold.txt")

def get_channel_tier(chan_id: str) -> str:
    if chan_id in GOLD_CHANNELS:
        return "gold"
    if chan_id in PREMIUM_CHANNELS:
        return "premium"
    return "basic"

def get_usage(chan_id):
    today = date.today().isoformat()

    usage = channel_usage.setdefault(chan_id, {
        "day": today,
        "messages": 0,
        "images": 0,
        "files": 0
    })

    # reset daily
    if usage["day"] != today:
        usage.update({
            "day": today,
            "messages": 0,
            "images": 0,
            "files": 0
        })

    return usage

def check_limit(chan_id, kind: str) -> bool:
    tier = get_channel_tier(chan_id)
    limits = LIMITS[tier]
    usage = get_usage(chan_id)

    return usage[kind] < limits[kind]

def consume(chan_id, kind: str):
    usage = get_usage(chan_id)
    usage[kind] += 1

async def deny_limit(message, kind):
    tier = get_channel_tier(str(message.channel.id))
    await message.reply(
        f"🚫 **{tier.upper()}** limit hit for `{kind}` today.\n"
        "Contact aarav_2022 for an upgrade."
    )

def check_total_limit(chan_id: str, kind: str) -> bool:
    tier = get_channel_tier(chan_id)
    limit = TOTAL_LIMITS[tier][kind]

    if limit == float("inf"):
        return True

    store = total_image_count if kind == "images" else total_file_count
    used = store.get(chan_id, 0)

    return used < limit

def consume_total(chan_id: str, kind: str):
    store = total_image_count if kind == "images" else total_file_count
    store[chan_id] = store.get(chan_id, 0) + 1

async def autosave_usage():
    while True:
        save_usage()
        await asyncio.sleep(60)

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
        reply = await call_groq_vision(
            prompt=vision_prompt,
            image_bytes=image_bytes,
            image_mime="image/png"
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
    prompt = (
        build_general_prompt(chan_id, mode, message, include_last_image=False)
        + f"\nUser says:\n{content}\n\nReply:"
    )

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

# ---------------- IMAGE EXTRACTION ----------------
async def extract_image_bytes(message) -> bytes | None:
    """
    Extract raw image bytes from a Discord message.
    Supports attachments and embeds.
    """

    # Attachments
    for attachment in message.attachments:
        if attachment.content_type and attachment.content_type.startswith("image/"):
            try:
                return await attachment.read()
            except Exception as e:
                print(f"[IMAGE ERROR] Failed to read attachment: {e}")
                return None

    # Embeds (image previews, link embeds)
    for embed in message.embeds:
        url = None
        if embed.image and embed.image.url:
            url = embed.image.url
        elif embed.thumbnail and embed.thumbnail.url:
            url = embed.thumbnail.url

        if url:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            return await resp.read()
            except Exception as e:
                print(f"[IMAGE ERROR] Failed to download embed image: {e}")
                return None

    return None

async def handle_image_message(message, mode):
    """
    Handles images sent by the user.
    Sends the image directly to the Groq vision model.
    Returns the model's response as a string, or a fallback message.
    """

    # Extract image bytes
    image_bytes = await extract_image_bytes(message)
    if not image_bytes:
        print("[VISION ERROR] No image found in message")
        return None

    chan_id = str(message.channel.id)
    channel_last_image_bytes[chan_id] = image_bytes

    channel_id = message.channel.id
    IMAGE_PROCESSING_CHANNELS.add(channel_id)

    try:
        persona = PERSONAS.get(mode, PERSONAS["serious"])
        prompt = (
            persona + "\n"
            "You are Codunot, a helpful assistant. "
            "The user sent the image attached to this message. "
            "Explain, describe, or answer based on the image content only. "
            "Keep replies short, clear, and helpful.\n"
            f"User message (optional context):\n{message.content}\n\n"
            "Reply concisely as Codunot:"
        )

        print(f"[VISION PROMPT] ({channel_id}) {prompt}")

        # Call the unified Groq client
        response = await call_groq(
            prompt=prompt,
            image_bytes=image_bytes,
            temperature=0.7
        )

        if response:
            print(f"[VISION MODEL RESPONSE] {response}")
            return response.strip()

        return "🤔 I can't interpret this image right now, try again later."

    except Exception as e:
        print(f"[VISION ERROR] {e}")
        return "🤔 Something went wrong while analyzing the image."

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
    chan_id_str = str(message.channel.id)

    # Check daily limit
    if not check_limit(chan_id_str, "files"):
        await deny_limit(message, "files")
        return None

    # Check total lifetime limit
    if not check_total_limit(chan_id_str, "files"):
        await message.reply(
            "🚫 You've hit your **total file upload limit**.\n"
            "Contact aarav_2022 for an upgrade."
        )
        return None

    # Extract file bytes
    file_bytes, filename = await extract_file_bytes(message)
    if not file_bytes:
        return None

    filename_lower = filename.lower()
    text = None

    try:
        if filename_lower.endswith(".txt"):
            text = await read_text_file(file_bytes)

        elif filename_lower.endswith(".pdf"):
            try:
                with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                    pages_text = [page.extract_text() or "" for page in pdf.pages]
                    text = "\n".join(pages_text).strip()
            except Exception as e:
                print(f"[PDF ERROR] {e}")
                text = None

        elif filename_lower.endswith(".docx"):
            doc = Document(io.BytesIO(file_bytes))
            text = "\n".join(p.text for p in doc.paragraphs).strip()

        else:
            await message.channel.send(
                f"⚠️ I cannot read `{filename}` (unsupported file type)."
            )
            return None

    except Exception as e:
        print(f"[FILE ERROR] Failed to read {filename}: {e}")
        await message.channel.send(
            f"⚠️ I cannot read `{filename}` as a file."
        )
        return None

    if not text:
        await message.channel.send(
            f"⚠️ `{filename}` appears to have no readable text."
        )
        return None

    # Build prompt
    persona = PERSONAS.get(mode, PERSONAS["serious"])
    prompt = (
        f"{persona}\n"
        f"The user uploaded a file `{filename}`. Content:\n{text}\n\n"
        "Help the user based on this content."
    )

    # Call Groq and reply
    try:
        response = await call_groq_with_health(
            prompt=prompt,
            temperature=0.7,
            mode=mode
        )
        if response:
            await send_human_reply(message.channel, response.strip())

            # Update counts
            consume(chan_id_str, "files")        # daily
            consume_total(chan_id_str, "files")  # total
            save_usage()  # save after consuming

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

async def boost_image_prompt(user_prompt: str) -> str:
    """
    Uses LLaMA to rewrite a user image idea into a strong image-generation prompt.
    Falls back to original prompt if boosting fails.
    """

    boost_instruction = (
        "You are a professional image prompt engineer.\n\n"
        "Rewrite the user's idea into a single, high-quality image generation prompt.\n\n"
        "STRICT RULES:\n"
        "- Preserve the user's original idea exactly (no new subjects or story changes)\n"
        "- If a named person, character, place, or object is mentioned, you MAY clarify it "
        "with widely-known, neutral descriptors (e.g., role or visual identity)\n"
        "- Do NOT invent unknown facts or niche details\n"
        "- Expand ONLY with visual details: appearance, clothing, setting, lighting, mood, composition\n"
        "- Use concrete, vivid language suitable for AI image models\n"
        "- Do NOT mention artist names, camera brands, or model names\n"
        "- Do NOT include explanations or formatting\n"
        "- Output ONE paragraph only, under 80 words\n\n"
        "User idea:\n"
        f"{user_prompt}"
    )

    try:
        boosted = await call_groq(
            prompt=boost_instruction,
            model="llama-3.3-70b-versatile",
            temperature=0.6
        )

        if boosted:
            return boosted.strip()

    except Exception as e:
        print("[PROMPT BOOST ERROR]", e)

    # Fallback — NEVER break image generation
    return user_prompt

def build_vision_followup_prompt(message):
    return (
        "You are Codunot.\n"
        "An image was shown earlier in this channel.\n\n"

        "RULES:\n"
        "- ONLY talk about the image if the user's message is clearly referring to it.\n"
        "- If the user asks something unrelated (greetings, bot info, creator, general chat, etc.), "
        "IGNORE the image completely and reply normally.\n"
        "- If the user is unclear, ask ONE short clarification question.\n\n"

        f"User message:\n{message.content}"
    )
        
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

def clean_chess_input(content: str, bot_id: int) -> str:
    content = content.strip()

    # Remove bot mentions
    content = content.replace(f"<@{bot_id}>", "")
    content = content.replace(f"<@!{bot_id}>", "")

    return content.strip()

def normalize_move_input(board, text: str):
    move = text.strip()

    if not move:
        return None

    if move.lower() in ["resign", "i resign", "quit"]:
        return "resign"

    move = move.replace("0-0-0", "O-O-O").replace("0-0", "O-O")

    # pawn move like e4
    if len(move) == 2 and move[0].islower() and move[1].isdigit():
        return move

    # piece move: bc4 → Bc4
    if move[0].isalpha():
        return move[0].upper() + move[1:]

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

    # ---------------- LAST IMAGE FOLLOW-UP ----------------
    if (
        chan_id in channel_last_image_bytes
        and not message.attachments
        and not message.embeds
    ):
        response = await call_groq(
            prompt=build_vision_followup_prompt(message),
            image_bytes=channel_last_image_bytes[chan_id],
            temperature=0.7
        )
        if response:
            await message.reply(response)
            return


	
    # ---------------- IMAGE GENERATION ----------------
    if message.id in processed_image_messages:
        return

    processed_image_messages.add(message.id)

    # Decide if user is explicitly requesting an image
    visual_type = await decide_visual_type(content, chan_id)

    # Only proceed if AI thinks it's an image request
if visual_type == "fun":
        await send_human_reply(message.channel, "🖼️ Generating image... please wait.")

        chan_id_str = str(message.channel.id)

        # Daily limit
        if not check_limit(chan_id_str, "images"):
            await deny_limit(message, "images")
            return

        # Total lifetime limit
        if not check_total_limit(chan_id_str, "images"):
            await message.reply(
                "🚫 You've hit your **total image generation limit**.\n"
                "Contact aarav_2022 for an upgrade."
            )
            return

        # Decide prompt
        if await is_codunot_self_image(content):
            image_prompt = CODUNOT_SELF_IMAGE_PROMPT
        else:
            image_prompt = await boost_image_prompt(content)

        print(f"[IMAGE PROMPT BOOSTED] ({chan_id}) {image_prompt}")

        try:
            # Generate image
            aspect = "16:9"
            image_bytes = await generate_image(image_prompt, aspect_ratio=aspect, steps=4)

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

            # Save last image
            channel_last_image_bytes[chan_id] = image_bytes

            # Send image
            file = discord.File(io.BytesIO(image_bytes), filename="image.png")
            await message.channel.send(file=file)

            # Update usage counts once
            consume(chan_id_str, "images")       # daily
            consume_total(chan_id_str, "images") # total
            save_usage()

        except Exception as e:
            print("[IMAGE GEN ERROR]", e)
            await send_human_reply(
                message.channel,
                "🤔 Couldn't generate image right now. Please try again later."
            )

# ---------------- CHESS MODE ----------------
if channel_chess.get(chan_id):
    board = chess_engine.get_board(chan_id)

    # -------- GAME OVER --------
    if board.is_game_over():
        result = board.result()
        if result == "1-0":
            msg = "GG 😎 you won!"
        elif result == "0-1":
            msg = "GG 😄 I win!"
        else:
            msg = "GG 🤝 it’s a draw!"

        channel_chess[chan_id] = False
        await send_human_reply(message.channel, f"{msg} Wanna analyze or rematch?")
        return

    # -------- RESIGN --------
    cleaned = clean_chess_input(content, bot.user.id)
    if cleaned.lower() in ["resign", "i resign", "quit"]:
        channel_chess[chan_id] = False
        await send_human_reply(
            message.channel,
            f"GG 😄 {message.author.display_name} resigned — I win ♟️"
        )
        return

    # -------- CHESS CHAT --------
    if looks_like_chess_chat(cleaned):
        chess_prompt = (
            PERSONAS["funny"]
            + "\nYou are a strong chess player helping during a LIVE game.\n"
            + "Rules:\n"
            + "- Never invent engine lines\n"
            + "- Explain ideas, not forced moves\n\n"
            + f"Current FEN:\n{board.fen()}\n\n"
            + f"User says:\n{cleaned}\n\nReply:"
        )

        response = await call_groq(
            prompt=chess_prompt,
            model="llama-3.3-70b-versatile",
            temperature=0.6
        )

        await send_human_reply(message.channel, humanize_and_safeify(response))
        return

    # -------- PLAYER MOVE --------
    move_san = normalize_move_input(board, cleaned)

    if not move_san:
        await send_human_reply(
            message.channel,
            "🤔 That doesn’t look like a legal move. Try something like `e4` or `Bc4`."
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
        channel_chess[chan_id] = False
        await send_human_reply(
            message.channel,
            f"😮 Checkmate! YOU WIN ({move_san})"
        )
        return

    # -------- ENGINE MOVE --------
    best = chess_engine.get_best_move(chan_id)

    if not best:
        await send_human_reply(
            message.channel,
            "⚠️ Engine hiccup — your turn again!"
        )
        return

    engine_move = board.parse_uci(best["uci"])
    board.push(engine_move)

    await send_human_reply(
        message.channel,
        f"My move: `{best['san']}`"
    )

    if board.is_checkmate():
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
	chan_id = str(message.channel.id)

    if not check_limit(chan_id, "messages"):
        await deny_limit(message, "messages")
        return

    consume(chan_id, "messages")
    asyncio.create_task(generate_and_reply(chan_id, message, content, mode))

    # ---------------- SAVE USER MESSAGE ----------------
    channel_memory[chan_id].append(f"{message.author.display_name}: {content}")

# ---------------- EVENTS ----------------
@bot.event
async def on_ready():
    print(f"{BOT_NAME} is ready!")
    asyncio.create_task(process_queue())
    asyncio.create_task(autosave_usage())

# ---------------- RUN ----------------
def run():
    bot.run(DISCORD_TOKEN)

if __name__ == "__main__":
    run()
