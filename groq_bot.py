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
import base64
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

    if response:
        channel_memory[chan_id].append(f"{BOT_NAME}: {response}")
        memory.add_message(chan_id, BOT_NAME, response)
        memory.persist()

# ---------------- IMAGE HANDLING ----------------

async def ocr_image(image_bytes: bytes) -> str:
    try:
        img = Image.open(io.BytesIO(image_bytes))  # Open the .webp image
        text = pytesseract.image_to_string(img)   # Run OCR on the image
        text = text.strip()  # Clean up text
        if text:
            return text
        return "[No readable text detected]"
    except Exception as e:
        print(f"[OCR ERROR] {e}")
        return "[OCR failed]"

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

    # 1. OCR
    ocr_text = await ocr_image(image_bytes)
    print(f"[DEBUG] OCR RESULT: {ocr_text}")

    # 2. Build prompt
    persona = PERSONAS.get(mode, PERSONAS["serious"])
    prompt = (
        persona + "\n"
        "The user sent an image. I extracted text using OCR.\n"
        "Here is the extracted text:\n"
        f"----\n{ocr_text}\n----\n"
        "Help the user based ONLY on this extracted text. "
        "Never say that OCR isn't working."
        "If there is no text in the image at all, help the user normally by seeing the image, dont consider the text if OCR returns nothing."
        "Never say the image has text or not. Just help the user with whatever they want if the image doesnt have text."
    )

    try:
        response = await call_groq(
            prompt=prompt,
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            temperature=0.7
        )
        if response:
            print(f"[DEBUG] Model returned: {response}")
            return response.strip()
        else:
            return "i cant see images rn.. :((( maybe later???? :::::::::::::::::::))))))"

    except Exception as e:
        print(f"[OCR ERROR] {e}")
        return "i cannot see images rn sowwwwyyyyyy.... maybe later?"

        
# ---------------- CHESS UTILS ----------------
RESIGN_PHRASES = [
    "resign", "i resign", "gg", "good game", "give up", "i give up",
    "surrender", "i surrender", "forfeit", "i forfeit", "quit", "i quit",
    "done", "enough", "cant win", "can't win", "lost", "i lost",
    "i'm done", "im done"
]

CHESS_CHAT_KEYWORDS = [
    "hint", "help", "assist", "suggest", "advice",
    "what should", "what do i play", "what now",
    "any ideas", "idea", "plan", "strategy",
    "next move", "best move", "recommend",
    "good move", "bad move", "was that good",
    "was that bad", "mistake", "blunder",
    "did i blunder", "is this winning", "is this losing",
    "am i better", "am i worse", "position",
    "analyze", "analysis", "explain", "why", "how",
    "what's the idea", "what is the point", "what does this do",
    "what am i missing", "thoughts", "teach", "learn", "lesson",
    "how do i improve", "how to play", "beginner", "advanced", "tips",
    "principles", "fundamentals", "opening", "opening name", "what opening",
    "is this an opening", "theory", "book move", "out of book",
    "endgame", "middlegame", "late game", "early game", "transition",
    "am i in trouble", "is this dangerous", "any threats",
    "what is he threatening", "is my king safe", "or", "instead",
    "better than", "which is better", "this or that",
    "gg", "good game", "that was fun", "nice game", "rematch",
    "again", "another", "idk", "i don't know", "confused", "lost",
    "i'm stuck", "not sure", "lol", "lmao", "bruh", "bro",
    "haha", "rip", "damn", "oops", "my bad"
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
    return any(phrase in t for phrase in RESIGN_PHRASES)

def looks_like_chess_chat(text: str) -> bool:
    t = text.lower().strip()
    if any(k in t for k in CHESS_CHAT_KEYWORDS):
        return True
    if len(t.split()) > 3:
        return True
    return False

def looks_like_chess_move(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    if looks_like_chess_chat(t):
        return False
    return bool(MOVE_REGEX.match(t))

def normalize_move_input(board, move_input: str) -> str | None:
    raw = move_input.strip()
    if not raw:
        return None
    if is_resign_message(raw):
        return "resign"
    norm = (
        raw.replace("o-o-o", "O-O-O")
           .replace("o-o", "O-O")
           .replace("0-0-0", "O-O-O")
           .replace("0-0", "O-O")
    ).strip()
    legal_moves = list(board.legal_moves)
    if len(norm) == 2 and norm[0].lower() in "abcdefgh" and norm[1] in "12345678":
        matches = [m for m in legal_moves if m.to_square == chess.parse_square(norm.lower())]
        if len(matches) == 1:
            return board.san(matches[0])
    if len(norm) >= 2 and norm[0].lower() in "nbrqk":
        norm = norm[0].upper() + norm[1:]
    try:
        move_obj = board.parse_san(norm)
        return board.san(move_obj)
    except:
        pass
    try:
        move_obj = chess.Move.from_uci(raw.lower())
        if move_obj in legal_moves:
            return board.san(move_obj)
    except:
        pass
    return None

# ---------------- ON_MESSAGE + CHESS MODE ----------------
@bot.event
async def on_message(message: Message):
    if message.author.bot:
        return

    now = datetime.utcnow()
    is_dm = isinstance(message.channel, discord.DMChannel)
    chan_id = f"dm_{message.author.id}" if is_dm else str(message.channel.id)
    bot_id = bot.user.id

    # Respond only if bot mentioned in server
    if not is_dm and bot.user not in message.mentions:
        return

    content = re.sub(rf"<@!?\s*{bot_id}\s*>", "", message.content).strip()
    content_lower = content.lower()

    # Load/set mode
    saved_mode = memory.get_channel_mode(chan_id)
    channel_modes[chan_id] = saved_mode if saved_mode else "funny"
    if not saved_mode:
        memory.save_channel_mode(chan_id, "funny")

    # Ensure states
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

    # ---------------- IMAGE CHECK ----------------
    has_image = any(a.content_type and a.content_type.startswith("image/") for a in message.attachments)
    has_image |= any((e.image and e.image.url) or (e.thumbnail and e.thumbnail.url) for e in message.embeds)
    urls = re.findall(r"(https?://\S+)", message.content)
    img_exts = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff")
    has_image |= any(url.lower().endswith(img_exts) for url in urls)
    if has_image:
        image_reply = await handle_image_message(message, mode)
        if image_reply:
            await send_human_reply(message.channel, image_reply)
            return

    # ---------------- CHESS MODE ----------------
    if channel_chess.get(chan_id):
        board = chess_engine.get_board(chan_id)

        # Game over → normal chat
        if board.is_game_over():
            channel_chess[chan_id] = False
            await send_human_reply(message.channel, "GG 😎 wanna play again?")
            return

        # Resign
        if is_resign_message(content):
            await send_human_reply(message.channel, f"GG 😄 {message.author.display_name} resigned!")
            channel_chess[chan_id] = False
            return

        # Natural language chat (hints, questions)
        if looks_like_chess_chat(content):
            chess_prompt = (
                PERSONAS["funny"] +
                "\nYou are a chess-savvy friend helping during a live game.\n" +
                f"Current FEN: {board.fen()}\n" +
                f"User says: {content}\n" +
                "Give hints, explanations, or chess knowledge. DO NOT invent moves.\nReply:"
            )
            response = await call_groq(prompt=chess_prompt, model="llama-3.3-70b-versatile", temperature=0.6)
            await send_human_reply(message.channel, humanize_and_safeify(response))
            return

        # Try real move
        move_san = normalize_move_input(board, content)
        if not move_san:
            await send_human_reply(message.channel, "🤔 That doesn’t look like a legal move — want a hint?")
            return

        move_obj = board.parse_san(move_san)
        board.push(move_obj)

        if board.is_checkmate():
            await send_human_reply(message.channel, f"😮 Checkmate! YOU WIN ({move_san})")
            channel_chess[chan_id] = False
            return

        # Engine move
        best = chess_engine.get_best_move(chan_id)
        bot_move = board.parse_uci(best["uci"])
        board.push(bot_move)
        await send_human_reply(message.channel, f"My move: `{best['uci']}` / **{best['san']}**")
        if board.is_checkmate():
            await send_human_reply(message.channel, f"💀 Checkmate — I win ({best['san']})")
            channel_chess[chan_id] = False

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
