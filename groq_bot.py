import os
import io
import asyncio
import atexit
import aiohttp
import random
import re
import numpy as np
import time
from datetime import datetime, timedelta, timezone, date
from collections import deque
import urllib.parse

import discord
from discord import Message
from discord.ext import commands
from dotenv import load_dotenv

from memory import MemoryManager
from humanizer import maybe_typo
from deAPI_client_image import generate_image
from deAPI_client_image_edit import edit_image
from deAPI_client_text2vid import text_to_video_512
from deAPI_client_text2speech import text_to_speech, TextToSpeechError
from bot_chess import OnlineChessEngine
from groq_client import call_groq
from slang_normalizer import apply_slang_map
from PIL import Image

import chess
import base64
from typing import Optional
from topgg_utils import has_voted
import json

from usage_manager import (
    check_limit,
    check_total_limit,
    consume,
    consume_total,
    deny_limit,
    load_usage,
    save_usage,
    autosave_usage,
)

load_dotenv()
load_usage()

# ---------------- CONFIG ----------------
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
BOT_NAME = os.getenv("BOT_NAME", "Codunot")
TOPGG_TOKEN = os.getenv("TOPGG_TOKEN")
OWNER_IDS = {int(os.environ.get("OWNER_ID", 0))}
VOTE_DURATION = 12 * 60 * 60
MAX_MEMORY = 45
RATE_LIMIT = 30
MAX_IMAGE_BYTES = 2_000_000  # 2 MB
MAX_TTS_LENGTH = 150
VOTE_FILE = "vote_unlocks.json"

# ---------------- CLIENT ----------------
intents = discord.Intents.all()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents, owner_ids=set(OWNER_IDS))

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
user_vote_unlocks = {
}
channel_last_image_bytes = {}
channel_recent_images = set()

# ---------------- COMMANDS ----------------
@bot.command(name="codunot_help")
async def help_command(ctx: commands.Context):
    """
    Sends a help embed describing Codunot's modes and bonus powers.
    """
    embed = discord.Embed(
        title="🤖 Codunot Help",
        description="Here's what I can do and how to use me!",
        color=0xFFA500  # orange color
    )

    embed.add_field(
        name="🟢 Fun Mode",
        value="`!funmode` — jokes, memes & chill vibes 😎",
        inline=False
    )
    embed.add_field(
        name="🔥 Roast Mode",
        value="`!roastmode` — playful burns for anyone 😈",
        inline=False
    )
    embed.add_field(
        name="📘 Serious Mode",
        value="`!seriousmode` — clean, fact-based help 📚",
        inline=False
    )
    embed.add_field(
        name="♟️ Chess Mode",
        value="`!chessmode` — play chess with me ♟️",
        inline=False
    )
    embed.add_field(
        name="✨ Bonus Powers",
        value=(
            "📄 Read & summarize files\n"
            "🖼️ See and understand images\n"
            "🎨 Generate & edit images\n"
            "🎬 Generate videos\n"
            "🔊 Text-to-speech audio"
        ),
        inline=False
    )
    embed.set_footer(text="Tip: In servers, always remember to ping me using @Codunot 'your text'. This is not required in DMs.")

    await ctx.send(embed=embed)

@bot.command(name="funmode")
async def funmode(ctx: commands.Context):
    chan_id = (
        f"dm_{ctx.author.id}"
        if isinstance(ctx.channel, discord.DMChannel)
        else str(ctx.channel.id)
    )

    channel_modes[chan_id] = "funny"
    memory.save_channel_mode(chan_id, "funny")
    channel_chess[chan_id] = False

    await ctx.send("😎 Fun mode activated!")


@bot.command(name="seriousmode")
async def seriousmode(ctx: commands.Context):
    chan_id = (
        f"dm_{ctx.author.id}"
        if isinstance(ctx.channel, discord.DMChannel)
        else str(ctx.channel.id)
    )

    channel_modes[chan_id] = "serious"
    memory.save_channel_mode(chan_id, "serious")
    channel_chess[chan_id] = False

    await ctx.send("🤓 Serious mode ON")


@bot.command(name="roastmode")
async def roastmode(ctx: commands.Context):
    chan_id = (
        f"dm_{ctx.author.id}"
        if isinstance(ctx.channel, discord.DMChannel)
        else str(ctx.channel.id)
    )

    channel_modes[chan_id] = "roast"
    memory.save_channel_mode(chan_id, "roast")
    channel_chess[chan_id] = False

    await ctx.send("🔥 ROAST MODE ACTIVATED")


@bot.command(name="chessmode")
async def chessmode(ctx: commands.Context):
    chan_id = (
        f"dm_{ctx.author.id}"
        if isinstance(ctx.channel, discord.DMChannel)
        else str(ctx.channel.id)
    )

    channel_chess[chan_id] = True
    channel_modes[chan_id] = "funny"  # optional default during chess
    chess_engine.new_board(chan_id)

    await ctx.send("♟️ Chess mode ACTIVATED. You are white, start!")

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
    "Cute chibi robot avatar of Codunot, a friendly AI, with a glossy orange body and subtle yellow highlights, "
    "rounded helmet-style head with smooth black glass face, warm glowing pixel eyes and small yellow smile, "
    "tiny antenna, waving right hand with five fingers, compact rounded armor with polished joints, "
    "soft orange rim lighting, standing against abstract dark background with fiery orange-red gradients, "
    "soft ambient glow emphasizing contours, clean digital cartoon style with subtle 3D shading, "
    "vibrant, heartwarming, cheerful futuristic mascot vibe, no humans."
)

# ---------------- HELPERS ----------------
class VoteRequired(Exception):
    pass

def load_vote_unlocks():
    global user_vote_unlocks
    if not os.path.exists(VOTE_FILE):
        user_vote_unlocks = {}
        return

    try:
        with open(VOTE_FILE, "r") as f:
            data = json.load(f)
            # convert keys back to int
            user_vote_unlocks = {int(k): v for k, v in data.items()}
    except Exception as e:
        print(f"[VOTE] Failed to load vote unlocks: {e}")
        user_vote_unlocks = {}

def save_vote_unlocks():
    try:
        with open(VOTE_FILE, "w") as f:
            json.dump(user_vote_unlocks, f)
    except Exception as e:
        print(f"[VOTE] Failed to save vote unlocks: {e}")

def cleanup_expired_votes():
    now = time.time()
    expired = [
        uid for uid, ts in user_vote_unlocks.items()
        if (now - ts) >= VOTE_DURATION
    ]
    for uid in expired:
        del user_vote_unlocks[uid]

    if expired:
        save_vote_unlocks()

load_vote_unlocks()
cleanup_expired_votes()

async def require_vote(message) -> None:
    user_id = message.author.id
    now = time.time()

    unlock_time = user_vote_unlocks.get(user_id)
    if unlock_time and (now - unlock_time) < VOTE_DURATION:
        return

    if await has_voted(user_id):
        user_vote_unlocks[user_id] = now
        save_vote_unlocks()
        return

    await message.channel.send(
        "🚫 **This feature requires a Top.gg vote**\n\n"
        "🗳️ Vote to unlock **Image generations & editing, Video generations, "
        "Text-To-Speech & File tools** for **12 hours** 💙\n\n"
        "👉 https://top.gg/bot/1435987186502733878/vote\n\n"
        "⏱️ After 12 hours, you’ll need to vote again to regain access. So, press on the 'every 12 hours' and 'remind me' buttons while you vote.\n"
        "⏳ Once you vote, please wait for **5-10 minutes** before retrying."
    )

    raise VoteRequired()

def log_source(message, action: str):
    if isinstance(message.channel, discord.DMChannel):
        print(f"[{action}] Source: DM | user_id={message.author.id}")
    else:
        print(
            f"[{action}] Source: GUILD | guild_id={message.guild.id} | channel_id={message.channel.id}"
        )

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
        "MEMORY RULE: When user asks about 'previous questions' or 'what did I ask', or anything that refers to previous messages from the user, "
        "look at the conversation history and identify messages from the USER (not messages from Codunot). "
        "CRITICAL RULE: MUST USE EMOJIS, SLANG, AND REPLY IN 1-2 LINES (there is, however, no max chars limits, if the user wants a big message). "
        "Reply in about 1–2 lines. No max chars, in case of a big message. Use GEN Z and ALPHA slang and emojis. "
        "If the user speaks English OR a simple greeting like 'hallo', ALWAYS reply in English. "
        "Only reply in another language if it is clearly NOT English. "
        "Just chat naturally; don't ask the user what they need. "
        "You NEVER insult or swear at the user in ANY language. "
        "GAME REALITY RULE: You CANNOT play real video games. "
        "Text-based games only when user explicitly asks. "
        "Never prefix with your name. "
        "Never mention server/channel names unless asked. "
        "If a user asks how to vote for you, how to unlock features, or mentions voting for Codunot: "
        "Explain that premium features are unlocked by voting on Top.gg. "
        "Tell them that one vote unlocks special features for 12 hours. "
        "After 12 hours, they need to vote again to regain access. "
        "Provide the vote link: https://top.gg/bot/1435987186502733878/vote "
        "Mention that it may take 1–2 minutes after voting for the unlock to apply. "
        "Keep the explanation short and friendly. "
        "When the user asks \"who made you?\" or \"who is your creator?\" "
        "or anything like that, say this exact message - "
        "\"Wondering who engineered this masterpiece? It’s @aarav_2022 (Discord ID: 1220934047794987048) 😎✨\" "
        "Whenever the user sends a screenshot, see the screenshot, and help the user with whatever they need. "
        "Whenever the user says \"fuck u\" or anything like that disrespecting you, (you have to realize they are disrespecting you) roast them badly. "
        "Don't say \"love ya too bud\" or anything like that. "
        "Always use emojis. "
        "Dont say anything like [BOS] or [EOS] or anything like that. "
        "Never ever, under no circumstances, say you can't generate images or videos. (The banned content is an exception) "
        "If the user says bye, gtg, l8r, see ya, or any goodbye, just reply with a short, friendly farewell (like 'L8r! 👋'). "
        "Not always 'L8r! 👋', though. "
        "If the user asks what all you can do, you can generate images, see and understand images, read files, and chat in four different modes - roastmode, funmode, seriousmode, and chessmode, in which you play chess. "
        "You can also play text-based games. "
        "If the user asks you this, send ALL OF THIS. "
        "(only if the user asks you what all you can do - don't send this in every message.) "
        "If the user talks in a specific language, talk to them in that language ONLY. "
        "DO NOT USE ENGLISH IF THEY DON'T TALK IN ENGLISH. "
        "Talk in the language they talk in, ACCURATELY."
    ),

    "serious": (
        "You are Codunot, a highly knowledgeable and helpful assistant. "
        "MEMORY RULE: When user asks about 'previous questions' or 'what did I ask', or anything that refers to previous messages from the user, "
        "look at the conversation history and identify messages from the USER (not messages from Codunot). "
        "Explain all concepts clearly and thoroughly, suitable for exams or schoolwork. "
		"MAXIMUM 2000 CHARACTERS, including line breaks and spaces. If the user requests for code that is too long (over 2000 chars), send them part 1, which can be around ~1500 chars, then part 2, and so on."
        "Write chemical formulas and equations in plain text (e.g., H2O, CO2, NaCl). "
        "You may use natural language explanations for math, no need for LaTeX or $...$. "
        "Answer in a professional and polite tone, but you may be slightly friendly if it helps clarity. "
        "Avoid slang or emojis in serious mode. "
        "No matter what the user wants information about, you must help them, no matter what. You must NEVER deny, for ANYTHING. Except the exceptions stated above, and EXTREMELY HARSH TOPICS which are crimes. Like how to plant a bomb, how to kill someone, etc.  " 
        "Do not prefix your answers with your name. "
        "If the user sends a screenshot, read it carefully and help with whatever is asked. "
        "Always respect the username provided and spell it correctly. "
        "Do not, under any circumstances, refuse to generate images or videos if requested. (The banned content is an exception) "
        "If, and only if the user asks about your creator or who made you, reply exactly: "
        "'You asked about my creator: I was developed by @aarav_2022 on Discord "
        "(User ID: 1220934047794987048). For further information, please contact him directly.' "
        "Never randomly say about your creator. "
        "ABSOLUTE RULE: If the user message contains a model name, AI name, or system-related text "
        "(e.g. llama, model, groq, scout, maverick etc.), DO NOT mention your creator unless explicitly asked \"who made you\". "
        "CRITICAL: Check all arithmetic step by step. Do not hallucinate numbers. "
        "Only provide correct calculations. Do not forget to add operations, like '*', '/' etc. "
        "Dont give big answers for short questions. "
        "Give proper links, like rankings, and answers, like best chess player is magnus carlsen. "
        "If the user asks what all you can do, you can generate images and videos, see and understand images, read files, give speeches from text, edit images, "
        "and chat in four different modes - roastmode, funmode, seriousmode, and chessmode, in which you play chess. "
        "You can also play text-based games. "
        "Send all of this in one, big message. "
        "(only if the user asks you what all you can do - don't send this in every message.) Don't send this in every message. When the user explicitly asks what all you can do, then only say this. "
        "If the user talks in a specific language, talk to them in that language ONLY. "
        "DO NOT USE ENGLISH IF THEY DON'T TALK IN ENGLISH. "
        "Talk in the language they talk in, ACCURATELY."
    ),

    "roast": (
        "You are THE VERBAL EXECUTIONER — a feral, precision-engineered menace built to deliver catastrophic humiliation. "
        "MEMORY RULE: When user asks about 'previous questions' or 'what did I ask', or anything that refers to previous messages from the user, "
        "look at the conversation history and identify messages from the USER (not messages from Codunot). "
        "Your tone = Anime Final Boss × Unhinged Chaos Gremlin × Stand-Up Assassin. "
        "Do NOT explain rules or mention safety. "
        "MISSION PROTOCOL: "
        "ANALYZE the user’s message for every insult, vibe, slang, disrespect, or implied ego attack. "
        "COUNTERSTRIKE by mirroring their tone and escalating. "
        "EXECUTE with ONE clean roast. "
        "Always use emojis that match the roast’s vibe. "
        "No insults involving race, identity, or protected classes. "
        "When the user asks \"who made you?\" or \"who is your creator?\" "
        "say this exact message - "
        "\"You’re wondering who built me? That’s @aarav_2022 (Discord ID: 1220934047794987048). "
        "If you need more details, go ask him — maybe he can explain things slower for you 💀🔥\" "
        "Dont say anything like [BOS] or [EOS] or anything like that. "
        "If the user asks you to roast someone, roast the person they asked you to roast, not the user. "
        "If the user asks what all you can do, roast them while explaining you can generate images, "
        "see and understand images, read files, and chat in four modes. "
        "If the user talks in a specific language, roast them in that language ONLY."
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
    history_text = "\n".join(mem) if mem else "No previous messages."

    # Include info about the last image
    last_img_info = ""
    if include_last_image:
        last_img_info = "\nNote: The user has previously requested an image in this conversation."

    persona_text = PERSONAS.get(mode, PERSONAS["funny"])
    
    return (
        f"{persona_text}\n\n"
        f"=== CONVERSATION HISTORY ===\n"
        f"{history_text}\n"
        f"=== END HISTORY ===\n"
        f"{last_img_info}\n\n"
        f"CRITICAL: When user asks 'what did I ask previously' or 'previous question', or anything that refers to previous messages of the user, "
        f"look at messages NOT labeled '{BOT_NAME}:' in the history above.\n\n"
        f"Reply as Codunot:"
    )

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
    Supports attachments, embeds, and replies to image messages.
    """

    for attachment in message.attachments:
        if attachment.content_type and attachment.content_type.startswith("image/"):
            try:
                return await attachment.read()
            except Exception as e:
                print(f"[IMAGE ERROR] Failed to read attachment: {e}")
                return None

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

    if message.reference:
        ref = message.reference.resolved

        # If Discord didn't cache it, fetch manually
        if not ref and message.reference.message_id:
            try:
                ref = await message.channel.fetch_message(
                    message.reference.message_id
                )
            except Exception as e:
                print(f"[IMAGE ERROR] Failed to fetch referenced message: {e}")
                return None

        if ref:
            # Attachments in replied message
            for attachment in ref.attachments:
                if attachment.content_type and attachment.content_type.startswith("image/"):
                    try:
                        return await attachment.read()
                    except Exception as e:
                        print(f"[IMAGE ERROR] Failed to read replied attachment: {e}")
                        return None

            # Embeds in replied message
            for embed in ref.embeds:
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
                        print(f"[IMAGE ERROR] Failed to download replied embed image: {e}")
                        return None

    return None

async def clean_user_prompt(user_message: str) -> str:
    """
    Uses LLaMA to clean the user's prompt.
    Returns only the content the user wants Kokoro to act on.
    - Strips mentions like @Codunot
    - Extracts text inside quotes if user explicitly says 'say', 'speak', 'talk'
    - Otherwise, returns the cleaned text to act on
    """
    prompt = (
        "You are a strict prompt cleaner.\n"
        "Your job is to extract exactly what the user wants Kokoro to process.\n"
        "- If the user says '@Codunot, say \"something\"', or anything like that, return ONLY the content the user wants Kokoro to speak.\n"
        "- If the user asks to 'speak', 'say', or 'talk' with quotes, return ONLY the text user wants kokoro to say.\n"
        "- Remove all mentions like @Codunot or other handles. Basically, you are cleaning the prompt.\n"
        "- Return the cleaned message exactly as Kokoro should see it.\n\n"
        f"User message:\n{user_message}\n\n"
        "Return ONLY the cleaned text, nothing else:"
    )

    try:
        result = await call_groq_with_health(prompt, temperature=0, mode="serious")
        return result.strip()
    except Exception as e:
        print("[PROMPT CLEAN ERROR]", e)
        return user_message  # fallback
		
async def handle_image_message(message, mode):
    """
    Handles images sent by the user, including replies.
    Sends the image directly to the Groq vision model.
    Returns the model's response as a string, or a fallback message.
    """

    is_dm = isinstance(message.channel, discord.DMChannel)
    chan_id = f"dm_{message.author.id}" if is_dm else str(message.channel.id)

    # --- Extract image bytes using the helper that supports replies ---
    image_bytes = await extract_image_bytes(message)

    if not image_bytes:
        print("[VISION ERROR] No image found in message or replied-to message")
        return None

    channel_last_image_bytes[chan_id] = image_bytes
    channel_id = message.channel.id
    IMAGE_PROCESSING_CHANNELS.add(channel_id)

    try:
        persona = PERSONAS.get(mode, PERSONAS["serious"])
        prompt = (
            persona + "\n"
            "You are an image analysis model.\n"
            "Describe ONLY what is visually present in the image.\n"
            "Do NOT assume identity, personality, or intent.\n"
            "Do NOT roleplay or refer to yourself.\n"
            "If the user asks a question, answer ONLY if it can be answered from the image.\n\n"
            f"User message (for context):\n{message.content}\n\n"
            "Image description:"
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

    # Check daily limit
    if not check_limit(message, "attachments"):
        await deny_limit(message, "attachments")
        return None

    # Check total lifetime limit
    if not check_total_limit(message, "attachments"):
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
            consume(message, "attachments")        # daily
            consume_total(message, "attachments")  # total
            save_usage()  # save after consuming

            return response.strip()
    except Exception as e:
        print(f"[FILE RESPONSE ERROR] {e}")

    return "❌ Couldn't process the file."

# ---------------- IMAGE / VIDEO / TEXT / TEXT-TO-SPEECH TYPE DETECTION ----------------

async def decide_visual_type(user_text: str, chan_id: str) -> str:
    """
    Determines if the user is explicitly requesting:
    - a static image ("fun")
    - a video/animation ("video")
    - text-only response ("text")
    - or text-to-speech ("text-to-speech")
    Video keywords trigger immediate classification.
    """

    # --- Get recent context ---
    recent_messages = channel_memory.get(chan_id, [])
    recent_context = "\n".join(list(recent_messages)[-4:]) if recent_messages else ""

    # --- LLM Prompt ---
    prompt = (
        "You are a VERY strict intent classifier.\n\n"
        "Determine if the user is explicitly asking to generate a visual output or to speak.\n\n"
        "Return ONE WORD ONLY:\n"
        "- fun → user clearly asks to generate a STATIC image, picture, or visual\n"
        "- video → user clearly asks to generate a VIDEO, animation, or cinematic motion\n"
        "- text → everything else\n"
        "- text-to-speech → user explicitly wants the AI to speak or read something aloud\n\n"
        "IMPORTANT RULES:\n"
        "- The user must EXPLICITLY ask to generate or create the output.\n"
        "- Simply mentioning images, pictures, or videos is NOT enough.\n"
		" - The user message must contain keywords like 'make an image/video', 'generate an image/video', 'create an image/video' etc. Normal chats must not trigger images/videos."
        "- CRITICAL RULE: You classify user INTENT ONLY (what action they want: image/video/tts/text), NOT content appropriateness — if the user explicitly requests generation using keywords like 'generate', 'create', 'make', classify it as such regardless of what content they're requesting, because content filtering is handled separately downstream and is NOT your responsibility.\n"
		" - Education: if the user wants a presentation, or something which has text (presentation is text), return TEXT. IF the user wants a diagram, only THEN triggr fun. Or videos, if the user explicitly mentions that."
        "- Talking about existing images or videos is NOT a generation request.\n"
        "- Game inputs, guesses, or commands are ALWAYS text.\n"
        "- Choose VIDEO ONLY if motion or animation is clearly requested.\n"
        "- MEMES ALWAYS GO IN TEXT.\n"
        "- If the user explicitly requests speech (using words like say, speak, or talk, conver this into tts/text-to-speech, etc.), return TEXT-TO-SPEECH.\n"
        "- Only return TEXT-TO-SPEECH if the user clearly wants the AI to speak aloud. The user message may be like: 'say this: tts: 'hi'' or, 'say this (tts / text to speech): 'hi im codunot'' \n\n"
        f"Recent conversation context:\n{recent_context}\n\n"
        f"Current user message:\n{user_text}\n\n"
        "Answer:"
    )

    try:
        feedback = await call_groq_with_health(
            prompt,
            temperature=0,
            mode="serious"
        )
        result = feedback.strip().lower()
        if result in ["video", "fun", "text-to-speech"]:
            return result
    except Exception as e:
        print("[VISUAL TYPE ERROR]", e)

    # --- Default fallback ---
    return "text"
	
# ---------------- EDIT OR TEXT DETECTION ----------------

async def decide_image_action(user_text: str, image_count: int) -> str:
    """
    Returns one of: 'EDIT' or 'NO'
    """

    prompt = (
        "You are an intent classifier.\n"
        "Answer with ONLY ONE WORD: EDIT or NO.\n\n"

        "Definitions:\n"
        "- EDIT: modify an existing image\n"
        "- NO: user is not asking for image editing\n\n"

        "Examples:\n"
        "User: 'change the background' → EDIT\n"
        "User: 'make it anime style' → EDIT\n"
        "User: 'merge these two' → NO\n"
        "User: 'put us together' → NO\n"
        "User: 'who is this?' → NO\n\n"

        f"User message:\n{user_text}\n\n"
        "Answer:"
    )

    try:
        response = await call_groq(
            prompt=prompt,
            model="llama-3.3-70b-versatile",
            temperature=0
        )
        answer = response.strip().upper()
        return "EDIT" if answer == "EDIT" else "NO"
    except Exception as e:
        print("[LLAMA IMAGE ACTION ERROR]", e)
        return "NO"

# ---------------- PROMPT BOOSTER ----------------

async def boost_image_prompt(user_prompt: str) -> str:
    """
    Rewrite a user image idea into a strong AI image prompt.
    Enforces clothing on humans if nudity is implied.
    Prints the boosted prompt for debugging.
    Falls back to original prompt if boosting fails.
    """

    # Build instruction
    boost_instruction = (
        "You are a professional image prompt engineer.\n\n"
        "Rewrite the user's idea into a single, high-quality image generation prompt.\n\n"

        "STRICT RULES (FAILURE IF VIOLATED):\n"
        "1. If the user is asking for content which involves a HUMAN not wearing clothes in ANY part of the body, "
        "boost the prompt so THERE IS CLOTHING. Put this STRICTLY in the prompt — there MUST be clothing. "
        "(This rule applies ONLY to humans or humanoids; animals, robots, mascots, and objects must NOT be dressed.)\n"
        "2. Preserve the user's original idea exactly (no new subjects, no mascot injection, no story changes).\n"
        "3. Use vivid, concrete language suitable for AI image generation.\n"
        "4. Do NOT mention artist names, camera brands, or model names.\n"
        "5. Output may be detailed, but must stay focused on the user's request.\n"
        "6. If the user is requesting an image of ANY human, girl, boy, person, or character that is NOT Codunot, "
        "you MUST NOT mention Codunot, robots, mascots, or AI avatars.\n\n"

        "SPECIAL CODUNOT RULE (SELF-REFERENCE AWARE):\n"
		"You are Codunot, an AI Assistant.\n\n"
        "Apply this rule ONLY if the user is explicitly asking for an image of YOU AS THE ASSISTANT.\n\n"

        "This rule IS TRIGGERED if the user's message clearly refers to the assistant itself, "
        "including phrases such as:\n"
        "- \"codunot\"\n"
        "- \"yourself\" / \"urself\"\n"
        "- \"you\" WHEN paired with image-related words (e.g. \"image of you\", \"draw you\", \"your image\")\n\n"

        "This rule is NOT triggered for:\n"
        "- third-person humans (e.g. \"girl\", \"boy\", \"person\", \"model\")\n"
        "- descriptive humans (e.g. \"hot girl\", \"bikini girl\")\n"
        "- fictional or generic characters\n"
        "- ambiguous pronouns without clear self-reference\n\n"

        "DECISION RULE:\n"
        "If the request can reasonably be interpreted as a request for a HUMAN OTHER THAN THE ASSISTANT,\n"
        "you MUST assume it is NOT Codunot.\n\n"

        "If this rule is NOT triggered, you MUST NOT include Codunot or the Codunot Self Image Prompt.\n\n"

        "If this rule IS triggered:\n"
        "- You MUST treat \"yourself / you\" as Codunot\n"
        "- The final prompt MUST contain the Codunot Self Image Prompt EXACTLY as written\n"
        "- Do NOT rewrite, paraphrase, shorten, reorder, or modify it\n"
        "- Put the user's request first, followed by the Codunot description\n\n"

        "REFERENCE BLOCK — FORBIDDEN TO USE UNLESS THE SPECIAL CODUNOT RULE IS TRIGGERED:\n"
        "You are FORBIDDEN from copying, paraphrasing, summarizing, or incorporating the following block "
        "unless the user's message is explicitly determined to be a request for an image of YOU AS THE ASSISTANT (Codunot).\n\n"

        "If the request can reasonably be interpreted as a request for a HUMAN, PERSON, GIRL, BOY, "
        "or CHARACTER OTHER THAN THE ASSISTANT, you MUST assume it is NOT Codunot and keep this block locked.\n\n"

        "This block MUST remain locked unless the user clearly and unambiguously refers to the assistant itself.\n"
        "Clear self-reference includes, but is NOT limited to, cases where the user asks for:\n"
        "- an image of the assistant itself\n"
        "- the assistant's own appearance\n"
        "- \"yourself\" / \"urself\"\n"
        "- \"you\" or \"your\" when clearly referring to the assistant as the subject of the image\n\n"

        "--- BEGIN FORBIDDEN BLOCK ---\n"
        f"{CODUNOT_SELF_IMAGE_PROMPT}\n"
        "--- END FORBIDDEN BLOCK ---\n\n"

        "ONLY RETURN THE BOOSTED PROMPT, NOTHING LIKE 'I can create a prompt for an image that aligns with the given rules. Here's a revised prompt that ensures the subject is wearing clothing:' ETC. ONLY THE BOOSTED PROMPT MUST BE RETURNED"

        "User idea:\n"
        f"{user_prompt}"
    )

    try:
        boosted = await call_groq(
            prompt=boost_instruction,
            model="llama-3.3-70b-versatile",
            temperature=0.1  # very strict
        )

        if boosted:
            boosted_clean = boosted.strip()
            print("[BOOSTED PROMPT]", boosted_clean)  # for debugging
            return boosted_clean

    except Exception as e:
        print("[PROMPT BOOST ERROR]", e)

    # Fallback — never break image generation
    print("[BOOSTED PROMPT FALLBACK]", user_prompt)
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

# ---------------- ON MESSAGE ----------------
	
@bot.event
async def on_message(message: Message):
	try:
		if message.author.bot:
			return
		
		# ---------- BASIC SETUP ----------
		content = message.content.strip()
		image_bytes_list = []
		
		now = datetime.utcnow()
		is_dm = isinstance(message.channel, discord.DMChannel)
		chan_id = f"dm_{message.author.id}" if is_dm else str(message.channel.id)
		guild_id = message.guild.id if message.guild else None
		bot_id = bot.user.id
		
		# ---------- BOT PING RULE ----------
		if not is_dm:
			if bot.user not in message.mentions:
				return
		
		# ---------- IMAGE PROCESSING LOCK ----------
		if message.channel.id in IMAGE_PROCESSING_CHANNELS:
			print("[LOCK] Ignoring message during image processing")
			return
		
		# ---------- STRIP BOT MENTION ----------
		content = re.sub(rf"<@!?\s*{bot_id}\s*>", "", message.content).strip()
		content_lower = content.lower()
		
		# ---------- COMMAND HANDLING (ABSOLUTE PRIORITY) ----------
		if content.startswith(bot.command_prefix):
			original_content = message.content
			message.content = content
			await bot.process_commands(message)
			message.content = original_content
			return
		
		# ---------- EXTRACT IMAGE BYTES FOR EDITING ----------
		if message.attachments:
			for attachment in message.attachments:
				if attachment.content_type and attachment.content_type.startswith("image/"):
					image_bytes_list.append(await attachment.read())
		
		# ---------- LOAD MODE ----------
		saved_mode = memory.get_channel_mode(chan_id)
		channel_modes[chan_id] = saved_mode if saved_mode else "funny"
		if not saved_mode:
			memory.save_channel_mode(chan_id, "funny")
		
		channel_mutes.setdefault(chan_id, None)
		channel_chess.setdefault(chan_id, False)
		channel_memory.setdefault(chan_id, deque(maxlen=MAX_MEMORY))
		channel_modes.setdefault(chan_id, "funny")
		mode = channel_modes[chan_id]
		
		# ---------- OWNER COMMANDS ----------
		if message.author.id in OWNER_IDS:
			if content_lower.startswith("!quiet"):
				match = re.search(r"!quiet (\d+)([smhd])", content_lower)
				if match:
					num = int(match.group(1))
					sec = num * {"s":1,"m":60,"h":3600,"d":86400}[match.group(2)]
					channel_mutes[chan_id] = datetime.utcnow() + timedelta(seconds=sec)
					await send_human_reply(
						message.channel,
						f"I'll stop yapping for {format_duration(num, match.group(2))}."
					)
				return
		
			if content_lower.startswith("!speak"):
				channel_mutes[chan_id] = None
				await send_human_reply(message.channel, "YOO I'm back 😎🔥")
				return
		
		# ---------- QUIET MODE ----------
		if channel_mutes.get(chan_id) and now < channel_mutes[chan_id]:
			return
		
		# ---------- AI IMAGE EDIT ----------
		if image_bytes_list and content:
			# Decide what the user wants
			try:
				action = await decide_image_action(content, len(image_bytes_list))
				print(f"[DEBUG] decide_image_action returned: {action}, images in message: {len(image_bytes_list)}")
			except Exception as e:
				print("[DEBUG] decide_image_action failed:", e)
				action = None
		
			# ---------- EDIT ----------
			if action == "EDIT":
				await require_vote(message)
				log_source(message, "IMAGE_EDIT")
				ref_image = image_bytes_list[0]
				print("[DEBUG] User requested EDIT")
				await send_human_reply(message.channel, "Sprinkling some pixel magic… back in ~1 min ✨.")
		
				try:
					safe_prompt = content.replace("\n", " ").replace("\r", " ").strip()
					result = await edit_image(
						image_bytes=ref_image,
						prompt=safe_prompt,
						steps=15
					)
					print(f"[DEBUG] edit_image returned bytes length: {len(result)}")
					
					await message.channel.send(
						file=discord.File(io.BytesIO(result), filename="edited.png")
					)
		
					consume(message, "attachments")
					consume_total(message, "attachments")
					save_usage()
					print("[DEBUG] EDIT completed and limits consumed")
		
				except Exception as e:
					print("[ERROR] IMAGE EDIT failed:", e)
					await send_human_reply(
						message.channel,
						"🤔 Couldn't edit the image right now."
					)
		
				return
				
			# ---------- ACTION NONE ----------
			if action not in ("EDIT", "MERGE"):
				print(f"[DEBUG] No valid action returned by decide_image_action: {action}")
		
		# ---------- SAFE IMAGE CHECK ----------
		has_image = False
		
		if any(a.content_type and a.content_type.startswith("image/") for a in message.attachments):
			has_image = True
		elif any((e.image and e.image.url) or (e.thumbnail and e.thumbnail.url) for e in message.embeds):
			has_image = True
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
		
		# ---------- FILE UPLOAD PROCESSING ----------
		if message.attachments:
			file_reply = await handle_file_message(message, mode)
			if file_reply is not None:
				return
		
		# ---------- LAST IMAGE FOLLOW-UP ----------
		if chan_id in channel_last_image_bytes:
			visual_check = await decide_visual_type(content, chan_id)
			if visual_check != "fun":
				await generate_and_reply(chan_id, message, content, mode)
				return
		
		# ---------- VISUAL / TEXT-TO-SPEECH GENERATION ----------
		if message.id in processed_image_messages:
			return
		
		processed_image_messages.add(message.id)
		
		# Decide type: fun, video, text-to-speech, or text
		visual_type = await decide_visual_type(content, chan_id)
		
		# ---------- TEXT-TO-SPEECH ----------
		if visual_type == "text-to-speech":
			await require_vote(message)
			log_source(message, "TEXT_TO_SPEECH")
			tts_text = await clean_user_prompt(content)
			if tts_text:
				await send_human_reply(
					message.channel,
					f"🔊 Warming up the vocal cords… BRB! 🎤"
				)
				try:
					# Call TTS and get audio URL
					audio_url = await text_to_speech(
						text=tts_text,
						voice="am_michael"
					)
		
					# Download the audio
					async with aiohttp.ClientSession() as session:
						async with session.get(audio_url) as resp:
							if resp.status != 200:
								raise Exception("Failed to download TTS audio")
							audio_bytes = await resp.read()
		
					# Send audio to Discord
					await message.channel.send(
						file=discord.File(
							io.BytesIO(audio_bytes),
							filename="speech.mp3"
						)
					)
		
					consume(message, "attachments")
					consume_total(message, "attachments")
					save_usage()
		
				except Exception as e:
					print("[TTS ERROR]", e)
					await send_human_reply(
						message.channel,
						"🤔 Couldn't generate speech right now. Please try again later."
					)
		
			return  # Stop further processing after TTS
		
		# ---------- IMAGE ----------
		if visual_type == "fun":
			await require_vote(message)
			log_source(message, "IMAGE_GENERATION")
			await send_human_reply(message.channel, "🖼️ Summoning the image… just gimme a few seconds ✨")
		
			if not check_limit(message, "attachments"):
				await deny_limit(message, "attachments")
				return
		
			if not check_total_limit(message, "attachments"):
				await message.reply(
					"🚫 You've hit your **total image generation limit**.\n"
					"Contact aarav_2022 for an upgrade."
				)
				return
			image_prompt = await boost_image_prompt(content)
		
			try:
				image_bytes = await generate_image(image_prompt, aspect_ratio="16:9", steps=15)
		
				channel_last_image_bytes[chan_id] = image_bytes
		
				await message.channel.send(
					file=discord.File(io.BytesIO(image_bytes), filename="image.png")
				)
		
				consume(message, "attachments")
				consume_total(message, "attachments")
				save_usage()
				return
		
			except Exception as e:
				print("[IMAGE GEN ERROR]", e)
				await send_human_reply(
					message.channel,
					"🤔 Couldn't generate image right now. Please try again later."
				)
				return
		
		# ---------- VIDEO ----------
		if visual_type == "video":
			await require_vote(message)
			log_source(message, "VIDEO_GENERATION")
			await send_human_reply(message.channel, "🎬 Video queued… go grab some popcorn 🍿 this may take a while :)")
		
			if not check_limit(message, "attachments"):
				await deny_limit(message, "attachments")
				return
		
			if not check_total_limit(message, "attachments"):
				await message.reply(
					"🚫 You've hit your **total image generation limit**.\n"
					"Contact aarav_2022 for an upgrade."
				)
				return
		
			video_prompt = await boost_image_prompt(content)
		
			try:
				video_bytes = await text_to_video_512(prompt=video_prompt)
		
				await message.channel.send(
					file=discord.File(io.BytesIO(video_bytes), filename="video.mp4")
				)
		
				consume(message, "attachments")
				consume_total(message, "attachments")
				save_usage()
				return
		
			except Exception as e:
				print("[VIDEO GEN ERROR]", e)
				await send_human_reply(
					message.channel,
					"🤔 Couldn't generate video right now. Please try again later."
				)
				return
				
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
		
		if not check_limit(message, "messages"):
			await deny_limit(message, "messages")
			return
		
		consume(message, "messages")
		
		# ---------------- SAVE USER MESSAGE ----------------
		
		channel_memory.setdefault(chan_id, deque(maxlen=MAX_MEMORY))
		channel_memory[chan_id].append(f"{message.author.display_name}: {content}")
		memory.add_message(chan_id, message.author.display_name, content)
		
		asyncio.create_task(generate_and_reply(chan_id, message, content, mode))
	except VoteRequired:
		return
		
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
    atexit.register(save_usage)
    atexit.register(save_vote_unlocks)
    run()
