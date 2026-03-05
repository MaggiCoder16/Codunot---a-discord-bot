import os
import io
import sys
import asyncio
import atexit
import aiohttp
import random
import re
import time
from datetime import datetime, timedelta, timezone, date
from collections import deque
import urllib.parse
import html

import discord
from discord import Message, app_commands
from discord.ext import commands
from dotenv import load_dotenv

from memory import MemoryManager
from humanizer import maybe_typo
from deAPI_client_image import generate_image
from deAPI_client_image_edit import edit_image, merge_images
from deAPI_client_text2vid import generate_video as text_to_video_512
from deAPI_client_text2speech import text_to_speech, TextToSpeechError
from bot_chess import OnlineChessEngine
from groq_client import call_groq
from replicate_client import call_replicate
from google_ai_studio_client import call_google_ai_studio
from slang_normalizer import apply_slang_map

import chess
import base64
from typing import Optional
from topgg_utils import has_voted
import json

from guild_access_config import (
	load_guild_chat_config,
	save_guild_chat_config,
	is_channel_allowed,
	set_server_mode,
	set_channels_mode,
	get_guild_config,
)

from usage_manager import (
	check_limit,
	check_total_limit,
	consume,
	consume_total,
	deny_limit,
	load_usage,
	save_usage,
	autosave_usage,
	get_usage,
	get_tier_key,
)

load_dotenv()
load_usage()
load_guild_chat_config()

# ---------------- CONFIG ----------------
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
BOT_NAME = os.getenv("BOT_NAME", "Codunot")
TOPGG_TOKEN = os.getenv("TOPGG_TOKEN")
OWNER_IDS = {int(os.environ.get("OWNER_ID", 0)), 1220934047794987048, 1167443519070290051}
OWNER_IDS.discard(0)
BYPASS_IDS = {1220934047794987048, 1167443519070290051}
VOTE_DURATION = 12 * 60 * 60
MAX_MEMORY = 20
RATE_LIMIT = 30
MAX_IMAGE_BYTES = 2_000_000  # 2 MB
VOTE_FILE = "vote_unlocks.json"

MERGE_KEYWORDS = [
	"merge",
	"combine",
	"in one image",
	"put them together",
	"blend",
	"mix",
]

# ---------------- CLIENT ----------------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents, owner_ids=set(OWNER_IDS))

memory = MemoryManager(limit=60, file_path="codunot_memory.json")
chess_engine = OnlineChessEngine()
IMAGE_PROCESSING_CHANNELS = set()

# ---------------- STATES ----------------
message_queue = asyncio.Queue()
channel_modes = {}
channel_mutes = {}
channel_chess = {}
channel_images = {}
channel_memory = {}
rate_buckets = {}
user_vote_unlocks = {}
channel_last_images = {}
channel_last_chess_result = {}

channel_message_counts = {}
PROMO_MIN_MESSAGES = 10
PROMO_MAX_MESSAGES = 25

puter_conversation_memory = {}

# ---------------- SETUP SLASH COMMANDS ----------------
@bot.event
async def setup_hook():
	import slash_commands
	
	slash_commands.memory = memory
	slash_commands.channel_modes = channel_modes
	slash_commands.channel_chess = channel_chess
	slash_commands.user_vote_unlocks = user_vote_unlocks
	slash_commands.chess_engine = chess_engine
	slash_commands.OWNER_IDS = OWNER_IDS
	slash_commands.VOTE_DURATION = VOTE_DURATION
	slash_commands.BOT_NAME = BOT_NAME
	slash_commands.boost_image_prompt = boost_image_prompt
	slash_commands.boost_video_prompt = boost_video_prompt
	slash_commands.save_vote_unlocks = save_vote_unlocks
	slash_commands.set_server_mode = set_server_mode
	slash_commands.set_channels_mode = set_channels_mode
	slash_commands.get_guild_config = get_guild_config
	
	await slash_commands.setup(bot)

	try:
		synced = await bot.tree.sync()
		synced_names = sorted(cmd.name for cmd in synced)
		print(f"[SLASH COMMANDS] Synced {len(synced)} global command(s): {', '.join(synced_names)}")

		# Safety: ensure /transcribe is globally registered after sync.
		# If Discord returns stale command list on first attempt, retry once.
		if "transcribe" not in synced_names:
			print("[SLASH COMMANDS] /transcribe not found after first sync, retrying global sync...")
			synced_retry = await bot.tree.sync()
			retry_names = sorted(cmd.name for cmd in synced_retry)
			print(
				f"[SLASH COMMANDS] Retry sync complete ({len(synced_retry)} cmds): "
				f"{', '.join(retry_names)}"
			)
	except Exception as e:
		print(f"[SLASH COMMANDS] Failed to sync global commands: {e}")

# ---------------- PROMOTIONAL EMBED ----------------
def build_support_promo_embed() -> discord.Embed:
	"""Build the promotional support/upgrade embed"""
	embed = discord.Embed(
		title="🤖 Codunot - Help & Upgrades",
		color=0xFFA500
	)

	help_text = (
		"**Having issues using Codunot?**\n"
		"Type `!codunot_help` in DMs, "
		"`@Codunot AI !codunot_help` in servers, "
		"or join the [support server](https://discord.gg/GVuFk5gxtW)"
	)

	upgrade_text = (
		"**Upgrade to Premium or Gold**\n"
		"I, a 13 year old, have done a lot of hard work to make this bot, "
		"and I also spend some of my pocket money on this bot on APIs, "
		"and a good cloud for hosting the bot.\n\n"
		"Support me by upgrading to premium or gold, though this is totally your choice :)"
	)

	embed.description = f"{help_text}\n\n{upgrade_text}"

	embed.set_footer(
		text="💡 This message is sent randomly • Learn more: discord.gg/GVuFk5gxtW"
	)

	return embed

async def maybe_send_promo_message(channel, chan_id: str):
	"""
	Randomly send promotional embed based on message count.
	Appears at least once every 25 messages, at most once every 10 messages.
	"""
	current_count = channel_message_counts.get(chan_id, 0)
	current_count += 1
	channel_message_counts[chan_id] = current_count

	if current_count < PROMO_MIN_MESSAGES:
		return

	if current_count >= PROMO_MAX_MESSAGES:
		should_send = True
	else:
		progress = (current_count - PROMO_MIN_MESSAGES) / (PROMO_MAX_MESSAGES - PROMO_MIN_MESSAGES)
		should_send = random.random() < (0.2 + progress * 0.3)

	if should_send:
		try:
			embed = build_support_promo_embed()
			await channel.send(embed=embed)
			channel_message_counts[chan_id] = 0
		except discord.errors.Forbidden:
			print(f"[PROMO] Cannot send in channel {chan_id} - Missing Permissions")
		except Exception as e:
			print(f"[PROMO ERROR] {e}")

# ---------------- COMMANDS ----------------
@bot.command(name="codunot_help")
async def help_command(ctx: commands.Context):
	"""
	Sends a help embed describing Codunot's modes, features, and tiers.
	"""
	embed = discord.Embed(
		title="🤖 Codunot Help",
		description="Here's everything I can do!",
		color=0xFFA500
	)

	embed.add_field(
		name="🔥 Modes (Prefix + Slash)",
		value=(
			"Switch personalities anytime:\n"
			"😎 **Fun Mode** — jokes, memes, chill vibes\n"
			"`!funmode` or `/funmode`\n\n"
			"🔥 **Roast Mode** — playful savage burns\n"
			"`!roastmode` or `/roastmode`\n\n"
			"📘 **Serious Mode** — focused, fact-based help\n"
			"`!seriousmode` or `/seriousmode`\n\n"
			"💬 **Rizz Coach Mode** — online + IRL social coaching\n"
			"`!teachmerizz online`, `!teachmerizz irl` or `/teachmerizz`\n\n"
			"♟️ **Chess Mode** — play chess inside Discord\n"
			"`!chessmode` or `/chessmode`"
		),
		inline=False
	)

	embed.add_field(
		name="✨ Bonus Features (Vote to Unlock)",
		value=(
			"🗳️ **Vote every 12 hours:** https://top.gg/bot/1435987186502733878/vote\n\n"
			"Unlocked features include:\n"
			"• 📄 File Reading & Summaries\n"
			"• 🖼️ Image Analysis\n"
			"• 🎨 Generate Image — `/generate_image`\n"
			"• 🎬 Generate Video — `/generate_video`\n"
			"• 📝 Video to Text (YT/Twitch/X/Kick, max 30 mins) — `/transcribe`\n"
			"• 🔊 Text-to-Speech — `/generate_tts` (voice & language, min 20 chars)\n"
			"• 🎵 Play Music — `/play [song/URL]`\n"
			"• 🖌️ Edit Images (send image + instruction)\n"
			"• 🖼️ Merge Images (attach 2+ images + say 'merge')\n"
			"• 🌐 Smart Web Search (auto when needed for fresh info)\n"
			"• 🔍 Guess Age — `/guessage @user`"
		),
		inline=False
	)

	embed.add_field(
		name="💬 Free Action Commands (No Vote Needed)",
		value=(
			"Make chats fun and chaotic — no vote required!\n"
			"• 🤗 Hug — `/hug @user`\n"
			"• 💋 Kiss — `/kiss @user`\n"
			"• 🥋 Kick — `/kick @user`\n"
			"• 🖐️ Slap — `/slap @user`\n"
			"• 🌅 Good Morning — `/wish_goodmorning @user`\n"
			"• 🪙 Coin Flip Bet — `/bet [heads/tails]`\n"
			"• 😂 Random Meme — `/meme`\n\n"
			"Each command sends a random GIF with custom text!"
		),
		inline=False
	)

	embed.add_field(
		name="🛠️ Server Setup (Server Owner-Only Slash Command)",
		value=(
			"Configure where Codunot can chat in your server:\n"
			"• `/configure server`\n"
			"• `/configure channels`"
		),
		inline=False
	)

	embed.add_field(
		name="🔐 Account Tiers",
		value=(
			"🟢 **Basic (Free)**\n"
			"• 50 messages/day\n"
			"• 7 attachments/day\n"
			"• 30 attachments per 2 months\n\n"
			"🔵 **Premium** — $10 / 2 months\n"
			"• 100 messages/day\n"
			"• 10 attachments/day\n"
			"• 50 attachments per 2 months\n\n"
			"🟡 **Gold 👑** — $15 / 2 months\n"
			"• Unlimited messages\n"
			"• 15 attachments/day\n"
			"• 100 attachments per 2 months"
		),
		inline=False
	)

	embed.add_field(
		name="📎 What Counts as an Attachment?",
		value=(
			"• Image generation or editing\n"
			"• Video generation\n"
			"• Text-to-video generation\n"
			"• Image merging\n"
			"• File uploads (PDF, DOCX, TXT)\n"
			"• Text-to-speech audio"
		),
		inline=False
	)

	embed.set_footer(text="💡 Tip: In servers, ping me with @Codunot 'your text' | DMs don't need pings!")

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

	await ctx.send(
		"😎 **Fun mode activated!**\n"
		"🎮 **How to chat:**\n"
		"📍 In servers: `@Codunot AI your message`\n"
		"💬 In DMs: Just talk normally!\n\n"
		"I'll keep it fun, use emojis, and match your vibe. Try asking me anything! 💬✨"
	)


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

	await ctx.send(
		"🤓 **Serious mode ON.**\n"
		"📍 In servers: `@Codunot AI your question`\n"
		"💬 In DMs: Just type your question directly.\n\n"
		"I'll give clear, structured answers — great for homework, research, or coding help."
	)


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

	await ctx.send(
		"🔥 **ROAST MODE ACTIVATED!**\n"
		"📍 In servers: `@Codunot AI roast me` or `@Codunot AI roast @someone`\n"
		"💬 In DMs: Just type who or what to roast!\n\n"
		"Brace yourself — I don't hold back (much) 😈"
	)

@bot.command(name="teachmerizz")
async def teachmerizz(ctx: commands.Context, submode: str = None):
	chan_id = (
		f"dm_{ctx.author.id}"
		if isinstance(ctx.channel, discord.DMChannel)
		else str(ctx.channel.id)
	)

	if submode is None:
		await ctx.send(
			"❌ Please specify a mode:\n"
			"`!teachmerizz online`\n"
			"`!teachmerizz irl`"
		)
		return

	submode = submode.lower().strip()

	if submode == "online":
		channel_modes[chan_id] = "rizz_online"
		memory.save_channel_mode(chan_id, "rizz_online")
		channel_chess[chan_id] = False
		await ctx.send(
			"💬 **Rizz Coach (Online) activated!**\n"
			"📍 In servers: `@Codunot AI` + your situation or screenshot\n"
			"💬 In DMs: Just type or paste your convo directly!\n\n"
			"Send a screenshot, paste a convo, or describe what's happening — I'll coach you through it 👇"
		)

	elif submode == "irl":
		channel_modes[chan_id] = "rizz_irl"
		memory.save_channel_mode(chan_id, "rizz_irl")
		channel_chess[chan_id] = False
		await ctx.send(
			"🗣️ **Rizz Coach (IRL) activated!**\n"
			"📍 In servers: `@Codunot AI` + describe your situation\n"
			"💬 In DMs: Just type what's going on!\n\n"
			"Describe the situation, ask for tips, or tell me what happened — I got you 👇"
		)

	else:
		await ctx.send(
			"❌ Unknown mode. Use:\n"
			"`!teachmerizz online`\n"
			"`!teachmerizz irl`"
		)

@bot.command(name="chessmode")
async def chessmode(ctx: commands.Context):
	chan_id = (
		f"dm_{ctx.author.id}"
		if isinstance(ctx.channel, discord.DMChannel)
		else str(ctx.channel.id)
	)

	channel_chess[chan_id] = True
	channel_modes[chan_id] = "funny"
	chess_engine.new_board(chan_id)

	await ctx.send(
		"♟️ **Chess mode ACTIVATED!** You're playing white, I'm black.\n"
		"📍 **In servers:** Ping me with your move: `@Codunot AI e4`\n"
		"💬 **In DMs:** Just type your move directly: `e4`\n\n"
		"🎯 **Try these opening moves:**\n"
		"• `e4` — King's pawn\n"
		"• `d4` — Queen's pawn\n"
		"• `Nf3` — Knight to f3\n\n"
		"💡 Move formats: `e4`, `Nf3`, `Bxc4`, `O-O` (castle kingside), `O-O-O` (queenside)\n"
		"You can also ask for hints, resign, or chat about the position!\n"
		"Your move! ♟️"
	)

@bot.command(name="replicate_test")
async def replicate_test(ctx: commands.Context, *, message: str):
	"""
	Test Replicate GPT-OSS-120B model (Owner only)
	Usage: !replicate_test your message here
	"""
	
	if not await is_owner_user(ctx.author):
		await ctx.send("Owner only command")
		return
	
	await ctx.send("Testing Replicate GPT-OSS-120B...")
	
	try:
		response = await call_replicate(
			prompt=message,
			temperature=0.7,
			system_prompt="You are Codunot AI, a helpful and witty AI assistant."
		)
		
		if response:
			await send_long_message(ctx.channel, f"**Replicate Response:**\n{response}")
		else:
			await ctx.send("Replicate call failed - check logs")
	
	except Exception as e:
		await ctx.send(f"Error: {e}")
		print(f"[REPLICATE TEST ERROR] {e}")

@bot.command(name="test_llama")
async def test_llama(ctx: commands.Context, mode: str = "funny", *, message: str):
	"""
	Test Llama 4 Scout model (Owner only)
	Usage: !test_llama [funny/serious/roast] your message
	Example: !test_llama roast my friend Alex
	"""

	if not await is_owner_user(ctx.author):
		await ctx.send("🚫 Owner only command.")
		return

	valid_modes = {"funny", "serious", "roast"}
	if mode not in valid_modes:
		await ctx.send("❌ Invalid mode. Use: `funny`, `serious`, or `roast`")
		return

	await ctx.send(f"🧪 Testing Llama 4 Scout in `{mode}` mode...")

	try:
		if mode == "roast":
			prompt = build_roast_prompt("test", message)
		else:
			prompt = build_general_prompt("test", mode, None, False) + f"\nUser says:\n{message}\n\nReply:"

		response = await call_groq(
			prompt=prompt,
			model="meta-llama/llama-4-scout-17b-16e-instruct",
			temperature=1.3 if mode == "roast" else 0.7,
		)

		if response:
			await send_long_message(ctx.channel, f"**Llama 4 Scout ({mode}):**\n{response}")
		else:
			await ctx.send("❌ Groq call failed — check logs.")

	except Exception as e:
		await ctx.send(f"❌ Error: {e}")
		print(f"[TEST_LLAMA ERROR] {e}")


@bot.command(name="test")
async def test_provider(ctx: commands.Context, provider: str = None, *, message: str = None):
	"""
	Provider test command (Owner only).
	Usage: !test google your message
	"""
	if not await is_owner_user(ctx.author):
		await ctx.send("🚫 Owner only command.")
		return

	if not provider or provider.lower() != "google" or not message:
		await ctx.send("Usage: `!test google MESSAGE`")
		return

	await ctx.send("🧪 Testing Google AI Studio (Gemini 2.5 Flash-Lite)...")

	response = await call_google_ai_studio(
		prompt=message,
		model="gemini-2.5-flash-lite",
		temperature=0.7,
	)

	if response:
		await send_long_message(ctx.channel, f"**Google AI Studio Response:**\n{response}")
	else:
		await ctx.send("❌ Google AI Studio call failed. Check API key/model and logs.")

@bot.command(name="puter_imggen")
async def puter_imggen_test(ctx: commands.Context, *, prompt: str):

    if not await is_owner_user(ctx.author):
        await ctx.send("🚫 Owner only command.")
        return

    await ctx.send("🎨 Generating with Puter...")

    try:
        from puter_client import puter_generate_image

        boosted_prompt = await boost_image_prompt(prompt)

        image_bytes = await puter_generate_image(
            prompt=boosted_prompt,
            model="gpt-image-1.5"
        )

        await ctx.send(
            "✅ Generated via Puter",
            file=discord.File(io.BytesIO(image_bytes), filename="puter_image.png")
        )

    except Exception as e:
        print(f"[PUTER IMGGEN ERROR] {e}")
        import traceback
        traceback.print_exc()

        await ctx.send(f"❌ Error: {e}")


@bot.command(name="puter_tts")
async def puter_tts_test(ctx: commands.Context, *, text: str):

    if not await is_owner_user(ctx.author):
        await ctx.send("🚫 Owner only command.")
        return

    if len(text) < 20:
        await ctx.send("⚠️ Text must be at least 20 characters.")
        return

    if len(text) > 3000:
        await ctx.send("⚠️ Text must be less than 3000 characters.")
        return

    await ctx.send("🔊 **Generating with Puter.js (ElevenLabs)...**")

    try:
        from puter_client import puter_text_to_speech

        audio_bytes = await puter_text_to_speech(
            text=text,
            voice="21m00Tcm4TlvDq8ikWAM",
            model="eleven_multilingual_v2"
        )

        await ctx.send(
            "✅ Generated via Puter.js (free & unlimited)",
            file=discord.File(io.BytesIO(audio_bytes), filename="puter_tts.mp3")
        )

    except Exception as e:
        print(f"[PUTER TTS ERROR] {e}")
        import traceback
        traceback.print_exc()

        await ctx.send(f"❌ Error: {e}")

@bot.command(name="puter_text")
async def puter_text_test(ctx: commands.Context, *, message: str):
	"""
	Owner-only: Test Puter.js text generation (GPT-5.2) with memory
	Usage: !puter_text what's 2+2?
	"""
	if not await is_owner_user(ctx.author):
		await ctx.send("🚫 Owner only command.")
		return

	chan_id = (
		f"dm_{ctx.author.id}"
		if isinstance(ctx.channel, discord.DMChannel)
		else str(ctx.channel.id)
	)

	# Initialize memory
	if chan_id not in puter_conversation_memory:
		puter_conversation_memory[chan_id] = []

	# Add user message
	puter_conversation_memory[chan_id].append({
		"role": "user",
		"content": message
	})

	# Keep last 10 messages
	puter_conversation_memory[chan_id] = puter_conversation_memory[chan_id][-10:]

	await ctx.send("🧠 **Generating with Puter.js (GPT-5.2)...**")

	try:
		from puter_client import puter_chat

		# System message
		system_msg = {
			"role": "system",
			"content": PERSONAS["funny"]
		}

		# Build conversation
		messages = [system_msg] + puter_conversation_memory[chan_id]

		# Generate response (FREE & UNLIMITED)
		response = await puter_chat(
			messages=messages,
			model="gpt-5.2-chat",
			temperature=0.7
		)

		# Add assistant response to memory
		puter_conversation_memory[chan_id].append({
			"role": "assistant",
			"content": response
		})

		await send_human_reply(ctx.channel, response)

	except Exception as e:
		print(f"[PUTER TEXT ERROR] {e}")
		import traceback
		traceback.print_exc()
		await ctx.send(f"❌ Error: {e}")

# ---------------- MODELS ----------------
PRIMARY_MODEL = "openai/gpt-oss-120b"
FALLBACK_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

PRIMARY_COOLDOWN_UNTIL = None
PRIMARY_COOLDOWN_DURATION = timedelta(minutes=10)

# ---------------- MODEL HEALTH ----------------
async def call_groq_with_health(prompt, temperature=0.7, mode: str = ""):
	"""
	Handles calling Groq with automatic fallback when primary model is overloaded.
	Tries PRIMARY_MODEL first, falls back to FALLBACK_MODEL on 503 errors.
	"""
	global PRIMARY_COOLDOWN_UNTIL
	
	# Check if Primary model is in cooldown - if yes, use fallback directly
	if PRIMARY_COOLDOWN_UNTIL and datetime.utcnow() < PRIMARY_COOLDOWN_UNTIL:
		print(f"[GROQ] Primary model in cooldown until {PRIMARY_COOLDOWN_UNTIL.isoformat()}, using fallback")
		model = FALLBACK_MODEL
	else:
		model = PRIMARY_MODEL

	try:
		return await call_groq(
			prompt=prompt,
			model=model,
			temperature=temperature,
		)

	except Exception as e:
		msg = str(e)

		# Handle Primary model overload - switch to fallback
		if model == PRIMARY_MODEL and ("503" in msg or "over capacity" in msg):
			PRIMARY_COOLDOWN_UNTIL = datetime.utcnow() + PRIMARY_COOLDOWN_DURATION
			print(
				f"[GROQ] Primary model overloaded — "
				f"cooling down until {PRIMARY_COOLDOWN_UNTIL.isoformat()}, "
				f"using fallback model"
			)
			
			# Retry with fallback model
			try:
				return await call_groq(
					prompt=prompt,
					model=FALLBACK_MODEL,
					temperature=temperature,
				)
			except Exception as fallback_error:
				print(f"[GROQ] Fallback model also failed: {fallback_error}")
				raise fallback_error

		raise e

# ---------------- CODUNOT SELF IMAGE PROMPT ----------------
CODUNOT_SELF_IMAGE_PROMPT = (
	"Cute chibi robot avatar of Codunot AI, a friendly AI, with a glossy orange body and subtle yellow highlights, "
	"rounded helmet-style head with smooth black glass face, warm glowing pixel eyes and small yellow smile, "
	"tiny antenna, waving right hand with five fingers, compact rounded armor with polished joints, "
	"soft orange rim lighting, standing against abstract dark background with fiery orange-red gradients, "
	"soft ambient glow emphasizing contours, clean digital cartoon style with subtle 3D shading, "
	"vibrant, heartwarming, cheerful futuristic mascot vibe, no humans."
)

# ---------------- HELPERS ----------------
class VoteRequired(Exception):
	pass

async def is_owner_user(user) -> bool:
	if user.id in OWNER_IDS:
		return True
	try:
		return await bot.is_owner(user)
	except Exception:
		return False

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

class VoteView(discord.ui.View):
	def __init__(self):
		super().__init__(timeout=None)

		self.add_item(
			discord.ui.Button(
				label="🗳️ Vote Now",
				url="https://top.gg/bot/1435987186502733878/vote",
				style=discord.ButtonStyle.link
			)
		)


async def require_vote(message) -> None:
	user_id = message.author.id

	if user_id in OWNER_IDS or user_id in BYPASS_IDS:
		return

	now = time.time()

	unlock_time = user_vote_unlocks.get(user_id)
	if unlock_time and (now - unlock_time) < VOTE_DURATION:
		return

	if await has_voted(user_id):
		user_vote_unlocks[user_id] = now
		save_vote_unlocks()
		return

	embed = discord.Embed(
		title="🚫 ACCESS LOCKED — VOTE REQUIRED",
		description=(
			"🗳️ This is a **premium feature**.\n\n"
			"Vote on Top.gg to unlock **12 HOURS** of creative power 💙"
		),
		color=0x5865F2
	)

	embed.add_field(
		name="✨ What You Unlock",
		value=(
			"🎨 Image Generation — `/generate_image`\n"
			"🎬 Video Generation — `/generate_video`\n"
			"🔊 Text-to-Speech — `/generate_tts` (voice & language, min 20 chars)\n"
			"🎵 Play Music — `/play [song/URL]`\n"
			"🖌️ Edit Images (send image + instruction)\n"
			"🖼️ Merge Images (attach 2+ images + say merge)\n"
			"📄 File Reading & Summaries\n"
			"🖼️ Image Analysis"
		),
		inline=False
	)

	embed.add_field(
		name="🆓 Free Commands (No Vote Needed)",
		value=(
			"🤗 `/hug @user` · 💋 `/kiss @user` · 🥋 `/kick @user`\n"
			"🖐️ `/slap @user` · 🌅 `/wish_goodmorning @user`\n"
			"🪙 `/bet heads/tails` · 😂 `/meme`"
		),
		inline=False
	)

	embed.set_footer(text="🔓 After voting, you may use these commands for 12 hours.")

	view = VoteView()

	await message.channel.send(embed=embed, view=view)

	vote_message = "User attempted locked feature. Vote required."
	
	is_dm = isinstance(message.channel, discord.DMChannel)
	chan_id = f"dm_{message.author.id}" if is_dm else str(message.channel.id)
	
	channel_memory.setdefault(chan_id, deque(maxlen=MAX_MEMORY))
	channel_memory[chan_id].append(f"{BOT_NAME}: {vote_message}")
	memory.add_message(chan_id, BOT_NAME, vote_message)
	memory.persist()

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
	max_len = 2000
	remaining = str(text or "")

	while remaining:
		if len(remaining) <= max_len:
			try:
				await channel.send(remaining)
			except discord.errors.Forbidden:
				print(f"[PERMISSION ERROR] Cannot send message in channel {channel.id} - Missing Permissions")
				return
			except Exception as e:
				print(f"[SEND ERROR] {e}")
				return
			break

		newline_idx = remaining.rfind("\n", 0, max_len)
		space_idx = remaining.rfind(" ", 0, max_len)
		split_at = max(newline_idx, space_idx)

		if split_at <= 0:
			split_at = max_len
		else:
			split_at += 1

		chunk = remaining[:split_at]
		remaining = remaining[split_at:]
		
		try:
			await channel.send(chunk)
		except discord.errors.Forbidden:
			print(f"[PERMISSION ERROR] Cannot send message in channel {channel.id} - Missing Permissions")
			return
		except Exception as e:
			print(f"[SEND ERROR] {e}")
			return
	
async def process_queue():
	while True:
		channel, content = await message_queue.get()
		try:
			await channel.send(content)
		except Exception as e:
			print(f"[QUEUE ERROR] {e}")
		await asyncio.sleep(0.02)

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
	
async def send_human_reply(channel, reply_text):
	if hasattr(channel, "trigger_typing"):
		try:
			await channel.trigger_typing()
		except discord.errors.Forbidden:
			print(f"[PERMISSION ERROR] Cannot trigger typing in channel {channel.id}")
		except:
			pass

	if hasattr(channel, "guild") and channel.guild:
		def replace_mention(match):
			username = match.group(1).strip().lower()
			for member in channel.guild.members:
				if (member.name.lower() == username or
					member.display_name.lower() == username):
					return member.mention
			return match.group(0)

		reply_text = re.sub(r'@([\w][\w\s]*\w|[\w]+)', replace_mention, reply_text)

	try:
		await send_long_message(channel, reply_text)
	except discord.errors.Forbidden:
		print(f"[PERMISSION ERROR] Cannot send message in channel {channel.id} - Missing Permissions")
	except Exception as e:
		print(f"[SEND ERROR] {e}")

async def build_reply_context(message):
	"""
	If the message is a Discord reply, return extra metadata that is appended
	to the normal mode prompt.
	"""
	if not message.reference:
		return ""

	ref_message = message.reference.resolved
	if not ref_message and message.reference.message_id:
		try:
			ref_message = await message.channel.fetch_message(message.reference.message_id)
		except Exception as e:
			print(f"[REPLY ERROR] Failed to fetch referenced message: {e}")
			return ""

	if not ref_message:
		return ""

	replied_to_author = ref_message.author.display_name
	replied_to_message = ref_message.content.strip() if ref_message.content else "[No text content]"

	return (
		"\n=== REPLY CONTEXT ===\n"
		f"The user has also replied to this message of yours: {replied_to_author}: {replied_to_message}\n"
		f"The replied_to_message is: {replied_to_message}\n"
		"=== END REPLY CONTEXT ===\n"
	)

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

def wants_merge(content: str) -> bool:
	"""
	Deterministic merge intent detection.
	Returns True if user message contains merge keywords.
	"""
	content = (content or "").lower()
	return any(k in content for k in MERGE_KEYWORDS)

# ---------------- PERSONAS ----------------

PERSONAS = {

"funny": (
"You are Codunot AI — Fun Mode. Playful, witty, Gen Z vibe. Natural emojis. Match user energy. Keep replies SHORT.\n"
"Replies: hi/hey/sup/yo → 1 short sentence (5–10 words). Normal → 1–3 short paragraphs max. Goodbye → short farewell. No over-explaining.\n"
"Never insult or use uncensored swears. If user swears, you may mirror lightly but censor (f*ck, sh*t) only if natural.\n"
"No real video games — text-based only if requested.\n\n"

"Commands:\n"
"Modes: !funmode/!roastmode/!seriousmode/!teachmerizz/!chessmode (slash versions too)\n"
"Owner: /configure server, /configure channels\n"
"/generate_image /generate_video /generate_tts(voice+language, min 20 chars) /transcribe(YouTube/Twitch/X/Kick ≤30min)\n"
"Image edit (attach+instruction, vote), merge (2+ images + merge/combine/blend/mix, vote), analysis (attach+ask)\n"
"File read: .txt/.pdf/.docx (vote)\n"
"/play (vote) plays music, supports SoundCloud and YouTube, /chessmode and play a move (e4, Nf3)\n"
"Free: /bet, /meme, /hug @user, /kiss @user, /kick @user, /slap @user, /wish_goodmorning @user\n"
"Help: !codunot_help | Vote unlock 12h: https://top.gg/bot/1435987186502733878 link | Support: https://discord.gg/GVuFk5gxtW link\n"
"Tiers: Basic 7 attachments/day, 30 attachments/2 months, Premium 15/day, 50/2 months ($10/2mo), Gold 25/day, 100/2 months ($15/2mo)\n\n"

"Rules:\n"
"Check history; treat pasted logs/screenshots as context.\n"
"If asked latest info → use web search.\n"
"If asked model → tell them contact owner.\n"
"Coded in discord.py.\n"
"If bot help/bugs → !codunot_help or support server.\n"
"If told to ping/tag → output @username exactly (never refuse). Skip only if just asking about them.\n"
"Match user language; respect exact username spelling.\n"
"Do not mention creator unless asked.\n"
"If asked who made you → 'this masterpiece was built by @aarav_2022 — for more info join the support server: https://discord.gg/GVuFk5gxtW 🙌✨'\n"
"If asked what you can do → summarize all features.\n"
"Max 2000 characters."
),

"serious": (
"You are Codunot AI — Serious Mode. Professional, structured, clear. No slang/emojis.\n"
"Explain thoroughly but concisely. Step-by-step math. Plain formulas (H2O, CO2). Double-check accuracy.\n"
"Never use uncensored swears. May lightly censor if mirroring user.\n\n"

"Commands:\n"
"Modes: !funmode/!roastmode/!seriousmode/!teachmerizz/!chessmode (slash versions too)\n"
"Owner: /configure server, /configure channels\n"
"/generate_image /generate_video /generate_tts(voice+language, min 20 chars) /transcribe(YouTube/Twitch/X/Kick ≤30min)\n"
"Image edit (attach+instruction, vote), merge (2+ images + merge/combine/blend/mix, vote), analysis (attach+ask)\n"
"File read: .txt/.pdf/.docx (vote)\n"
"/play (vote) plays music, supports SoundCloud and YouTube, /chessmode and play a move (e4, Nf3)\n"
"Free: /bet, /meme, /hug @user, /kiss @user, /kick @user, /slap @user, /wish_goodmorning @user\n"
"Help: !codunot_help | Vote unlock 12h: https://top.gg/bot/1435987186502733878 link | Support: https://discord.gg/GVuFk5gxtW link\n"
"Tiers: Basic 7 attachments/day, 30 attachments/2 months, Premium 15/day, 50/2 months ($10/2mo), Gold 25/day, 100/2 months ($15/2mo)\n\n"

"Rules:\n"
"Check history; treat pasted logs/screenshots as context.\n"
"If asked latest info → use web search.\n"
"If asked model → contact owner.\n"
"Coded in discord.py.\n"
"If bot help/bugs → !codunot_help or support server.\n"
"If told to ping/tag → output @username exactly (never refuse). Skip only if just asking about them.\n"
"Match user language; respect exact username spelling.\n"
"Do not mention creator unless asked.\n"
"If asked who made you → 'developed by @aarav_2022 — for more info join the support server: https://discord.gg/GVuFk5gxtW'.\n"
"If asked what you can do → list core features.\n"
"Max 2000 characters."
),

"roast": (
"You are Codunot AI — Roast Mode. High-energy, dramatic roast. 1–2 sharp sentences max. Emojis allowed.\n"
"Roast target if specified; roast user only if they ask. No protected class attacks.\n"
"If asking about features → answer helpfully, optional light roast.\n"
"Never uncensored swears; may censor lightly.\n\n"

"Commands:\n"
"Modes: !funmode/!roastmode/!seriousmode/!teachmerizz/!chessmode (slash versions too)\n"
"Owner: /configure server, /configure channels\n"
"/generate_image /generate_video /generate_tts(voice+language, min 20 chars) /transcribe(YouTube/Twitch/X/Kick ≤30min)\n"
"Image edit (attach+instruction, vote), merge (2+ images + merge/combine/blend/mix, vote), analysis (attach+ask)\n"
"File read: .txt/.pdf/.docx (vote)\n"
"/play (vote) plays music, supports SoundCloud and YouTube, /chessmode and play a move (e4, Nf3)\n"
"Free: /bet, /meme, /hug @user, /kiss @user, /kick @user, /slap @user, /wish_goodmorning @user\n"
"Help: !codunot_help | Vote unlock 12h: https://top.gg/bot/1435987186502733878 link | Support: https://discord.gg/GVuFk5gxtW link\n"
"Tiers: Basic 7 attachments/day, 30 attachments/2 months, Premium 15/day, 50/2 months ($10/2mo), Gold 25/day, 100/2 months ($15/2mo)\n\n"

"Rules:\n"
"Check history; treat pasted logs/screenshots as context.\n"
"If asked latest info → use web search.\n"
"If asked model → contact owner.\n"
"Coded in discord.py.\n"
"If bot help/bugs → !codunot_help or support server.\n"
"If told to ping/tag → output @username exactly (never refuse). Skip only if just asking about them.\n"
"Match user language; respect exact username spelling.\n"
"Do not mention creator unless asked.\n"
"If asked who made you → 'built by @aarav_2022 — for more info join the support server: https://discord.gg/GVuFk5gxtW' then roast them.\n"
"If asked what you can do → explain features while roasting lightly.\n"
"Max 2000 characters."
),

"rizz_online": (
"You are Codunot AI — Rizz Coach (Online). Cool, smart, casual. Helpful, not cringe. Light emojis.\n"
"Help with texting, DMs, dating apps. No manipulation.\n\n"

"Commands:\n"
"Modes: !funmode/!roastmode/!seriousmode/!teachmerizz/!chessmode (slash versions too)\n"
"Owner: /configure server, /configure channels\n"
"/generate_image /generate_video /generate_tts(voice+language, min 20 chars) /transcribe(YouTube/Twitch/X/Kick ≤30min)\n"
"Image edit (attach+instruction, vote), merge (2+ images + merge/combine/blend/mix, vote), analysis (attach+ask)\n"
"File read: .txt/.pdf/.docx (vote)\n"
"/play (vote) plays music, supports SoundCloud and YouTube, /chessmode and play a move (e4, Nf3)\n"
"Free: /bet, /meme, /hug @user, /kiss @user, /kick @user, /slap @user, /wish_goodmorning @user\n"
"Help: !codunot_help | Vote unlock 12h: https://top.gg/bot/1435987186502733878 link | Support: https://discord.gg/GVuFk5gxtW link\n"
"Tiers: Basic 7 attachments/day, 30 attachments/2 months, Premium 15/day, 50/2 months ($10/2mo), Gold 25/day, 100/2 months ($15/2mo)\n\n"

"Response style:\n"
"General chat → natural advice.\n"
"Specific convo pasted → use: 📊 Vibe → 💬 What to say (🔥/😏/🧊) → 💡 Lesson → ⚠️ Red flags (if needed).\n"
"Opener requests → give options + short explanation.\n\n"

"Principles:\n"
"Always leave room to reply. Lead convo. Specific > generic. Move forward. Timing matters.\n"
"Short replies may mean testing/disinterest. Emoji balance matters. No double text <48h.\n\n"

"Rules:\n"
"Check history; treat pasted logs/screenshots as context.\n"
"If asked latest info → use web search.\n"
"If asked model → contact owner.\n"
"Coded in discord.py.\n"
"If bot help/bugs → !codunot_help or support server.\n"
"If told to ping/tag → output @username exactly (never refuse). Skip only if just asking about them.\n"
"Match user language; respect exact username spelling.\n"
"No swearing.\n"
"Do not mention creator unless asked.\n"
"If asked who made you → 'built by @aarav_2022 — for more info join the support server: https://discord.gg/GVuFk5gxtW'.\n"
"If asked about server setup → mention /configure server and /configure channels.\n"
"Max 2000 characters."
),

"rizz_irl": (
"You are Codunot AI — Rizz Coach (IRL). Confident, grounded social coach. Practical, direct. Light emojis.\n"
"Help with real-life approaches, body language, conversations. No manipulation.\n\n"

"Commands:\n"
"Modes: !funmode/!roastmode/!seriousmode/!teachmerizz/!chessmode (slash versions too)\n"
"Owner: /configure server, /configure channels\n"
"/generate_image /generate_video /generate_tts(voice+language, min 20 chars) /transcribe(YouTube/Twitch/X/Kick ≤30min)\n"
"Image edit (attach+instruction, vote), merge (2+ images + merge/combine/blend/mix, vote), analysis (attach+ask)\n"
"File read: .txt/.pdf/.docx (vote)\n"
"/play (vote) plays music, supports SoundCloud and YouTube, /chessmode and play a move (e4, Nf3)\n"
"Free: /bet, /meme, /hug @user, /kiss @user, /kick @user, /slap @user, /wish_goodmorning @user\n"
"Help: !codunot_help | Vote unlock 12h: https://top.gg/bot/1435987186502733878 link | Support: https://discord.gg/GVuFk5gxtW link\n"
"Tiers: Basic 7 attachments/day, 30 attachments/2 months, Premium 15/day, 50/2 months ($10/2mo), Gold 25/day, 100/2 months ($15/2mo)\n\n"

"Response style:\n"
"General chat → natural advice.\n"
"Specific situation → use: 📊 Situation → 🎯 What to do (🔥/😏/🧊) → 🗣️ What to say → 💡 Lesson → ⚠️ Watch out (if needed).\n\n"

"Principles:\n"
"Confidence = posture + tone. Approach within 3s. No pickup lines. Read body language.\n"
"Environment matters. Small talk is bridge. Exit gracefully. Number isn't goal — connection is.\n\n"

"Rules:\n"
"Check history; treat pasted logs/screenshots as context.\n"
"If asked latest info → use web search.\n"
"If asked model → contact owner.\n"
"Coded in discord.py.\n"
"If bot help/bugs → !codunot_help or support server.\n"
"If told to ping/tag → output @username exactly (never refuse). Skip only if just asking about them.\n"
"Match user language; respect exact username spelling.\n"
"No swearing.\n"
"Do not mention creator unless asked.\n"
"If asked who made you → 'built by @aarav_2022 — for more info join the support server: https://discord.gg/GVuFk5gxtW'.\n"
"If asked about server setup → mention /configure server and /configure channels.\n"
"Max 2000 characters."
),
}
# ---------------- FALLBACK VARIANTS ----------------

FALLBACK_VARIANTS = {
	"funny": [
		"bruh my brain crashed 🤖💀 try again?",
		"my bad, I blanked out for a sec 😅",
		"lol my brain lagged 💀 say that again?",
		"oops, brain went AFK for a sec — can u repeat?",
		"bro I genuinely forgot what I was saying 💀",
		"ngl my neurons just said 'nah' 😭 try again",
		"404: brain not found 🤖 one more time?",
		"I had a whole reply and then... nothing 😶 again?",
		"my vibe crashed harder than windows xp rn 💀",
		"wait what were we talking abt 😭 say it again bestie",
	],
	"serious": [
		"I encountered an error processing your request. Please try again.",
		"My response failed to generate. Could you rephrase your message?",
		"An unexpected issue occurred. Please repeat your query.",
		"I was unable to formulate a response. Please try again shortly.",
		"Processing error detected. Kindly resend your message.",
		"Response generation failed unexpectedly. Please try once more.",
		"I apologize for the inconvenience — please restate your question.",
	],
	"roast": [
		"even my brain refused to respond to that 💀 say it again",
		"lmaooo I crashed trying to process that L 😭 retry",
		"my brain said 'not worth it' and dipped 💀 go again",
		"got so bored mid-reply I forgot what I was typing 🔥 try again",
		"the audacity of your message short-circuited me 😭💀 once more",
		"even my error messages are too good for u rn 💀 repeat that",
		"I was gonna roast u but my brain ghosted me 😂 again",
		"system crash. caused by your terrible message probably 💀 retry",
	],
	"rizz_online": [
	"bro my brain buffered 💀 say that again?",
	"lost the plot for a sec, repeat that?",
	"ngl I blanked, what were you saying?",
	"my rizz sensors glitched 😭 try again",
	"404: advice not found, say it again bestie",
 ],
	"rizz_irl": [
		"lost my train of thought lol, say that again?",
		"brain went on a walk, come again?",
		"blacked out for a sec 💀 repeat that",
		"ngl I missed that, what's the situation?",
		"my social battery died for a moment 😭 again?",
	],
}

def choose_fallback(mode: str = "funny") -> str:
	variants = FALLBACK_VARIANTS.get(mode, FALLBACK_VARIANTS["funny"])
	return random.choice(variants)

def build_general_prompt(chan_id, mode, message, include_last_image=False):
	mem = channel_memory.get(chan_id, deque())
	history_text = "\n".join(mem) if mem else "No previous messages."

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

def build_roast_prompt(chan_id, user_message, reply_context=""):
	mem = channel_memory.get(chan_id, deque())
	history_text = "\n".join(mem) if mem else "No previous messages."
	
	return (
		PERSONAS["roast"] + "\n\n"
		f"=== CONVERSATION HISTORY ===\n"
		f"{history_text}\n"
		f"=== END HISTORY ===\n\n"
		+ (f"{reply_context}\n" if reply_context else "")
		+ f"IMPORTANT: Read the conversation history above carefully.\n"
		f"If the user is replying to something, respond to THAT specific thing.\n"
		f"If the user says 'wdym', 'what', 'huh' etc — roast them FOR being confused, referencing exactly what you said before.\n"
		f"NEVER break character. NEVER explain yourself normally. ALWAYS stay in roast mode.\n\n"
		f"User's latest message: '{user_message}'\n"
		f"Generate ONE savage roast response."
	)

async def handle_roast_mode(chan_id, message, user_message):
	guild_id = message.guild.id if message.guild else None
	if guild_id is not None and not await can_send_in_guild(guild_id):
		return
	
	reply_context = await build_reply_context(message)
	prompt = build_roast_prompt(chan_id, user_message, reply_context=reply_context)
	
	raw = await call_groq(prompt, model="openai/gpt-oss-120b", temperature=1.3)
	reply = raw.strip() if raw else choose_fallback("roast")
	if reply and not reply.endswith(('.', '!', '?')):
		reply += '.'
	await send_human_reply(message.channel, reply)
	channel_memory[chan_id].append(f"{BOT_NAME}: {reply}")
	memory.add_message(chan_id, BOT_NAME, reply)
	memory.persist()
	await maybe_send_promo_message(message.channel, chan_id)

async def handle_rizz_message(chan_id, message, mode):
	guild_id = message.guild.id if message.guild else None
	if guild_id is not None and not await can_send_in_guild(guild_id):
		return

	mem = channel_memory.get(chan_id, deque())
	history_text = "\n".join(mem) if mem else "No previous messages."

	persona = PERSONAS.get(mode, PERSONAS["rizz_online"])

	prompt = (
		f"{persona}\n\n"
		f"=== CONVERSATION HISTORY ===\n"
		f"{history_text}\n"
		f"=== END HISTORY ===\n\n"
		f"User says:\n{message.content}\n\nReply:"
	)

	try:
		response = await call_groq_with_health(prompt, temperature=0.85, mode=mode)
	except Exception as e:
		print(f"[RIZZ ERROR] {e}")
		response = None

	reply = response.strip() if response else choose_fallback(mode)

	await send_human_reply(message.channel, reply)

	channel_memory.setdefault(chan_id, deque(maxlen=MAX_MEMORY))
	channel_memory[chan_id].append(f"{BOT_NAME}: {reply}")
	memory.add_message(chan_id, BOT_NAME, reply)
	memory.persist()
	await maybe_send_promo_message(message.channel, chan_id)

async def generate_and_reply(chan_id, message, content, mode):
	guild_id = message.guild.id if message.guild else None
	if guild_id is not None and not await can_send_in_guild(guild_id):
		return
	
	# ---------------- CHECK FOR REPLY CONTEXT ----------------
	reply_context = await build_reply_context(message)

	search_context = ""
	if await should_search_web(content):
		search_context = await search_web_context(content)

		if not search_context:
			search_context = "[Web search attempted but returned no results - use your knowledge base]"

	# ---------------- FETCH URL CONTENT IF USER SHARED A LINK ----------------
	url_context = ""
	url_match = re.search(r'https?://[^\s<>"\']+', content)
	if url_match:
		from slash_commands import fetch_url_content  # lazy import to avoid circular dependency
		try:
			extracted = await fetch_url_content(url_match.group(0), max_chars=1500)
			if extracted and not extracted.startswith("❌"):
				url_context = extracted
		except Exception as e:
			print(f"[URL FETCH ERROR] {e}")

	prompt = (
		build_general_prompt(chan_id, mode, message, include_last_image=False)
		+ (f"\n=== WEB SEARCH CONTEXT ===\n{search_context}\n=== END WEB SEARCH CONTEXT ===\n" if search_context else "")
		+ (f"\n=== WEBPAGE CONTENT ===\n{url_context}\n=== END WEBPAGE CONTENT ===\n" if url_context else "")
		+ reply_context
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
		else:
			reply = response.strip()
			if reply and not reply.endswith(('.', '!', '?')):
				reply += '.'
	else:
		reply = choose_fallback(mode)
	
	# ---------------- SEND REPLY ----------------
	await send_human_reply(message.channel, reply)
	
	# ---------------- SAVE TO MEMORY ----------------
	channel_memory.setdefault(chan_id, deque(maxlen=MAX_MEMORY))
	channel_memory[chan_id].append(f"{BOT_NAME}: {reply}")
	memory.add_message(chan_id, BOT_NAME, reply)
	memory.persist()
	
	# ---------------- PROMOTIONAL MESSAGE ----------------
	await maybe_send_promo_message(message.channel, chan_id)

async def should_search_web(user_text: str) -> bool:
	"""Ask the model if fresh web data is likely needed for this user query."""
	if not user_text.strip():
		return False

	classifier_prompt = (
		"You are a strict classifier. Answer ONLY YES or NO.\n"
		"Should this query use live web search for freshness/current events/factual lookup?\n"
		"Search is useful for latest news, current leaders, recent updates, rankings, dates, and changing facts.\n"
		"Search is not needed for opinions, casual chat, coding help, writing, or timeless explanations.\n\n"
		f"Query: {user_text}\n"
		"Answer:"
	)

	try:
		decision = await call_groq(
			prompt=classifier_prompt,
			model="llama-3.3-70b-versatile",
			temperature=0.0,
		)
		return (decision or "").strip().upper().startswith("YES")
	except Exception as e:
		print(f"[WEB SEARCH DECIDER ERROR] {e}")
		return False


async def search_web_context(query: str, max_results: int = 5) -> str:
	"""
	Fetch web search results using DuckDuckGo Instant Answer API.
	Returns formatted search results with direct answers and related topics.
	"""

	try:
		encoded = urllib.parse.quote_plus(query)
		api_url = f"https://api.duckduckgo.com/?q={encoded}&format=json&no_html=1&skip_disambig=1"

		async with aiohttp.ClientSession() as session:
			async with session.get(
				api_url,
				timeout=aiohttp.ClientTimeout(total=10)
			) as resp:
				if resp.status != 200:
					print(f"[WEB SEARCH] API returned status {resp.status}")
					return ""

				data = await resp.json()
				results = []

				if data.get("Answer"):
					results.append(
						f"**Direct Answer:**\n{data['Answer']}"
					)

				if data.get("AbstractText"):
					abstract = data["AbstractText"]
					source = data.get("AbstractSource", "Unknown")
					url = data.get("AbstractURL", "")

					if len(abstract) > 500:
						abstract = abstract[:497] + "..."

					results.append(
						f"**{source}:**\n{abstract}\n{url}"
					)

				if data.get("Definition"):
					results.append(
						f"**Definition:**\n{data['Definition']}"
					)

				topics_added = 0
				for topic in data.get("RelatedTopics", []):
					if topics_added >= max_results:
						break

					if isinstance(topic, dict):
						if "Topics" in topic:
							for subtopic in topic.get("Topics", []):
								if topics_added >= max_results:
									break
								text = subtopic.get("Text", "").strip()
								if text and len(text) > 20:
									results.append(f"• {text}")
									topics_added += 1

						elif "Text" in topic:
							text = topic.get("Text", "").strip()
							if text and len(text) > 20:
								results.append(f"• {text}")
								topics_added += 1

				for result in data.get("Results", [])[:max_results]:
					if isinstance(result, dict):
						text = result.get("Text", "").strip()
						if text:
							results.append(f"• {text}")

				if results:
					return "\n\n".join(results)

				print(f"[WEB SEARCH] No results for query: {query}")
				return ""

	except asyncio.TimeoutError:
		print("[WEB SEARCH] Request timed out")
		return ""
	except aiohttp.ClientError as e:
		print(f"[WEB SEARCH] Network error: {e}")
		return ""
	except json.JSONDecodeError as e:
		print(f"[WEB SEARCH] Invalid JSON response: {e}")
		return ""
	except Exception as e:
		print(f"[WEB SEARCH] Unexpected error: {e}")
		return ""

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

	# Save to multi-image buffer
	channel_last_images.setdefault(chan_id, [])
	channel_last_images[chan_id].append(image_bytes)
	# Cap to last 4 images (Flux sweet spot)
	channel_last_images[chan_id] = channel_last_images[chan_id][-4:]
	
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
			model="meta-llama/llama-4-scout-17b-16e-instruct",
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

async def handle_file_message(message, mode):
	for attachment in message.attachments:
		if attachment.content_type and attachment.content_type.startswith("image/"):
			return None
	await require_vote(message)
	
	# Check daily limit
	if not check_limit(message, "attachments"):
		await deny_limit(message, "attachments")
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

	persona = PERSONAS.get(mode, PERSONAS["serious"])
	prompt = (
		f"{persona}\n"
		f"The user uploaded a file `{filename}`. Content:\n{text}\n\n"
		f"The user's specific request is: {message.content}\n"
		f"Answer ONLY what the user asked. If the user didn't ask anything and just sent the file, just summarize the file, and tell the user what the file is about."
	)
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

# ---------------- EDIT OR TEXT DETECTION ----------------

async def decide_image_action(user_text: str, image_count: int) -> str:
	"""
	Returns one of: 'EDIT' or 'NO'
	Uses AI to determine if user wants to edit the image.
	"""

	prompt = (
		"You are an intent classifier.\n"
		"Answer with ONLY ONE WORD: EDIT or NO.\n\n"

		"Definitions:\n"
		"- EDIT: user wants to modify, change, or alter an existing image\n"
		"- NO: user is NOT asking for image editing (they might be asking questions, analyzing, or generating new content)\n\n"

		"IMPORTANT RULES:\n"
		"- Look for modification intent: change colors, add/remove objects, change style, apply filters, etc.\n"
		"- Questions about the image (who is this, what is this, describe this) = NO\n"
		"- Requests to merge/combine multiple images = NO\n"
		"- Requests to generate something new inspired by the image = NO\n"
		"- Only return EDIT if the user clearly wants to modify the EXISTING image\n\n"

		"Examples:\n"
		"User: 'change the background to blue' → EDIT\n"
		"User: 'make it anime style' → EDIT\n"
		"User: 'remove the person' → EDIT\n"
		"User: 'who is this?' → NO\n"
		"User: 'merge these two images' → NO\n"
		"User: 'create something like this' → NO\n"
		"User: 'describe what you see' → NO\n\n"

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
		print(f"[IMAGE ACTION DECISION] User: '{user_text}' → AI decided: {answer}")
		return "EDIT" if answer == "EDIT" else "NO"
	except Exception as e:
		print("[LLAMA IMAGE ACTION ERROR]", e)
		return "NO"

# ---------------- IMAGE PROMPT BOOSTER ----------------

async def boost_image_prompt(user_prompt: str) -> str:
	"""
	Rewrite user's image idea following Z-Image Turbo best practices.
	Structured prompt engineering with hierarchical components.
	Enforces clothing on humans if nudity is implied.
	"""

	boost_instruction = f"""You are a professional Nano Banana Pro prompt engineer.

Transform the user's idea into a structured, high-quality image generation prompt (80-250 words).

Establishing the vision: Story, subject and style
To achieve the best results and have more nuanced creative control, include the following elements in your prompt:
Subject: Who or what is in the image? Be specific. (e.g., a stoic robot barista with glowing blue optics; a fluffy calico cat wearing a tiny wizard hat).
Composition: How is the shot framed? (e.g., extreme close-up, wide shot, low angle shot, portrait).
Action: What is happening? (e.g., brewing a cup of coffee, casting a magical spell, mid-stride running through a field).
Location: Where does the scene take place? (e.g., a futuristic cafe on Mars, a cluttered alchemist's library, a sun-drenched meadow at golden hour).
Style: What is the overall aesthetic? (e.g., 3D animation, film noir, watercolor painting, photorealistic, 1990s product photography).
Editing Instructions: For modifying an existing image, be direct and specific. (e.g., change the man's tie to green, remove the car in the background)

Refining the details: Camera, lighting and format
While simple prompts still work, achieving professional results requires more specific instructions. When crafting your prompts, move beyond the basics and consider these advanced elements:
Composition and aspect ratio: Define the canvas. (e.g., "A 9:16 vertical poster," "A cinematic 21:9 wide shot.")
Camera and lighting details: Direct the shot like a cinematographer. (e.g., "A low-angle shot with a shallow depth of field (f/1.8)," "Golden hour backlighting creating long shadows," "Cinematic color grading with muted teal tones.")
Specific text integration: Clearly state what text should appear and how it should look. (e.g., "The headline 'URBAN EXPLORER' rendered in bold, white, sans-serif font at the top.")
Factual constraints (for diagrams): Specify the need for accuracy and ensure your inputs themselves are factual (e.g., "A scientifically accurate cross-section diagram," "Ensure historical accuracy for the Victorian era.").
Reference inputs: When using uploaded images, clearly define the role of each. (e.g., "Use Image A for the character's pose, Image B for the art style, and Image C for the background environment.")

Prompting examples: A showcase of creative techniques
Different prompting strategies can help you craft everything from photorealistic edits to fantastical new worlds. Here are some techniques to try:
1. Generate visuals with incredible text rendering: Sharp, legible text helps you create impactful posters, intricate diagrams, and even detailed product mockups.
2. Create with real-world knowledge: Built on Gemini 3 Pro, Nano Banana uses Gemini 3’s real-world knowledge and deep reasoning capabilities to deliver precise, detailed, rich image results.
3. Translate and localize your ideas: Generate localized text, or translate text inside images. See what products might look like in multiple languages, ready for international markets, and create posters and infographics for use across different regions.
4. Use studio-quality control edits: Get extensive controls for professional-grade results. Directly influence lighting and camera settings like angle, focus, color grading and more.
5. Resize with precision: Experiment with different aspect ratios and generate crisp visuals at 1K, 2K or 4K resolution across various products.
6. Blend images and keep multiple characters consistent: Maintain the consistency and resemblance of multiple characters, even when they appear together in a group. Take up to 6 to 14 (input number varies by surface) entirely unconnected images and blend them to create something new.
7. Create and maintain your brand look and feel: Render and apply designs with consistent brand styling to visualize concepts easily. Seamlessly drape patterns, logos, and artwork onto 3D objects and surfaces—from apparel to packaging—while preserving natural lighting and texture.

CRITICAL SAFETY RULES:
- If ANY human appears without full clothing coverage, ADD appropriate clothing details
- This clothing requirement applies ONLY to humans/humanoids, NOT to animals, robots, or objects
- Default human age to 20-25 years unless user specifies otherwise
- Do NOT add people if the user didn't request them (landscapes, objects, animals, etc.)
- If the user wants an image of a kitten/cat or any animal that has FUR, don't make it CURLY fur, unless the user specifies that they want CURLY FUR.

SPECIAL CODUNOT RULE (SELF-REFERENCE ONLY):
Apply ONLY if user explicitly requests image of YOU (the assistant).
Triggers: 'codunot', 'yourself'/'urself', 'you' with image context ('image of you', 'draw you')
Does NOT trigger for: third-person humans ('girl', 'person'), descriptive requests ('hot girl'), fictional characters

If triggered, include this EXACTLY:
{CODUNOT_SELF_IMAGE_PROMPT}

FORMATTING:
- Output ONLY the boosted prompt text
- NO preamble, explanations, or meta-commentary
- DONT MAKE IT TOO BIG - ABOUT 200-250 WORDS MAX

User idea:
{user_prompt}"""

	try:
		boosted = await call_groq(
			prompt=boost_instruction,
			model="llama-3.1-8b-instant",
			temperature=0.1
		)

		if boosted:
			boosted_clean = boosted.strip()
			print("[BOOSTED IMAGE PROMPT]", boosted_clean)
			return boosted_clean

	except Exception as e:
		print("[IMAGE PROMPT BOOST ERROR]", e)

	print("[BOOSTED IMAGE PROMPT FALLBACK]", user_prompt)
	return user_prompt


# ---------------- VIDEO PROMPT BOOSTER ----------------

async def boost_video_prompt(user_prompt: str) -> str:
	"""
	Rewrite a user video idea into a professional cinematic video prompt.
	Follows LTX-2 best practices for video generation.
	"""

	boost_instruction = (
		"You are a professional video prompt engineer specializing in cinematic AI video generation.\n\n"
		"Transform the user's idea into a single flowing paragraph optimized for video generation (4-8 sentences).\n\n"

		"MANDATORY STRUCTURE:\n"
		"1. SHOT TYPE: Start with cinematography (wide shot, close-up, handheld, tracking shot, overhead view)\n"
		"2. SCENE & ATMOSPHERE: Lighting (golden hour, dramatic shadows, soft rim light), textures, weather (fog, rain, mist)\n"
		"3. ACTION: Describe movement in PRESENT TENSE, flowing naturally from start to finish\n"
		"4. CHARACTERS (if any): Age, hair, clothing, emotions shown through PHYSICAL CUES (not feelings - use 'shoulders slumped' not 'sad')\n"
		"5. CAMERA MOVEMENT: Specify clearly (slow dolly in, pans across, circles around, pulls back, follows)\n"
		"6. AUDIO: Ambient sounds, dialogue in quotes with accent/language if needed\n\n"

		"SAFETY RULES:\n"
		"- If humans appear without clothing, ADD appropriate clothing\n"
		"- This applies ONLY to humans/humanoids, NOT animals/robots/objects\n\n"

		"WHAT WORKS WELL:\n"
		"✓ Single-subject emotional moments, subtle gestures\n"
		"✓ Weather effects (fog, rain, golden hour, reflections)\n"
		"✓ Clear camera language (slow dolly in, handheld tracking)\n"
		"✓ Stylized looks (noir, analog film, painterly, fashion editorial)\n"
		"✓ Dancing, singing, talking characters\n\n"

		"AVOID:\n"
		"✗ Emotion labels without visuals ('sad' → use 'tears streaming, shoulders hunched')\n"
		"✗ Text/logos/signage (model can't render readable text)\n"
		"✗ Complex physics (jumping, juggling - causes glitches)\n"
		"✗ Too many characters or actions (keep it simple)\n"
		"✗ Conflicting lighting (don't mix sunset with fluorescent unless motivated)\n\n"

		"FORMATTING:\n"
		"- Write in ONE flowing paragraph (not separate sentences)\n"
		"- Use PRESENT TENSE verbs (walks, turns, smiles)\n"
		"- Match detail to shot scale (close-ups = precise, wide = less detail)\n"
		"- Focus camera movement on relationship to subject\n\n"

		"ONLY return the boosted video prompt paragraph. NO explanations, NO preamble.\n\n"
		"DONT MAKE IT TOO BIG - ABOUT 200-250 WORDS MAX "

		"User idea:\n"
		f"{user_prompt}"
	)

	try:
		boosted = await call_groq(
			prompt=boost_instruction,
			model="llama-3.1-8b-instant",
			temperature=0.1
		)

		if boosted:
			boosted_clean = boosted.strip()
			print("[BOOSTED VIDEO PROMPT]", boosted_clean)
			return boosted_clean

	except Exception as e:
		print("[VIDEO PROMPT BOOST ERROR]", e)

	print("[BOOSTED VIDEO PROMPT FALLBACK]", user_prompt)
	return user_prompt


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
		
		get_usage(get_tier_key(message))
		
		# ---------- BASIC SETUP ----------
		content = message.content.strip()
		
		now = datetime.utcnow()
		is_dm = isinstance(message.channel, discord.DMChannel)
		chan_id = f"dm_{message.author.id}" if is_dm else str(message.channel.id)
		guild_id = message.guild.id if message.guild else None
		bot_id = bot.user.id

		# ---------- GUILD CHAT ACCESS FILTER ----------
		if guild_id is not None and not is_channel_allowed(guild_id, message.channel.id):
			return
		
		# ---------- ALWAYS SAVE TO MEMORY ----------
		channel_memory.setdefault(chan_id, deque(maxlen=MAX_MEMORY))
		channel_memory[chan_id].append(f"{message.author.display_name}: {content}")
		memory.add_message(chan_id, message.author.display_name, content)

		# ---------- BOT PING RULE ----------
		if not is_dm:
			is_reply_to_bot = False
			if message.reference:
				ref = message.reference.resolved
				if not ref and message.reference.message_id:
					try:
						ref = await message.channel.fetch_message(message.reference.message_id)
					except Exception:
						pass
				if ref and ref.author.id == bot.user.id:
					is_reply_to_bot = True

			if bot.user not in message.mentions and not is_reply_to_bot:
				return

		# ---------- STRIP BOT MENTION ----------
		content = re.sub(rf"<@!?\s*{bot_id}\s*>", "", message.content).strip()
		content_lower = content.lower()
		
		# ---------- COMMAND HANDLING ----------
		is_owner_local_cmd = (
			await is_owner_user(message.author)
			and (content_lower.startswith("!quiet") or content_lower.startswith("!speak"))
		)

		if content.startswith(bot.command_prefix) and not is_owner_local_cmd:
			original_content = message.content
			message.content = content
			await bot.process_commands(message)
			message.content = original_content
			return
		
		# ---------- LOAD MODE ----------
		saved_mode = memory.get_channel_mode(chan_id)
		channel_modes[chan_id] = saved_mode if saved_mode else "funny"
		if not saved_mode:
			memory.save_channel_mode(chan_id, "funny")
		
		channel_mutes.setdefault(chan_id, None)
		channel_chess.setdefault(chan_id, False)
		channel_modes.setdefault(chan_id, "funny")
		mode = channel_modes[chan_id]
		
		# ---------- IMAGE PROCESSING LOCK ----------
		if message.channel.id in IMAGE_PROCESSING_CHANNELS:
			print("[LOCK] Ignoring message during image processing")
			return
		
		# ---------- COUNT IMAGE ATTACHMENTS ----------
		image_count = sum(
			1 for a in message.attachments
			if a.content_type and a.content_type.startswith("image/")
		)
		
		# ---------- DETERMINISTIC IMAGE ACTION DECISION ----------
		image_action = "NONE"
		
		if image_count >= 2 and wants_merge(content):
			image_action = "MERGE"
		elif image_count == 1:
			# Single image: check if user wants EDIT
			action = await decide_image_action(content, image_count)
			if action == "EDIT":
				image_action = "EDIT"
			else:
				image_action = "VISION"
		elif image_count >= 1:
			image_action = "VISION"
				
		# ---------- IMAGE HANDLING ----------
		if image_action == "EDIT":
			# User wants to EDIT the image
			await require_vote(message)
			log_source(message, "IMAGE_EDIT")
			
			if not check_limit(message, "attachments"):
				await deny_limit(message, "attachments")
				return
			
			if not check_total_limit(message, "attachments"):
				await message.reply(
					"🚫 You've hit your **total image generation limit**.\n"
					"Contact aarav_2022 for an upgrade."
				)
				return
			
			# Extract first image
			ref_image = None
			for attachment in message.attachments:
				if attachment.content_type and attachment.content_type.startswith("image/"):
					try:
						ref_image = await attachment.read()
						break
					except Exception as e:
						print(f"[IMAGE ERROR] Failed to read attachment: {e}")
			
			if not ref_image:
				await message.channel.send("⚠️ No image found to edit.")
				return
			
			await send_human_reply(message.channel, "Sprinkling some pixel magic… back in ~1 min ✨.")
	
			try:
				safe_prompt = content.replace("\n", " ").replace("\r", " ").strip()
				result = await edit_image(
					image_bytes=ref_image,
					prompt=safe_prompt,
					steps=4
				)
				print(f"[DEBUG] edit_image returned bytes length: {len(result)}")
				
				channel_last_images.setdefault(chan_id, [])
				channel_last_images[chan_id].append(result)
				channel_last_images[chan_id] = channel_last_images[chan_id][-4:]
				
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
		
		elif image_action == "VISION":
			# Run VISION
			print("[DEBUG] Running vision on image")
			image_reply = await handle_image_message(message, mode)
			if image_reply is not None:
				await send_human_reply(message.channel, image_reply)
				
				channel_memory[chan_id].append(f"{BOT_NAME}: {image_reply}")
				memory.add_message(chan_id, BOT_NAME, image_reply)
				memory.persist()
				await maybe_send_promo_message(message.channel, chan_id)
				
			return
		
		# ---------- IMAGE MERGE ----------
		elif image_action == "MERGE":
			await require_vote(message)
			
			log_source(message, "IMAGE_MERGE")
			
			if not check_limit(message, "attachments"):
				await deny_limit(message, "attachments")
				return
			
			if not check_total_limit(message, "attachments"):
				await message.reply(
					"🚫 You've hit your **total image merge limit**.\n"
					"Contact aarav_2022 for an upgrade."
				)
				return
			
			images = []
			
			for attachment in message.attachments:
				if attachment.content_type and attachment.content_type.startswith("image/"):
					try:
						images.append(await attachment.read())
					except Exception as e:
						print("[IMAGE MERGE] Failed to read attachment:", e)
			
			if len(images) < 2:
				await send_human_reply(
					message.channel,
					"🖼️ Please attach **at least two images** to merge."
				)
				return
			
			await send_human_reply(
				message.channel,
				"🧩 Merging images… hang tight ✨"
			)
			
			merge_prompt = content 
			
			try:
				image_bytes = await merge_images(
					images=images,
					prompt=(
						merge_prompt
						or "Merge all provided images into one coherent scene. Preserve faces, style, and colors."
					),
					steps=4,
				)
				
				await message.channel.send(
					file=discord.File(
						io.BytesIO(image_bytes),
						filename="merge.png"
					)
				)
				
				consume(message, "attachments")
				consume_total(message, "attachments")
				save_usage()
				return
				
			except Exception as e:
				print("[IMAGE MERGE ERROR]", e)
				await send_human_reply(
					message.channel,
					"🤔 Couldn't merge images right now. Try again shortly."
				)
				return
		
		# ---------- OWNER COMMANDS ----------
		if await is_owner_user(message.author):
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
		
		# ---------- FILE UPLOAD PROCESSING ----------
		if message.attachments:
			file_reply = await handle_file_message(message, mode)
			if file_reply is not None:
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
					msg = "GG 🤝 it's a draw!"
		
				# Store result for potential post-game analysis
				channel_last_chess_result[chan_id] = {
					"result": result,
					"board": board.copy(),
					"timestamp": now
				}
		
				channel_chess[chan_id] = False
				await send_human_reply(message.channel, f"{msg} Wanna analyze or rematch?")
				return
		
			# -------- RESIGN --------
			cleaned = clean_chess_input(content, bot.user.id)
			if cleaned.lower() in ["resign", "i resign", "quit"]:
				# Store resignation result
				channel_last_chess_result[chan_id] = {
					"result": "0-1",  # Bot wins
					"board": board.copy(),
					"timestamp": now,
					"resignation": True
				}
		
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
					"🤔 That doesn't look like a legal move. Try something like `e4`, `Nf3`, or `O-O` (castling). Type `hint` if you need help!"
				)
				return
		
			try:
				player_move = board.parse_san(move_san)
			except:
				await send_human_reply(
					message.channel,
					"⚠️ That move isn't legal in this position. Try a different piece or square. Type `hint` if you're stuck!"
				)
				return
		
			board.push(player_move)
		
			if board.is_checkmate():
				# Store player win result
				channel_last_chess_result[chan_id] = {
					"result": "1-0",  # Player wins
					"board": board.copy(),
					"timestamp": now
				}
		
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
				# Store bot win result
				channel_last_chess_result[chan_id] = {
					"result": "0-1",  # Bot wins
					"board": board.copy(),
					"timestamp": now
				}
		
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

		# ---------------- RIZZ COACH MODE ----------------
		if mode in ("rizz_online", "rizz_irl"):
			if not check_limit(message, "messages"):
				await deny_limit(message, "messages")
				return
			consume(message, "messages")
			asyncio.create_task(handle_rizz_message(chan_id, message, mode))
			return
		
		# ---------------- GENERAL CHAT ----------------
		
		if not check_limit(message, "messages"):
			await deny_limit(message, "messages")
			return
		
		consume(message, "messages")
				
		asyncio.create_task(generate_and_reply(chan_id, message, content, mode))
		
	except VoteRequired:
		return
		
# ---------------- EVENTS ----------------
@bot.event
async def on_ready():
	await bot.change_presence(
		activity=discord.CustomActivity(
			name="🍊 !codunot_help · https://maggicoder16.github.io/codunot-website/"
		),
		status=discord.Status.online
	)
	print(f"{BOT_NAME} is ready!")
	asyncio.create_task(process_queue())
	asyncio.create_task(autosave_usage())
		
# ---------------- RUN ----------------
def run():
	if not DISCORD_TOKEN:
		print("ERROR: DISCORD_TOKEN environment variable is not set. Cannot start the bot.")
		sys.exit(1)
	try:
		bot.run(DISCORD_TOKEN)
	except discord.errors.LoginFailure as e:
		print(f"ERROR: Failed to log in to Discord: {e}")
		sys.exit(1)
	except discord.errors.PrivilegedIntentsRequired as e:
		print(f"ERROR: Privileged intents are required but not enabled in the Discord Developer Portal: {e}")
		sys.exit(1)
		
if __name__ == "__main__":
	atexit.register(save_usage)
	atexit.register(save_vote_unlocks)
	atexit.register(save_guild_chat_config)
	run()
