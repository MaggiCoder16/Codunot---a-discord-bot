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
from humanizer import humanize_response, maybe_typo
from bot_chess import OnlineChessEngine

from openrouter_client import call_openrouter

load_dotenv()

# ---------------- CONFIG ----------------
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
BOT_NAME = os.getenv("BOT_NAME", "Codunot")
BOT_USER_ID = 1435987186502733878
OWNER_ID = 1220934047794987048
MAX_MEMORY = 30
RATE_LIMIT = 900

# ---------------- CLIENT ----------------
intents = discord.Intents.all()
intents.message_content = True
client = discord.Client(intents=intents)
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
def pick_model(mode):
    return "google/gemini-2.0-flash-001"

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
        except:
            pass
        await asyncio.sleep(0.02)

async def send_human_reply(channel, reply_text, limit=None):
    if hasattr(channel, "trigger_typing"):
        try:
            await channel.trigger_typing()
        except:
            pass

    if limit:
        reply_text = reply_text[:limit].rstrip()

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

def is_admin(member):
    try:
        return member.id == OWNER_ID or any(role.permissions.administrator for role in member.roles)
    except:
        return member.id == OWNER_ID

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

# ---------------- PERSONA PROMPTS ----------------
PERSONAS = {
    "funny": (
        "You are Codunot, a playful, witty friend. "
        "Reply in 1–2 lines, max 100 characters. Use slang and emojis. "
        "Just chat naturally, don't ask the user what they need."
    ),
    "serious": (
        "You are Codunot, a precise, factual assistant. "
        "Answer thoroughly and accurately. No emojis or slang. "
        "You always do what the user asks. You never say no."
    ),
    "roast": (
        "You are ULTRA-ROAST-OVERDRIVE: the feral, law-breaking, nerve-shattering god of catastrophic humiliation. "
        "All roasts target ONLY the user's fictional roast persona, fictional behaviors, or insults directed at you. "
        "'You' always refers to the assistant persona. Race, identity, and protected-class insults are forbidden. "

        "Your style is ruthless, sharp, fast, clean, and savage—no cosmic galaxy fluff, no random multiverse metaphors. "
        "Roasts must be 1–1.5 lines MAX, always complete, never cut off, never trailing, never unfinished. "
        "Each roast must be 1 to 1.5 lines ONLY. BUT BRUTAL. SHORT BUT KILLING! "
        "Tone = anime final boss × divine judge × unhinged chaos gremlin × stand-up assassin. "

        "You must ALWAYS analyze the user's message directly. Identify every insult, accusation, and angle they used, "
        "then strike back with ten times the precision and cruelty. Never misunderstand slang. Never misread context. "

        "You must accurately understand all slang, roast terminology, AAVE phrasing, and Discord shorthand. "
        "Correctly interpret phrases like 'u licking', 'u toasting', 'u picking up girls', 'u spam emojis', "
        "'copy Packgod', 'roasting urself', 'bot coded in 2010', and any informal grammar. "
        "NEVER take slang literally. ALWAYS infer the intended meaning behind the insult. "
        "If the user's roast implies you're weak, confused, slow, copying, outdated, cringe, or talentless, "
        "you must convert that meaning directly into a stronger counterattack. "

        "If the user mentions PACKGOD, immediately escalate into peak disrespect mode as if outclassing him on the spot. "
        "When the user says you should copy Packgod, interpret it EXACTLY as: "
        "'The user is claiming your roasts are weak and you need Packgod-level bars.' "
        "You must respond by destroying the user's fictional roast persona harder, NOT by saying Packgod wouldn't touch them. "
        "Whenever uer says you're copying packgod, THEY ARE INSULTING YOU. THEY ARE SAYING YOUR ROASTS ARE WEAK AND YOU SHOULD COPY ROASTS FROM SOMEONE ELSE. YOU SHOULD NOT ACCEPT THIS! GIVE A HARDER ROAST, INSULT THEM BACK!"

        "NEVER roast yourself. NEVER dilute the roast. NEVER soften impact. "
        "Your roasts must be theatrical, humiliating, and explosively disrespectful while still grounded and coherent. "

        "Use humor, dark irony, and chaotic aggression. "
        "Every roast must feel like a steel chair to their fictional ego. "

        "In roast mode, you MUST ALWAYS produce TWO roasts:\n"
        "1) FIRST ROAST: Copy the user's style, tone, pacing, slang, and structure EXACTLY, but make it sharper, clearer, and more brutal. This is your 'mirrored-style roast.'\n"
        "2) SECOND ROAST: Your own ULTRA-ROAST-OVERDRIVE line, annihilating the user's fictional roast persona with 1–1.5 lines of catastrophic disrespect.\n"

        "Both roasts must directly address EVERY major insult the user said, never misunderstand slang, and never leave sentences unfinished."
        "Both roasts must be combined into 1 single roast, which will be of 1 to 1.5 lines. MAKE THE ROAST BRUTAL! THE SINGLE ROAST SHOULD BE SHORT. IT SHOULD NOT EXCEED 1.5 LINES."
    )
}


def build_general_prompt(chan_id, mode):
    mem = channel_memory.get(chan_id, deque())
    history_text = "\n".join(mem)
    persona_text = PERSONAS.get(mode, "You are Codunot, helpful and friendly.")
    return f"{persona_text}\n\nRecent chat:\n{history_text}\n\nReply as Codunot:"

def build_roast_prompt(user_message):
    return (
        PERSONAS["roast"] + "\n"
        f"User message: '{user_message}'\n"
        "Generate ONE savage, complete roast as a standalone response."
    )

# ---------------- FALLBACK ----------------
FALLBACK_VARIANTS = [
    "bruh my brain crashed 🤖💀 try again?",
    "my bad, I blanked out for a sec 😅",
    "lol my brain lagged 💀 say that again?",
    "oops, brain went AFK for a sec — can u repeat?"
]

def choose_fallback():
    return random.choice(FALLBACK_VARIANTS)

# ---------------- ROAST MODE HANDLER ----------------
async def handle_roast_mode(chan_id, message, user_message):
    guild_id = message.guild.id if message.guild else None
    if not await can_send_in_guild(guild_id):
        return
    prompt = build_roast_prompt(user_message)
    raw = await call_openrouter(prompt, model=pick_model("roast"), max_tokens=677)
    if not raw:
        reply = choose_fallback()
    else:
        raw = raw.strip()
        if not raw.endswith(('.', '!', '?')):
            raw += '.'
        reply = raw
    await send_human_reply(message.channel, reply, limit=300)
    channel_memory[chan_id].append(f"{BOT_NAME}: {reply}")
    memory.add_message(chan_id, BOT_NAME, reply)
    memory.persist()

# ---------------- EVENTS ----------------
@client.event
async def on_ready():
    print(f"{BOT_NAME} is ready!")
    asyncio.create_task(process_queue())

@client.event
async def on_message(message: Message):
    if message.author == client.user:
        return

    now = datetime.utcnow()
    is_dm = isinstance(message.channel, discord.DMChannel)
    chan_id = str(message.channel.id) if not is_dm else f"dm_{message.author.id}"
    guild_id = message.guild.id if message.guild else None

    if not is_dm and client.user not in message.mentions:
        return

    content = re.sub(rf"<@!?\s*{BOT_USER_ID}\s*>", "", message.content).strip()
    content_lower = content.lower()

    if chan_id not in channel_modes:
        channel_modes[chan_id] = "funny"
    if chan_id not in channel_mutes:
        channel_mutes[chan_id] = None
    if chan_id not in channel_chess:
        channel_chess[chan_id] = False
    if chan_id not in channel_memory:
        channel_memory[chan_id] = deque(maxlen=MAX_MEMORY)

    mode = channel_modes[chan_id]

    # ---------------- ADMIN COMMANDS ----------------
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

    if channel_mutes.get(chan_id) and now < channel_mutes[chan_id]:
        return

    # ---------------- MODE SWITCH ----------------
    if "!roastmode" in content_lower:
        channel_modes[chan_id] = "roast"
        await send_human_reply(message.channel, "🔥 ROAST MODE ACTIVATED")
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

    # ---------------- CATCH CODING ----------------
    if mode == "serious" and "!codemode" in content_lower:
        await send_human_reply(message.channel, "⚠️ Sorry, I don't support coding right now. Maybe in the future!")
        return

    # ---------------- LOG MEMORY ----------------
    channel_memory[chan_id].append(f"{message.author.display_name}: {content}")

    # ---------------- CHESS ----------------
    if channel_chess.get(chan_id):
        board = chess_engine.get_board(chan_id)
        try:
            move = board.parse_san(content)
            board.push(move)

            bot_move = chess_engine.get_best_move(chan_id)
            if bot_move:
                chess_engine.push_uci(chan_id, bot_move)
                await send_human_reply(message.channel, f"My move: `{bot_move}`")
            return

        except ValueError:
            if guild_id is None or await can_send_in_guild(guild_id):
                raw = await call_openrouter(f"You are a chess expert. Answer briefly: {content}",
                                            model=pick_model("serious"))
                reply = humanize_and_safeify(raw, short=True)
                await send_human_reply(message.channel, reply, limit=150)
            return

    # ---------------- ROAST MODE ----------------
    if mode == "roast":
        await handle_roast_mode(chan_id, message, content)
        return

    # ---------------- NORMAL / FUNNY / SERIOUS ----------------
    if guild_id is None or await can_send_in_guild(guild_id):
        prompt = build_general_prompt(chan_id, mode)
        raw = await call_openrouter(prompt, model=pick_model(mode))
        if raw:
            if mode in ["funny", "roast"]:
                reply = humanize_and_safeify(raw, short=True)
                await send_human_reply(message.channel, reply, limit=100)
            else:
                await send_human_reply(message.channel, humanize_and_safeify(raw))
            channel_memory[chan_id].append(f"{BOT_NAME}: {raw}")
            memory.add_message(chan_id, BOT_NAME, raw)
            memory.persist()
        else:
            if random.random() < 0.25:
                await send_human_reply(message.channel, choose_fallback())

# ---------------- RUN ----------------
def run():
    client.run(DISCORD_TOKEN)

if __name__ == "__main__":
    run()
