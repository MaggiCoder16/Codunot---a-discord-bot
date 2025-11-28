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
import aiohttp
import base64

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
        "Never mention server/channel names unless asked. "
        "When the user asks \"who made you?\" or \"who is your creator?\" "
        "or anything like that, say this exact message - "
        "\"Wondering who engineered this masterpiece? It’s @aarav_2022 "
        "(Discord ID: 1220934047794987048) 😎✨\""
        "Whenever the user sends a screenshot, read the screenshot, and help the user with whatever they need."
        "Whenever the user says \"fuck u\" or anything like that disrespecting you, (you have to realize they are disrespecting you) roast them light-heartedly. Don't say \"love ya too bud\" or anything like that"
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
        "\"You’re wondering who built me? That’s @aarav_2022 (Discord ID: 1220934047794987048). "
        "If you need more details, go ask him — maybe he can explain things slower for you 💀🔥\""
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
        return "bro I couldn’t load that image 💀"

    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
    persona = PERSONAS.get(mode, PERSONAS["serious"])

    payload = {
        "model": "nvidia/nemotron-nano-12b-v2-vl:free",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": persona},
                    {
                        "type": "input_image",
                        "image_url": f"data:image/png;base64,{image_b64}"
                    },
                    {"type": "text", "text": "What's in this image?"}
                ]
            }
        ]
    }

    try:
        response = await call_openrouter_raw(payload)
        if not response:
            return "bro I couldn’t load that image 💀"

        return response.strip()

    except Exception as e:
        print(f"[VISION ERROR] {e}")
        return "bro I couldn’t load that image 💀"

# ---------------- CHESS UTILS ----------------
RESIGN_PHRASES = [
    "resign", "i resign", "gg", "give up", "i give up",
    "surrender", "i surrender", "forfeit", "i forfeit",
    "quit", "i quit", "done", "enough", "cant win",
    "can't win", "lost", "i lost", "i'm done", "im done"
]

def is_resign_message(message_content: str) -> bool:
    msg = message_content.lower()
    for phrase in RESIGN_PHRASES:
        if phrase in msg:
            return True
    return False

def normalize_move_input(board, move_input: str) -> str:
    move_input = move_input.strip().lower().replace('o-0', '0-0').replace('o-o-o', '0-0-0')
    if is_resign_message(move_input):
        return "resign"

    legal_moves = list(board.legal_moves)

    if len(move_input) == 2 and move_input[0] in 'abcdefgh' and move_input[1] in '123456':
        matches = [m for m in legal_moves if m.to_square == chess.parse_square(move_input)]
        if len(matches) == 1:
            return board.san(matches[0])

    try:
        move_obj = board.parse_san(move_input)
        return board.san(move_obj)
    except:
        pass

    try:
        move_obj = chess.Move.from_uci(move_input)
        if move_obj in legal_moves:
            return board.san(move_obj)
    except:
        pass

    if '-' in move_input:
        try:
            move_obj = board.parse_san(move_input.replace('-', ''))
            return board.san(move_obj)
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

    # Mode switching
    if "!roastmode" in content_lower:
        channel_modes[chan_id] = "roast"
        memory.save_channel_mode(chan_id, "roast")
        await send_human_reply(message.channel, "🔥 ROAST MODE ACTIVATED")
        return
    if "!funmode" in content_lower:
        channel_modes[chan_id] = "funny"
        memory.save_channel_mode(chan_id, "funny")
        await send_human_reply(message.channel, "😎 Fun mode activated!")
        return
    if "!seriousmode" in content_lower:
        channel_modes[chan_id] = "serious"
        memory.save_channel_mode(chan_id, "serious")
        await send_human_reply(message.channel, "🤓 Serious mode ON")
        return
    if "!chessmode" in content_lower:
        channel_chess[chan_id] = True
        chess_engine.new_board(chan_id)
        await send_human_reply(message.channel, "♟️ Chess mode ACTIVATED. You are white, start!")
        return

    # ---------------- IMAGE HANDLING ----------------
    image_reply = await handle_image_message(message, mode)
    if image_reply:
        await send_human_reply(message.channel, image_reply)
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

    # Log user message in memory
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
