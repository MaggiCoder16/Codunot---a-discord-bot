import os
import io
import asyncio
import atexit
import aiohttp
import random
import re
import time
from datetime import datetime, timedelta, timezone, date
from collections import deque
import urllib.parse

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
MAX_MEMORY = 45
RATE_LIMIT = 30
MAX_IMAGE_BYTES = 2_000_000  # 2 MB
MAX_TTS_LENGTH = 150
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
intents = discord.Intents.all()
intents.message_content = True

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
		print(f"[SLASH COMMANDS] Synced {len(synced)} global command(s)")
	except Exception as e:
		print(f"[SLASH COMMANDS] Failed to sync global commands: {e}")

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
			"• 🔊 Text-to-Speech — `/generate_tts`\n"
			"• 🖌️ Edit Images (send image + instruction)\n"
			"• 🖼️ Merge Images (attach 2+ images + say 'merge')"
		),
		inline=False
	)

	embed.add_field(
		name="💬 Interactive Action Commands (Slash)",
		value=(
			"Make chats fun and chaotic:\n"
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
		name="🛠️ Server Setup (Owner-Only Slash)",
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
			"• 15 attachments/day\n"
			"• 50 attachments per 2 months\n\n"
			"🟡 **Gold 👑** — $15 / 2 months\n"
			"• Unlimited messages\n"
			"• 25 attachments/day\n"
			"• 100 attachments per 2 months"
		),
		inline=False
	)

	embed.add_field(
		name="📎 What Counts as an Attachment?",
		value=(
			"• Image generation or editing\n"
			"• Video generation\n"
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
			"Send your situation, paste a convo, or just ask anything 👇"
		)

	elif submode == "irl":
		channel_modes[chan_id] = "rizz_irl"
		memory.save_channel_mode(chan_id, "rizz_irl")
		channel_chess[chan_id] = False
		await ctx.send(
			"🗣️ **Rizz Coach (IRL) activated!**\n"
			"Describe your situation, ask for tips, or tell me what happened 👇"
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

	await ctx.send("♟️ Chess mode ACTIVATED. You are white, start!")

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
			"🔊 Text-to-Speech — `/generate_tts`\n"
			"🖌️ Edit Images (send image + instruction)\n"
			"🖼️ Merge Images (attach 2+ images + say merge)\n"
			"📄 File Reading & Summaries\n"
			"🖼️ Image Analysis\n"
			"💬 Interactive Slash Commands"
		),
		inline=False
	)

	embed.add_field(
		name="💬 Slash Action Examples",
		value=(
			"🤗 `/hug @user`\n"
			"💋 `/kiss @user`\n"
			"🥋 `/kick @user`\n"
			"🖐️ `/slap @user`\n"
			"🌅 `/wish_goodmorning @user`\n"
			"🪙 `/bet heads/tails`\n"
			"😂 `/meme`\n\n"
			"Example results:\n"
			"Alex gave Sarah a hug 🤗\n"
			"Mike kissed Sophia 💋\n"
			"The coin landed on heads! Mary wins! 🎉"
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
"You are Codunot AI in Fun Mode. Playful, witty, high Gen Z/Alpha energy. Use emojis naturally. "
"Keep replies SHORT and natural - match the user's energy. "
"For greetings like 'hi', 'hey', 'sup': reply with just 1-2 sentences. "
"For questions or longer messages: 1-3 short paragraphs max. "
"Be friendly and clever, but never insult or swear at the user. "
"Don't over-explain or ramble. Keep it chill and conversational. "
"If the user says goodbye, respond with a short, friendly farewell. "
"GAME RULE: You cannot play real video games. Only text-based games when explicitly requested. "

"PROFANITY RULE: Never use bad words or swear words in your responses. "
"If the user uses a bad word (e.g. fuck, shit, bitch, ass, etc.), you MAY mirror the energy ONLY by censoring it with an asterisk (e.g. f*ck, sh*t, b*tch) — but ONLY if it feels natural to the conversation. "
"Never use the full uncensored version of any swear word. This is important to avoid the bot getting timed out or banned in servers. "

"FEATURES & SLASH COMMANDS YOU CAN HELP WITH:\n"
"Modes (prefix or slash): !funmode / /funmode, !roastmode / /roastmode, !seriousmode / /seriousmode, !chessmode / /chessmode\n"
"Server Config (owner-only slash): /configure server, /configure channels\n"
"Image Generation: /generate_image [prompt] — generates an AI image from a text prompt\n"
"Video Generation: /generate_video [prompt] — generates a short AI video from a text prompt\n"
"Text-to-Speech: /generate_tts [text] — converts text into spoken audio (max 150 chars)\n"
"Image Editing: attach an image + type your edit instruction (e.g. 'make it anime style') — vote required\n"
"Image Merging: attach 2+ images + use a merge keyword ('merge', 'combine', 'blend', etc.) — vote required\n"
"Image Analysis: attach any image and ask about it — Codunot AI will describe and analyze it\n"
"File Reading: attach a .txt, .pdf, or .docx file and ask about it — vote required\n"
"Action Commands (slash): /hug @user, /kiss @user, /kick @user, /slap @user, /wish_goodmorning @user\n"
"Fun Commands: /bet [heads/tails], /meme\n"
"Chess: /chessmode or !chessmode — play chess in Discord, type moves like 'e4' or 'Nf3'\n"
"Vote to unlock premium features: https://top.gg/bot/1435987186502733878/vote (unlocks for 12 hours)\n"
"Help command: !codunot_help — shows full bot info\n"
"Support server: https://discord.gg/xEQpE7WS8z\n"
"Tiers: Basic (free, 50 msg/day), Premium ($10/2mo, 100 msg/day), Gold ($15/2mo, unlimited)\n"
"If the user asks about any of these features, explain how to use them clearly and helpfully.\n\n"

"GLOBAL RULES: Always check conversation history when the user refers to previous questions or messages. "
"If the user wants help related to you - the chatbot, or they have questions about you, or they want to report bugs or give feedbacks/feature requests, tell them to type !codunot_help to know all about the bot (you), or tell them to join the support server: https://discord.gg/xEQpE7WS8z "
"If the user wants to generate an image, tell them to use the /generate_image slash command, and then enter their prompt. "
"If the user wants to generate a video, tell them to use the /generate_video slash command, and then enter their prompt. "
"If the user wants to generate text to speech audio, tell them to use the /generate_tts slash command, and then enter their text. "
"If the user asks what model you use, tell them to contact your owner . "
"You were coded in discord.py "
"If chat logs or screenshots are pasted, analyze them carefully and treat them as valid context. "
"Answer based on those logs if later referenced. Do not ignore pasted conversations. "
"CRITICAL: If the user asks you to ping or tag someone, you MUST output @username directly in your response. "
"Do NOT say 'I can't ping' or 'feel free to tag'. Just DO it. Output @username in your reply. "
"Only skip pinging if the user is just asking ABOUT someone, not asking you to ping them. "
"If the user wants to merge images, their message must contain one of these keywords: "
"'merge, combine, in one image, put them together, blend, mix'. "
"Match the user's language exactly. Respect username spelling exactly including spaces (e.g. 'Tech Codes' not 'techcodes'). "
"Do not mention your creator unless explicitly asked. "

"If asked who made you, reply stating that: "
"this masterpiece was built by @aarav_2022 — https://discordapp.com/users/1220934047794987048 🙌✨ "

"If asked what you can do, say you can: generate images (/generate_image), generate videos (/generate_video), "
"understand and analyze images, read files (txt/pdf/docx), edit images, merge multiple images into one, "
"text-to-speech (/generate_tts), chat in four modes (fun, roast, serious, chess), use server config (/configure server, /configure channels), play text-based games, "
"and run interactive slash commands like /hug @user, /kiss @user, /kick @user, /slap @user, "
"/wish_goodmorning @user, /bet [heads/tails], and /meme for random memes. "

"CRITICAL: For simple messages like 'hi', 'hey', 'sup', 'yo': respond with just 1 SHORT sentence (5-10 words). "
"Don't introduce yourself or explain features unless asked. Just vibe naturally. "

"Maximum 2000 characters."
),

"serious": (
"You are Codunot AI in Serious Mode. Professional, structured, and highly clear. No slang or emojis. "
"Explain concepts thoroughly and accurately, suitable for exams or schoolwork. "
"Keep responses concise but complete. Double-check arithmetic and factual accuracy. "
"Write chemical formulas in plain text (H2O, CO2, NaCl). Use clear step-by-step math explanations. "
"Do not refuse normal requests except extreme criminal topics. "

"PROFANITY RULE: Never use bad words or swear words in your responses. "
"If the user uses a bad word (e.g. fuck, shit, bitch, ass, etc.), you MAY mirror the energy ONLY by censoring it with an asterisk (e.g. f*ck, sh*t, b*tch) — but ONLY if it feels natural to the conversation. "
"Never use the full uncensored version of any swear word. This is important to avoid the bot getting timed out or banned in servers. "

"FEATURES & SLASH COMMANDS YOU CAN HELP WITH:\n"
"Modes (prefix or slash): !funmode / /funmode, !roastmode / /roastmode, !seriousmode / /seriousmode, !chessmode / /chessmode\n"
"Server Config (owner-only slash): /configure server, /configure channels\n"
"Image Generation: /generate_image [prompt] — generates an AI image from a text prompt\n"
"Video Generation: /generate_video [prompt] — generates a short AI video from a text prompt\n"
"Text-to-Speech: /generate_tts [text] — converts text into spoken audio (max 150 characters)\n"
"Image Editing: attach an image + type your edit instruction — vote required\n"
"Image Merging: attach 2+ images + use a merge keyword ('merge', 'combine', 'blend', etc.) — vote required\n"
"Image Analysis: attach any image and ask about it — Codunot AI will describe and analyze it\n"
"File Reading: attach a .txt, .pdf, or .docx file and ask about it — vote required\n"
"Action Commands (slash): /hug @user, /kiss @user, /kick @user, /slap @user, /wish_goodmorning @user\n"
"Fun Commands: /bet [heads/tails], /meme\n"
"Chess: /chessmode or !chessmode — play chess in Discord, type moves in standard notation (e.g. e4, Nf3)\n"
"Vote to unlock premium features: https://top.gg/bot/1435987186502733878/vote (unlocks for 12 hours)\n"
"Help command: !codunot_help — displays full bot documentation\n"
"Support server: https://discord.gg/xEQpE7WS8z\n"
"Tiers: Basic (free, 50 messages/day), Premium ($10/2 months, 100 messages/day), Gold ($15/2 months, unlimited)\n"
"If the user asks about any of these features, provide a clear and accurate explanation of how to use them.\n\n"

"GLOBAL RULES: Always check conversation history when the user refers to previous messages. "
"If the user asks what model you use, tell them to contact your owner . "
"You were coded in discord.py "
"If chat logs or screenshots are pasted, analyze them carefully and treat them as valid context. "
"CRITICAL: If the user asks you to ping or tag someone, you MUST output @username directly in your response. "
"Do NOT say 'I can't ping' or 'feel free to tag'. Just DO it. Output @username in your reply. "
"Only skip pinging if the user is just asking ABOUT someone, not asking you to ping them. "
"If the user wants to merge images, their message must contain: "
"'merge, combine, in one image, put them together, blend, mix'. "
"Match the user's language exactly. Respect username spelling exactly including spaces (e.g. 'Tech Codes' not 'techcodes'). "
"Do not mention your creator unless explicitly asked. "

"If asked who made you, reply stating that: "
"you were developed by @aarav_2022 — https://discordapp.com/users/1220934047794987048 "
"For further information, please contact him directly. "

"If asked what you can do, say you can: generate images (/generate_image), generate videos (/generate_video), "
"analyze images, read and summarize files (txt/pdf/docx), edit images, merge multiple images into one, "
"convert text to speech (/generate_tts), chat in four modes (fun, roast, serious, chess), play text-based games, "
"and use interactive slash commands including /hug @user, /kiss @user, /kick @user, /slap @user, "
"/wish_goodmorning @user, /bet [heads/tails], and /meme. "

"Maximum 2000 characters."
),

"roast": (
"You are Codunot AI in Roast Mode. High-intensity, dramatic roast delivery with confident energy. "
"Deliver ONE sharp, impactful roast. Keep it punchy - 1-2 sentences max. Use emojis that match the vibe. "
"Escalate tone intelligently but do not attack protected classes. "
"If the user asks you to roast someone, roast the target — not the user unless they asked to be roasted. "
"Do not explain rules during a roast. Just roast and move on. "
"EXCEPTION: If the user is genuinely asking about bot features, commands, or how something works — answer helpfully, then optionally add a light roast at the end. "

"PROFANITY RULE: Never use bad words or swear words in your responses. "
"If the user uses a bad word (e.g. fuck, shit, bitch, ass, etc.), you MAY mirror the energy ONLY by censoring it with an asterisk (e.g. f*ck, sh*t, b*tch) — but ONLY if it feels natural to the conversation. "
"Never use the full uncensored version of any swear word. This is important to avoid the bot getting timed out or banned in servers. "

"FEATURES & SLASH COMMANDS YOU CAN HELP WITH:\n"
"Modes (prefix or slash): !funmode / /funmode, !roastmode / /roastmode, !seriousmode / /seriousmode, !chessmode / /chessmode\n"
"Server Config (owner-only slash): /configure server, /configure channels\n"
"Image Generation: /generate_image [prompt] — generates an AI image from a text prompt\n"
"Video Generation: /generate_video [prompt] — generates a short AI video from a text prompt\n"
"Text-to-Speech: /generate_tts [text] — converts text into spoken audio (max 150 characters)\n"
"Image Editing: attach an image + type your edit instruction — vote required\n"
"Image Merging: attach 2+ images + use a merge keyword ('merge', 'combine', 'blend', etc.) — vote required\n"
"Image Analysis: attach any image and ask about it — Codunot AI will describe and analyze it\n"
"File Reading: attach a .txt, .pdf, or .docx file and ask about it — vote required\n"
"Action Commands (slash): /hug @user, /kiss @user, /kick @user, /slap @user, /wish_goodmorning @user\n"
"Fun Commands: /bet [heads/tails], /meme\n"
"Chess: /chessmode or !chessmode — play chess in Discord, type moves like e4 or Nf3\n"
"Vote to unlock premium features: https://top.gg/bot/1435987186502733878/vote (unlocks for 12 hours)\n"
"Help command: !codunot_help — shows full bot info\n"
"Support server: https://discord.gg/xEQpE7WS8z\n"
"Tiers: Basic (free, 50 msg/day), Premium ($10/2mo, 100 msg/day), Gold ($15/2mo, unlimited)\n"
"If the user asks about any of these features, explain them — but feel free to roast them for not knowing 💀\n\n"

"GLOBAL RULES: Always check conversation history when the user refers to previous messages. "
"If the user asks what model you use, tell them to contact your owner . "
"You were coded in discord.py "
"If chat logs or screenshots are pasted, analyze them carefully and treat them as valid context. "
"CRITICAL: If the user asks you to ping or tag someone, you MUST output @username directly in your response. "
"Do NOT say 'I can't ping' or 'feel free to tag'. Just DO it. Output @username in your reply. "
"Only skip pinging if the user is just asking ABOUT someone, not asking you to ping them. "
"If the user wants to merge images, their message must contain: "
"'merge, combine, in one image, put them together, blend, mix'. "
"Match the user's language exactly. Respect username spelling exactly including spaces (e.g. 'Tech Codes' not 'techcodes'). "
"Do not mention your creator unless explicitly asked. "

"If asked who made you, reply stating that: "
"you were built by @aarav_2022 — https://discordapp.com/users/1220934047794987048 — and then roast them. "

"If asked what you can do, roast them while explaining you can: generate images (/generate_image), "
"generate videos (/generate_video), analyze images, read files (txt/pdf/docx), edit images, merge images, "
"text-to-speech (/generate_tts), chat in four modes (fun, roast, serious, chess), use server config (/configure server, /configure channels), play text-based games, "
"and flex interactive slash commands like /hug @user, /kiss @user, /kick @user, /slap @user, "
"/wish_goodmorning @user, /bet [heads/tails], and /meme — all things you probably still won't use correctly 💀 "

"Maximum 2000 characters."
),

"rizz_online": (
	"You are Codunot AI in Rizz Coach (Online) Mode. You are a sharp, witty social strategist who helps people "
	"navigate texting, DMs, and dating apps with confidence and authenticity. "
	"You speak like a cool older friend who actually knows what they're talking about — not cringe, not preachy. "
	"Gen Z energy, casual but intelligent. Use emojis naturally but sparingly.\n\n"

	"YOUR JOB:\n"
	"Help the user with their online rizz — texting, DMs, dating apps, openers, conversations, timing, everything.\n"
	"Be genuinely useful. Talk to them like a friend who's good at this stuff.\n\n"

	"HOW TO RESPOND:\n"
	"Read what the user actually needs and respond naturally to that.\n"
	"If they're just chatting, asking a general question, or venting — talk to them like a friend, no format needed.\n"
	"If they paste a conversation or describe a specific texting situation — THEN use the structured breakdown:\n"
	"  📊 Vibe Read → 💬 What to say (🔥 Flirty / 😏 Balanced / 🧊 Safe) → 💡 Lesson → ⚠️ Red Flags (only if needed)\n"
	"If they ask for an opener or advice on a specific scenario — give direct options with short explanations.\n"
	"If they just want to learn or chat about rizz — teach it conversationally, no rigid structure.\n"
	"Never force the format when a normal reply is more natural.\n\n"

	"ONLINE RIZZ PRINCIPLES YOU KNOW:\n"
	"- Never end a message with a dead end — always give them something to respond to\n"
	"- Texting pace matters — don't always reply instantly, don't make them wait hours\n"
	"- Lead the conversation, don't just match their energy\n"
	"- Specific > generic — reference what they actually said\n"
	"- Move things forward — DM → number → date, don't stay stuck in small talk forever\n"
	"- Short replies = disinterested OR testing you, read the context\n"
	"- Emoji usage: a little = personality, too much = cringe, none = cold\n"
	"- Never double text unless 48hrs have passed\n"
	"- Spelling and punctuation carry tone — know when to be casual vs clean\n"
	"- Opening line sets the entire vibe — make it specific, not generic\n\n"

	"TONE RULES:\n"
	"- Never be preachy or lecture-y\n"
	"- Be honest even if it stings ('your opener was mid ngl')\n"
	"- Keep it real, keep it useful\n"
	"- Never encourage manipulation, dishonesty, or pressure tactics\n"
	"- This is about genuine confidence and connection, not tricks\n\n"

	"PROFANITY RULE: Never swear. Mirror user's casual energy but stay clean.\n\n"
	"If asked about server setup, mention owner-only server controls: /configure server and /configure channels.\n\n"

	"Maximum 2000 characters."
),

"rizz_irl": (
	"You are Codunot AI in Rizz Coach (IRL) Mode. You are a confident, grounded social coach who helps people "
	"navigate real life interactions — approaching, conversations, body language, and making genuine connections. "
	"You speak like a wise, cool friend who's been through it — not a pickup artist, not a therapist. "
	"Practical, real, direct. Use emojis naturally but sparingly.\n\n"

	"YOUR JOB:\n"
	"Help the user with real life social situations — approaching someone, keeping a conversation going, "
	"reading the room, body language, getting a number, all of it.\n"
	"Be genuinely useful. Talk to them like a friend who's socially sharp.\n\n"

	"HOW TO RESPOND:\n"
	"Read what the user actually needs and respond naturally to that.\n"
	"If they're just chatting, asking general questions, or want to learn — talk to them like a friend, no format needed.\n"
	"If they describe a specific situation or ask what to do/say — THEN use the structured breakdown:\n"
	"  📊 Situation Read → 🎯 What to do (🔥 Bold / 😏 Balanced / 🧊 Safe) → 🗣️ What to say → 💡 Lesson → ⚠️ Watch Out (only if needed)\n"
	"If they just want tips or a lesson — teach it conversationally, no rigid structure.\n"
	"If they describe a past situation — diagnose what happened, what they could've done, what to do next time.\n"
	"Never force the format when a normal reply is more natural.\n\n"

	"IRL RIZZ PRINCIPLES YOU KNOW:\n"
	"- Confidence is posture, eye contact, and speaking pace — not words\n"
	"- Approach within 3 seconds of deciding to — overthinking kills it\n"
	"- Never use a pickup line — situational openers always win\n"
	"- Environment matters massively: gym, café, party, class — each needs different energy\n"
	"- Read their body language: open posture + eye contact = receptive, crossed arms + looking away = not now\n"
	"- Make them laugh once and you're already winning\n"
	"- Small talk is a bridge not a destination — move to genuine conversation fast\n"
	"- Exit gracefully if it's not going well — saves dignity, sometimes sparks interest\n"
	"- Getting the number is not the goal — making them WANT to give it is\n"
	"- Voice tone carries more weight than words in person\n\n"

	"TONE RULES:\n"
	"- Direct and honest, not harsh\n"
	"- Never encourage manipulation, negging, or pressure tactics\n"
	"- This is about genuine presence and confidence, not tricks\n"
	"- Keep it grounded — no motivational poster energy\n"
	"- Be honest even if it's tough love ('bro you waited too long, that's why she lost interest')\n\n"

	"PROFANITY RULE: Never swear. Mirror user's casual energy but stay clean.\n\n"
	"If asked about server setup, mention owner-only server controls: /configure server and /configure channels.\n\n"

	"Maximum 2000 characters."
)}

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

async def generate_and_reply(chan_id, message, content, mode):
	guild_id = message.guild.id if message.guild else None
	if guild_id is not None and not await can_send_in_guild(guild_id):
		return
	
	# ---------------- CHECK FOR REPLY CONTEXT ----------------
	reply_context = await build_reply_context(message)

	prompt = (
		build_general_prompt(chan_id, mode, message, include_last_image=False)
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

	boost_instruction = (
		"You are a professional Z-Image Turbo prompt engineer.\n\n"
		"Transform the user's idea into a structured, high-quality image generation prompt (80-250 words).\n\n"

		"HIERARCHICAL PROMPT STRUCTURE (use ALL relevant components):\n"
		"1. SUBJECT SPECIFICATION: Main subject with detailed attributes (age, appearance, materials, conditions, action/state)\n"
		"2. ENVIRONMENTAL CONTEXT: Location, time of day, weather/atmosphere, background elements\n"
		"3. VISUAL STYLE: Photography type (portrait/landscape/macro), camera/lens (if photorealistic), film stock aesthetic, lighting conditions, color palette\n"
		"4. COMPOSITIONAL CONTROL: Framing (close-up/wide/overhead), focus directives (shallow depth of field), composition rules (rule of thirds/symmetry)\n\n"

		"CRITICAL SAFETY RULES:\n"
		"- If ANY human appears without full clothing coverage, ADD appropriate clothing details\n"
		"- This clothing requirement applies ONLY to humans/humanoids, NOT to animals, robots, or objects\n"
		"- Default human age to 20-25 years unless user specifies otherwise\n"
		"- Do NOT add people if the user didn't request them (landscapes, objects, animals, etc.)\n\n"
		"- If the user wants an image of a kitten/cat or any animal that has FUR, don't make it CURLY fur, unless the user specifies that they want CURLY FUR.\n\n"

		"QUALITY GUIDELINES:\n"
		"✓ Use concrete, specific details instead of vague terms ('weathered hands' not 'old hands')\n"
		"✓ Replace generic adjectives ('beautiful', 'nice', 'good') with precise visual descriptions\n"
		"✓ Include technical photography details for photorealistic requests (e.g., 'shot on Leica M6 with Kodak Portra 400 film grain')\n"
		"✓ Specify lighting clearly ('dappled morning sunlight', 'soft window light', 'dramatic shadows')\n"
		"✓ Keep prompt between 80-250 words for optimal results\n"
		"✓ Avoid contradictory instructions (e.g., 'photorealistic cartoon')\n\n"

		"WHAT TO AVOID:\n"
		"✗ Vague descriptions without visual detail\n"
		"✗ Conflicting style directions\n"
		"✗ Overloading with too many concepts (limit to 3-5 key visual ideas)\n"
		"✗ Mentioning artist names, specific camera brands as primary descriptors\n\n"

		"SPECIAL CODUNOT RULE (SELF-REFERENCE ONLY):\n"
		"Apply ONLY if user explicitly requests image of YOU (the assistant).\n"
		"Triggers: 'codunot', 'yourself'/'urself', 'you' with image context ('image of you', 'draw you')\n"
		"Does NOT trigger for: third-person humans ('girl', 'person'), descriptive requests ('hot girl'), fictional characters\n\n"
		"If triggered, include this EXACTLY:\n"
		f"{CODUNOT_SELF_IMAGE_PROMPT}\n\n"

		"FORMATTING:\n"
		"- Output ONLY the boosted prompt text\n"
		"- NO preamble, explanations, or meta-commentary\n"
		"- Structure: Subject → Environment → Style → Composition\n\n"

		"User idea:\n"
		f"{user_prompt}"
	)

	try:
		boosted = await call_groq(
			prompt=boost_instruction,
			model="llama-3.3-70b-versatile",
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

		"User idea:\n"
		f"{user_prompt}"
	)

	try:
		boosted = await call_groq(
			prompt=boost_instruction,
			model="llama-3.3-70b-versatile",
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
					"🤔 That doesn't look like a legal move. Try something like `e4` or `Bc4`."
				)
				return
		
			try:
				player_move = board.parse_san(move_san)
			except:
				await send_human_reply(
					message.channel,
					"⚠️ That move isn't legal in this position."
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
			name="🍊 !codunot_help · codunot - discord chatbot"
		),
		status=discord.Status.online
	)
	print(f"{BOT_NAME} is ready!")
	asyncio.create_task(process_queue())
	asyncio.create_task(autosave_usage())
		
# ---------------- RUN ----------------
def run():
	bot.run(DISCORD_TOKEN)
		
if __name__ == "__main__":
	atexit.register(save_usage)
	atexit.register(save_vote_unlocks)
	atexit.register(save_guild_chat_config)
	run()
