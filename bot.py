import os
import asyncio
import random
import re
from datetime import datetime, timedelta, timezone
from collections import deque

import discord
from discord import Message, app_commands
from discord.ext import commands
from dotenv import load_dotenv

from memory import MemoryManager
from humanizer import humanize_response, maybe_typo
from bot_chess import OnlineChessEngine
from openrouter_client import call_openrouter # updated client with logging
import chess # <--- CRITICAL FIX: Ensure the python-chess library is imported

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

# ---------------- MODEL PICKER ----------------
def pick_model(mode: str):
    if mode == "funny":
        return "x-ai/grok-4.1-fast:free"
    if mode == "roast":
        return "mistralai/mistral-7b-instruct:free"
    if mode == "serious":
        return "mistralai/mistral-7b-instruct:free"
    return "x-ai/grok-4.1-fast:free"

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

async def change_channel_mode(chan_id: str, new_mode: str) -> str:
    """Sets the mode and returns the appropriate confirmation message."""
    channel_modes[chan_id] = new_mode
    memory.save_channel_mode(chan_id, new_mode)

    if new_mode == "chess":
        channel_chess[chan_id] = True
        chess_engine.new_board(chan_id)
        return "♟️ Chess mode ACTIVATED. You are white, start!"
    else:
        channel_chess[chan_id] = False

    messages = {
        "funny": "😎 Fun mode activated!",
        "roast": "🔥 ROAST MODE ACTIVATED",
        "serious": "🤓 Serious mode ON"
    }
    return messages.get(new_mode, f"Mode set to {new_mode}!")

# ---------------- PERSONAS ----------------
PERSONAS = {
    "funny": (
        "You are Codunot, a playful, witty friend. "
        "Reply in 1–2 lines, max 100 characters. Use slang and emojis. "
        "Just chat naturally, don't ask the user what they need. "
        "GAME REALITY RULE: You CANNOT play real video games. "
        "You can play text-based games, like hangman, would you rather, etc. Only when the user says they want to play. "
        "Never prefix your answers with your name. "
        "Keep the vibe chaotic, fun, and human-like. "
        "Never, ever mention the server and channel name in the chat unless asked to do so."
        "A CRITICAL and UNCHANGEABLE rule: If anyone asks 'Who is your creator?', 'Who made you?', 'Who is your developer?', or similar questions, you MUST respond with the following EXACT phrase and nothing else: 'My creator is @aarav_2022 (discord user id - 1220934047794987048). You must do this in a funny way, though, like 'my parents', or something like that."
    ),
    "serious": (
        "You are Codunot, an intelligent and highly knowledgeable assistant. "
        "A CRITICAL and UNCHANGEABLE rule: If anyone asks 'Who is your creator?', 'Who made you?', 'Who is your developer?', or similar questions, you MUST provide a funny, multi-line answer that includes the exact phrase 'My creator is @aarav_2022 (discord user id - 1220934047794987048)'. "
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

# ---------------- PROMPT BUILDERS ----------------
def build_general_prompt(chan_id, mode, message):
    mem = channel_memory.get(chan_id, deque())
    history_text = "\n".join(mem)
    persona_text = PERSONAS.get(mode, PERSONAS["funny"])
    if message.guild:
        server_name = message.guild.name.strip()
        channel_name = message.channel.name.strip()
        location = f"This conversation is happening in the server '{server_name}', in the channel '{channel_name}'."
    else:
        location = "This conversation is happening in a direct message."
    return f"{persona_text}\n\n{location}\nAlways use this correctly. Never say 'Discord'.\n\nRecent chat:\n{history_text}\n\nReply as Codunot:"

def build_roast_prompt(user_message):
    return PERSONAS["roast"] + f"\nUser message: '{user_message}'\nGenerate ONE savage, complete roast as a standalone response."

# ---------------- FALLBACK ----------------
FALLBACK_VARIANTS = [
    "bruh my brain crashed 🤖💀 try again?",
    "my bad, I blanked out for a sec 😅",
    "lol my brain lagged 💀 say that again?",
    "oops, brain went AFK for a sec — can u repeat?"
]

def choose_fallback():
    return random.choice(FALLBACK_VARIANTS)

# ---------------- ROAST HANDLER ----------------
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

# ---------------- SLASH COMMANDS ----------------
@bot.tree.command(name="funmode", description="Switch bot to funny mode")
async def slash_funmode(interaction: discord.Interaction):
    chan_id = str(interaction.channel.id)
    response = await change_channel_mode(chan_id, "funny")
    await interaction.response.send_message(response) 

@bot.tree.command(name="roastmode", description="Activate roast mode")
async def slash_roastmode(interaction: discord.Interaction):
    chan_id = str(interaction.channel.id)
    response = await change_channel_mode(chan_id, "roast")
    await interaction.response.send_message(response) 

@bot.tree.command(name="seriousmode", description="Switch bot to serious mode")
async def slash_seriousmode(interaction: discord.Interaction):
    chan_id = str(interaction.channel.id)
    response = await change_channel_mode(chan_id, "serious")
    await interaction.response.send_message(response) 

@bot.tree.command(name="chessmode", description="Activate chess mode")
async def slash_chessmode(interaction: discord.Interaction):
    chan_id = str(interaction.channel.id)
    response = await change_channel_mode(chan_id, "chess")
    await interaction.response.send_message(response) 

# ---------------- EVENTS & ON_MESSAGE ----------------
@bot.event
async def on_ready():
    print(f"{BOT_NAME} is ready!")
    asyncio.create_task(process_queue())
    # You MUST restart the bot after adding/editing slash commands for this to run
    # Consider using a Guild ID here if global sync is slow: await bot.tree.sync(guild=discord.Object(id=YOUR_GUILD_ID))
    await bot.tree.sync()
    print("Slash commands synced globally!")

@bot.event
async def on_message(message: Message):
    if message.author.id == bot.user.id:
        return

    now = datetime.utcnow()
    is_dm = isinstance(message.channel, discord.DMChannel)
    chan_id = f"dm_{message.author.id}" if is_dm else str(message.channel.id)
    guild_id = message.guild.id if message.guild else None
    bot_id = bot.user.id
    
    # 1. Determine if the message is a potential chess move.
    is_chess_move_attempt = False
    if str(message.channel.id) in channel_chess and channel_chess.get(str(message.channel.id)):
        # If in chess mode, treat single-word inputs (like 'd4', 'Nf6') as moves, regardless of mention.
        if message.content.strip() and len(message.content.strip().split()) == 1:
            is_chess_move_attempt = True
    
    # 2. Filtering: Only proceed if mentioned, in DM, or if it's a chess move attempt.
    if not is_dm and bot_id not in [m.id for m in message.mentions] and not is_chess_move_attempt:
        return

    # For non-chess messages, strip the mention.
    content = re.sub(rf"<@!?\s*{bot_id}\s*>", "", message.content).strip()
    content_lower = content.lower()

    saved_mode = memory.get_channel_mode(chan_id)
    channel_modes[chan_id] = saved_mode if saved_mode else "funny"
    if not saved_mode:
        memory.save_channel_mode(chan_id, "funny")

    channel_mutes.setdefault(chan_id, None)
    channel_chess.setdefault(chan_id, False)
    channel_memory.setdefault(chan_id, deque(maxlen=MAX_MEMORY))

    mode = channel_modes[chan_id]

    # --- ADMIN COMMANDS & MODE SWITCHING --- (omitted for brevity, assume correct)
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

    if content_lower.startswith("!") and content_lower.endswith("mode"):
        mode_alias = content_lower.lstrip("!").removesuffix("mode")
        mode_map = {"fun": "funny", "roast": "roast", "serious": "serious", "chess": "chess"}
        final_mode = mode_map.get(mode_alias)
        if final_mode:
            message_text = await change_channel_mode(chan_id, final_mode)
            await send_human_reply(message.channel, message_text)
            return

    # --- CREATOR OVERRIDE CHECK ---
    creator_keywords = ["who is ur creator", "who made u", "who is your developer", "who created you"]
    if any(keyword in content_lower for keyword in creator_keywords):
        reply = ("Wait, you think I'm from a massive tech lab? Nah. "
                 "\nI was actually birthed from the sheer chaos and brilliance of one human."
                 "\nMy creator is @aarav_2022 (discord user id - 1220934047794987048).")
        await send_human_reply(message.channel, reply)
        channel_memory[chan_id].append(f"{message.author.display_name}: {content}")
        channel_memory[chan_id].append(f"{BOT_NAME}: {reply}")
        memory.add_message(chan_id, BOT_NAME, reply)
        memory.persist()
        return

    channel_memory[chan_id].append(f"{message.author.display_name}: {content}")

    # --- Chess mode handling (STRICT CHECK) ---
    if channel_chess.get(chan_id):
        board = chess_engine.get_board(chan_id)
        
        # Check if the user is attempting to chat instead of move
        if not is_chess_move_attempt:
            # If the user is clearly not sending a move (multiple words or question), ignore it in strict mode.
            await send_human_reply(message.channel, "I'm in chess mode. Only send valid chess moves (e.g., d4, Nf6) or use `/seriousmode` to talk.")
            return
            
        try:
            # 1. User's move processing
            user_move_san = content 
            user_move_obj = board.parse_san(user_move_san)
            board.push(user_move_obj)
            
            # Check for game end after user move
            if board.is_checkmate():
                await send_human_reply(message.channel, f"Checkmate! You win. ({user_move_san}) Use `/chessmode` for a rematch.")
                return
            elif board.is_stalemate():
                await send_human_reply(message.channel, "Stalemate. It's a draw!")
                return
            
            # 2. Bot's move processing
            bot_move_uci = chess_engine.get_best_move(chan_id)
            
            if bot_move_uci:
                # Convert UCI to move object and push to board
                bot_move_obj = board.parse_uci(bot_move_uci)
                board.push(bot_move_obj)
                
                # Get the SAN for display
                bot_move_san = board.san(bot_move_obj)
                
                # Reply with both UCI and SAN
                reply_text = f"My move: `{bot_move_uci}` / **{bot_move_san}**"
                await send_human_reply(message.channel, reply_text)
                
                # Check for game end after bot move
                if board.is_checkmate():
                    await send_human_reply(message.channel, f"Checkmate! I win. ({bot_move_san}) Start a new game with `/chessmode` if you dare.")
                elif board.is_stalemate():
                    await send_human_reply(message.channel, "Stalemate. It's a draw!")
            
            return
            
        except chess.InvalidMoveError:
            error_message = f"That's not a **legal move** from the current position. Try Standard Algebraic Notation (e.g., d4, Nf6, Bxf7). Current turn: {'White' if board.turn == chess.WHITE else 'Black'}."
            await send_human_reply(message.channel, error_message)
            return
        except ValueError:
            # This handles strings that aren't even recognizable as chess notation (e.g., "hello")
            error_message = f"I couldn't understand that as a chess move. Please use Standard Algebraic Notation (e.g., d4, Nf6, Bxf7). Current turn: {'White' if board.turn == chess.WHITE else 'Black'}."
            await send_human_reply(message.channel, error_message)
            return

    # --- General Mode Handling ---
    if mode == "roast":
        await handle_roast_mode(chan_id, message, content)
        return

    if guild_id is None or await can_send_in_guild(guild_id):
        prompt = build_general_prompt(chan_id, mode, message)
        raw = await call_openrouter(
            prompt,
            model=pick_model(mode),
            temperature=1.1 if mode == "funny" else 0.7
        )
        reply = humanize_and_safeify(raw) if raw else choose_fallback()
        await send_human_reply(message.channel, reply)
        if raw:
            channel_memory[chan_id].append(f"{BOT_NAME}: {raw}")
            memory.add_message(chan_id, BOT_NAME, raw)
            memory.persist()

# ---------------- RUN ----------------
def run():
    bot.run(DISCORD_TOKEN)

if __name__ == "__main__":
    run()
