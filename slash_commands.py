import discord
from discord import app_commands
from discord.ext import commands
import os
import ssl
import time
import io
import json
import aiohttp
import asyncio
import random
import traceback
import tempfile
import re
from typing import Optional
from urllib.parse import urlparse, quote_plus

import wavelink
import yt_dlp

from memory import MemoryManager
from test_api import generate_image, ImageAPIError
import requests
from deAPI_client_text2vid import generate_video as text_to_video_512
from deAPI_client_text2speech import text_to_speech
from deAPI_client_video_to_text import transcribe_video, wait_for_transcription_text, VideoToTextError
from google_ai_studio_client import call_google_ai_studio

from usage_manager import (
	check_limit,
	check_total_limit,
	consume,
	consume_total,
	save_usage,
	get_tier_from_message,
)

from topgg_utils import has_voted

memory = None
channel_modes = {}
channel_chess = {}
user_vote_unlocks = {}
chess_engine = None
OWNER_IDS = set()
VOTE_DURATION = 12 * 60 * 60
BYPASS_IDS = {1220934047794987048, 1167443519070290051}
BOT_NAME = "Codunot"
TTS_LANG_VOICES: dict[str, tuple[str, dict[str, str]]] = {
	"en-gb": ("English (GB)", {
		"Alice": "bf_alice", "Daniel": "bm_daniel", "Emma": "bf_emma",
		"Fable": "bm_fable", "George": "bm_george", "Isabella": "bf_isabella",
		"Lewis": "bm_lewis", "Lily": "bf_lily",
	}),
	"en-us": ("English (US)", {
		"Adam": "am_adam", "Alloy": "af_alloy", "Aoede": "af_aoede",
		"Bella": "af_bella", "Echo": "am_echo", "Eric": "am_eric",
		"Fenrir": "am_fenrir", "Heart": "af_heart", "Jessica": "af_jessica",
		"Kore": "af_kore", "Liam": "am_liam", "Michael": "am_michael",
		"Nicole": "af_nicole", "Nova": "af_nova", "Onyx": "am_onyx",
		"Puck": "am_puck", "River": "af_river", "Santa": "am_santa",
		"Sarah": "af_sarah", "Sky": "af_sky",
	}),
	"fr-fr": ("France", {"Siwis": "ff_siwis"}),
	"hi": ("Hindi", {
		"Alpha": "hf_alpha", "Beta": "hf_beta",
		"Omega": "hm_omega", "Psi": "hm_psi",
	}),
	"it": ("Italian", {"Nicola": "im_nicola", "Sara": "if_sara"}),
	"pt-br": ("Portugal (BR)", {
		"Alex": "pm_alex", "Dora": "pf_dora", "Santa": "pm_santa",
	}),
	"es": ("Spain", {
		"Alex": "em_alex", "Dora": "ef_dora", "Santa": "em_santa",
	}),
}
TTS_ALL_VOICES: dict[str, str] = {
	name: code
	for _, voices in TTS_LANG_VOICES.values()
	for name, code in voices.items()
}
TTS_VOICE_CODE_TO_NAME = {code: name for name, code in TTS_ALL_VOICES.items()}
boost_image_prompt = None
boost_video_prompt = None
save_vote_unlocks = None
set_server_mode = None
set_channels_mode = None
get_guild_config = None
pending_transcriptions: dict[str, int] = {}
guild_history: dict[int, list] = {}
guild_now_message: dict[int, dict] = {}
guild_queue_messages: dict[int, list] = {}
guild_ytdl_queue: dict[int, list] = {}
guild_last_text_channel: dict[int, int] = {}
guild_volume: dict[int, int] = {}
guild_last_activity = {}
_COOKIE_TEMP_FILE = None
_COOKIE_TEMP_PATH: str = ""

# ── Lavalink node ─────────────────────────────────────────────────────────────
LAVALINK_HOST = os.getenv("LAVALINK_HOST", "").strip()
try:
	LAVALINK_PORT = int(os.getenv("LAVALINK_PORT", "443"))
except ValueError:
	print("[LAVALINK] Invalid LAVALINK_PORT value, defaulting to 443")
	LAVALINK_PORT = 443
LAVALINK_PASSWORD = os.getenv("LAVALINK_PASSWORD", "")
LAVALINK_SECURE = os.getenv("LAVALINK_SECURE", "true").strip().lower() in ("true", "1", "yes")

# ── yt-dlp fallback ───────────────────────────────────────────────────────────

def _init_cookie_file() -> str:
	global _COOKIE_TEMP_FILE, _COOKIE_TEMP_PATH
	content = os.getenv("YTDL_COOKIE_CONTENT", "").strip()
	if not content:
		return os.getenv("YTDL_COOKIES_TXT", "").strip()
	if _COOKIE_TEMP_PATH:
		return _COOKIE_TEMP_PATH
	tmp = tempfile.NamedTemporaryFile(
		mode="w", suffix=".txt", delete=False, encoding="utf-8"
	)
	tmp.write(content)
	tmp.flush()
	tmp.close()
	_COOKIE_TEMP_FILE = tmp
	_COOKIE_TEMP_PATH = tmp.name
	return _COOKIE_TEMP_PATH

COOKIE_PATH: str = _init_cookie_file()

YTDL_OPTIONS = {
	"format": "bestaudio/best",
	"noplaylist": True,
	"quiet": True,
	"nocheckcertificate": True,
	"default_search": "ytsearch",
	"source_address": "0.0.0.0",
	"extractor_args": {"youtube": {"player_client": ["mweb", "web"]}},
}
FFMPEG_BEFORE_OPTIONS = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"

_NODE_CANDIDATES = [
	"/opt/hostedtoolcache/node/20.20.0/x64/bin/node",
	"/usr/local/bin/node",
	"/usr/bin/node",
]

def _find_node_path() -> str | None:
	for path in _NODE_CANDIDATES:
		if os.path.isfile(path):
			return path
	import shutil
	return shutil.which("node")

_NODE_PATH = _find_node_path()

def _get_ytdl_options(tier: str, allow_playlist: bool = False) -> dict:
	options = dict(YTDL_OPTIONS)
	options["format"] = "bestaudio/best" if tier in {"premium", "gold"} else "bestaudio[abr<=192]/bestaudio/best"
	if allow_playlist:
		options["noplaylist"] = False
	if COOKIE_PATH:
		options["cookiefile"] = COOKIE_PATH
	if _NODE_PATH:
		options["js_runtimes"] = {"node": {"path": _NODE_PATH}}
	return options

def _get_quality_label(tier: str) -> str:
	return "320kbps" if tier in {"premium", "gold"} else "HD"

def _get_ffmpeg_options() -> dict:
	return {"before_options": FFMPEG_BEFORE_OPTIONS, "options": "-vn"}

async def _ytdl_extract(queries: list[str], tier: str) -> dict:
	loop = asyncio.get_running_loop()
	last_error: Exception | None = None
	for query in queries:
		def _extract(q=query):
			opts = _get_ytdl_options(tier)
			with yt_dlp.YoutubeDL(opts) as ytdl:
				return ytdl.extract_info(q, download=False)
		try:
			data = await loop.run_in_executor(None, _extract)
			if not data:
				raise Exception("No data returned.")
			if "entries" in data:
				entries = [e for e in data.get("entries", []) if e]
				if not entries:
					raise Exception("No results found.")
				data = entries[0]
			return data
		except Exception as e:
			last_error = e
			continue
	raise last_error or Exception("No results found.")

async def _ytdl_extract_playlist(url: str, tier: str) -> list[dict]:
	"""Extract all tracks from a playlist URL via yt-dlp."""
	loop = asyncio.get_running_loop()
	def _extract():
		opts = _get_ytdl_options(tier, allow_playlist=True)
		with yt_dlp.YoutubeDL(opts) as ytdl:
			return ytdl.extract_info(url, download=False)
	data = await loop.run_in_executor(None, _extract)
	if not data:
		raise Exception("No data returned.")
	if "entries" in data:
		entries = [e for e in data.get("entries", []) if e]
		if not entries:
			raise Exception("No results found in playlist.")
		return entries
	return [data]


# ── Transcription config ──────────────────────────────────────────────────────

ALLOWED_TRANSCRIBE_HOSTS = (
	"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be",
	"twitch.tv", "www.twitch.tv", "x.com", "www.x.com",
	"twitter.com", "www.twitter.com", "kick.com", "www.kick.com",
)
ALLOWED_TRANSCRIBE_HOST_SUFFIXES = ("youtube.com", "twitch.tv", "x.com", "twitter.com", "kick.com")
TRANSCRIBE_HOST_NORMALIZATION = {
	"m.youtube.com": "www.youtube.com", "music.youtube.com": "www.youtube.com",
	"m.twitch.tv": "www.twitch.tv", "m.x.com": "x.com", "mobile.x.com": "x.com",
	"m.twitter.com": "twitter.com", "mobile.twitter.com": "twitter.com",
	"m.kick.com": "www.kick.com",
}

# ── URL helpers ───────────────────────────────────────────────────────────────

_SPOTIFY_HOSTS = {"open.spotify.com", "play.spotify.com"}
_YT_PLAYLIST_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
_SC_PLAYLIST_HOSTS = {"soundcloud.com", "www.soundcloud.com"}

def _looks_like_url(value: str) -> bool:
	try:
		parsed = urlparse(value)
		return parsed.scheme in ("http", "https") and bool(parsed.netloc)
	except Exception:
		return False

def _is_spotify_url(url: str) -> bool:
	return (urlparse(url).hostname or "").lower() in _SPOTIFY_HOSTS

def _is_playlist_url(url: str) -> bool:
	try:
		parsed = urlparse(url)
	except Exception:
		return False
	host = (parsed.hostname or "").lower()
	query = parsed.query or ""
	if host in _YT_PLAYLIST_HOSTS:
		if "v=" in query and "list=" in query:
			return False
		return "list=" in query
	if host in _SC_PLAYLIST_HOSTS:
		return "/sets/" in parsed.path
	if host in _SPOTIFY_HOSTS:
		path = parsed.path.lower()
		return path.startswith("/playlist/") or path.startswith("/album/")
	return False

def _build_query_candidates(song: str) -> list[str]:
	query = (song or "").strip()
	if _looks_like_url(query):
		return [query]
	if query.startswith("www."):
		return [f"https://{query}"]
	return [f"ytsearch1:{query}", f"scsearch1:{query}"]

def _format_duration_seconds(seconds: int | None) -> str:
	if not seconds or seconds <= 0:
		return "Unknown"
	seconds = int(seconds)
	minutes, secs = divmod(seconds, 60)
	hours, minutes = divmod(minutes, 60)
	if hours:
		return f"{hours}:{minutes:02d}:{secs:02d}"
	return f"{minutes}:{secs:02d}"


# ── GIF / Meme data ───────────────────────────────────────────────────────────

ACTION_GIF_SOURCES = {
	"hug": [
		"https://media1.giphy.com/media/v1.Y2lkPTc5MGI3NjExYjFxbWd0djU0Y240MHE3d2t3dnIyZWtsaGI0aTFleGVncWswcDdkYyZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/uakdGGShmMS0KYfTgp/giphy.gif",
		"https://media.tenor.com/bVN5MdTrelYAAAAj/yaseen1.gif",
		"https://media.tenor.com/FNX3Xvr6yGwAAAAi/snek-bubu.gif",
		"https://i.imgur.com/uXL0iTg.gif",
		"https://i.giphy.com/IzXiddo2twMmdmU8Lv.webp",
		"https://i.giphy.com/VbawWIGNtKYwOFXF7U.webp",
	],
	"kiss": [
		"https://i.giphy.com/G3va31oEEnIkM.webp", "https://i.giphy.com/bGm9FuBCGg4SY.webp",
		"https://c.tenor.com/dd4mZNppytYAAAAd/tenor.gif", "https://c.tenor.com/Y2AdPDiQoK8AAAAC/tenor.gif",
		"https://i.giphy.com/PBbFIL4bF8uS4.webp", "https://i.giphy.com/rFdqmnaIxx6qk.webp",
		"https://i.giphy.com/MqbZjCY1ghSAo.webp", "https://i.giphy.com/6Q9P2ry85GGOKbxKiC.webp",
	],
	"kick": [
		"https://i.giphy.com/DfI1LsaCkWD20xRc4r.webp", "https://i.giphy.com/3o7TKwVQMoQh2At9qU.webp",
		"https://media.tenor.com/TDQXdEBNNjUAAAAi/milk-and-mocha.gif",
		"https://media.tenor.com/ztHpFwsax84AAAAi/hau-zozo-smile.gif",
		"https://i.giphy.com/l3V0j3ytFyGHqiV7W.webp", "https://i.giphy.com/k3j9oaRV4FAT3ksIG1.webp",
		"https://i.giphy.com/xr9FpQBn2sPUOVtnNZ.webp", "https://i.giphy.com/RN96CaqhRoRHk4DlLV.webp",
		"https://i.giphy.com/qiiimDJtLj4XK.webp",
	],
	"slap": [
		"https://media.tenor.com/TVPYqh_E1JYAAAAj/peach-goma-peach-and-goma.gif",
		"https://media.tenor.com/tMVS_yML7t0AAAAj/slap-slaps.gif",
		"https://c.tenor.com/OTr4wv64hwwAAAAd/tenor.gif", "https://c.tenor.com/4Ut_QPbeCZIAAAAd/tenor.gif",
		"https://c.tenor.com/LHlITawhrEcAAAAd/tenor.gif", "https://i.giphy.com/3oriNXBCGHrzCYIbZK.webp",
		"https://i.giphy.com/qyjexFwQwJp9yUvMxq.webp", "https://i.giphy.com/RYOYNPbKoRORepL80E.webp",
	],
	"wish_goodmorning": [
		"https://media.tenor.com/xwlZJGC0EqwAAAAj/pengu-pudgy.gif",
		"https://media.tenor.com/4pnZsJP06XMAAAAj/have-a-great-day-good-day.gif",
		"https://media.tenor.com/xlwtvJtC6FAAAAAM/jjk-jujutsu-kaisen.gif",
		"https://c.tenor.com/6VbeqshMfkEAAAAd/tenor.gif",
		"https://i.giphy.com/jhQ6s2Qwjhqpivlitm.webp", "https://i.giphy.com/GjfNsZPvCFs9dQrw36.webp",
	],
}

ACTION_MESSAGES = {
	"hug": [
		"🤗 {user} wrapped {target} in a giant cozy hug!",
		"💞 {user} gave {target} the warmest cuddle ever.",
		"🐻 {user} bear-hugged {target} with max affection.",
		"✨ {user} hugged {target} and instantly improved the vibe.",
		"🌈 {user} sent a comfort hug straight to {target}.",
		"🫶 {user} gave {target} a wholesome squeeze.",
		"☁️ {user} hugged {target} like a fluffy cloud.",
		"🎉 {user} rushed over and hugged {target} in celebration!",
		"💖 {user} shared a heart-melting hug with {target}.",
		"🌟 {user} delivered a legendary friendship hug to {target}.",
	],
	"kiss": [
		"💋🥰{user} gave {target} a sweet kiss!",
		"🌹💋 {user} kissed {target} and left everyone blushing.",
		"✨💋 {user} sent {target} a dramatic movie-scene kiss.",
		"💕💋 {user} gave {target} a soft little kiss.",
		"🥰💋 {user} kissed {target} with pure wholesome energy.",
		"🎀💋 {user} surprised {target} with an adorable kiss.",
		"💞💋 {user} planted a lovely kiss on {target}.",
		"🌟💋 {user} kissed {target} and sparkles appeared everywhere.",
		"🫣💋 {user} stole a quick kiss from {target}!",
		"🍓💋 {user} gave {target} a super cute kiss.",
	],
	"kick": [
		"🥋 {user} launched a playful kick at {target}!",
		"💥 {user} drop-kicked {target} into cartoon physics.",
		"⚡ {user} gave {target} a turbo ninja kick.",
		"🎯 {user} landed a clean anime kick on {target}.",
		"🌀 {user} spin-kicked {target} with style.",
		"🔥 {user} kicked {target} straight into next week.",
		"😤 {user} delivered a dramatic boss-fight kick to {target}.",
		"👟 {user} punted {target} with comedic precision.",
		"📢 {user} yelled 'HIYAA!' and kicked {target}.",
		"🏆 {user} scored a perfect kick combo on {target}.",
	],
	"slap": [
		"🖐️ {user} slapped {target} with cartoon force!",
		"💢 {user} delivered a dramatic anime slap to {target}.",
		"⚡ {user} gave {target} a lightning-fast slap.",
		"🎬 {user} slapped {target} like a soap-opera finale.",
		"👋 {user} landed a playful slap on {target}.",
		"🌪️ {user} windmill-slapped {target} into silence.",
		"😳 {user} gave {target} a surprise slap for the plot.",
		"🎯 {user} slapped {target} with perfect timing.",
		"🔥 {user} unleashed a spicy slap on {target}.",
		"📢 {user} slapped {target} and the crowd went wild.",
	],
	"wish_goodmorning": [
		"🌅 {user} wished {target} a bright and beautiful morning!",
		"☀️ {user} sent {target} a cheerful good morning wish.",
		"🌼 {user} told {target}: good morning, sunshine!",
		"☕ {user} handed {target} a coffee and said good morning.",
		"🐣 {user} wished {target} the happiest morning ever.",
		"🌞 {user} greeted {target} with a warm good morning.",
		"✨ {user} wished {target} a fresh start and good vibes.",
		"🍳 {user} served breakfast vibes and wished {target} good morning!",
		"🎶 {user} sang a tiny good morning song for {target}.",
		"💛 {user} wished {target} a cozy, wonderful morning.",
	],
}

MEME_SOURCES = [
	"https://i.imgur.com/giaxzSP.jpeg", "https://i.imgur.com/ELuCb1H.jpeg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/relatable-memes-jokes-memespointt-10-677cf9f8b57aa__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/relatable-memes-jokes-memespointt-35-677e714a64c1c__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/relatable-memes-jokes-memespointt-32-677e7089d37ed__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/relatable-memes-jokes-memespointt-37-677e71d07e283__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/relatable-memes-jokes-memespointt-19-677d015a22631__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/relatable-memes-jokes-memespointt-4-677cf70d35587__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/relatable-memes-jokes-memespointt-2-677cf62608ccb__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/relatable-memes-jokes-memespointt-6-677cf836e20bd__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/relatable-memes-jokes-memespointt-14-677cfece125a2__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/relatable-memes-jokes-memespointt-27-677d12eff1187__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/relatable-memes-jokes-memespointt-39-677e72289295d__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/relatable-memes-jokes-memespointt-30-677d14da83f61__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/Cw95ZfXSSkf-png__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/CyGhEAHSRoY-png__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/relatable-memes-jokes-memespointt-43-677e7303d7dd4__700.jpg",
]


async def fetch_bytes(url: str) -> bytes:
	async with aiohttp.ClientSession() as session:
		async with session.get(url) as resp:
			if resp.status != 200:
				raise Exception(f"Failed to fetch: HTTP {resp.status}")
			return await resp.read()


# ── Music Controls View ───────────────────────────────────────────────────────

class MusicControls(discord.ui.View):
	def __init__(self, cog, guild_id: int):
		super().__init__(timeout=None)
		self.cog = cog
		self.guild_id = guild_id

	async def interaction_check(self, interaction: discord.Interaction) -> bool:
		await interaction.response.defer()
		return await self.cog._ensure_music_control(interaction)

	@discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary)
	async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
		await self.cog._music_previous(interaction)

	@discord.ui.button(emoji="⏸️", style=discord.ButtonStyle.secondary)
	async def pause_button(self, interaction: discord.Interaction, button: discord.ui.Button):
		await self.cog._music_pause(interaction)

	@discord.ui.button(emoji="▶️", style=discord.ButtonStyle.secondary)
	async def resume_button(self, interaction: discord.Interaction, button: discord.ui.Button):
		await self.cog._music_resume(interaction)

	@discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary)
	async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
		await self.cog._music_next(interaction)

	@discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger)
	async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
		await self.cog._music_stop(interaction)


# ── Vote helpers ──────────────────────────────────────────────────────────────

def _build_vote_embed() -> discord.Embed:
	embed = discord.Embed(
		title="🔒 Vote Required to Unlock This Feature",
		description=(
			"This feature is locked behind a **free vote** on Top.gg!\n"
			"Vote once every 12 hours to unlock a ton of powerful features 💙"
		),
		color=0x5865F2
	)
	embed.add_field(name="🎨 Creative Tools", value=(
		"• 🖼️ **Image Analysis** — send any image\n"
		"• 🎨 **Generate Image** — `/generate_image`\n"
		"• 🖌️ **Edit Images** — send image + instruction\n"
		"• 🖼️ **Merge Images** — attach 2+ images + say merge\n"
		"• 🎬 **Generate Video** — `/generate_video`\n"
		"• 🔊 **Text-to-Speech** — `/generate_tts` (voice & language, min 20 chars)\n"
		"• 🎵 **Play Music** — `/play [song/URL]` in voice channels"
	), inline=False)
	embed.add_field(name="📁 File Tools", value=(
		"• 📄 **PDF Reading** — upload any PDF\n"
		"• 📝 **DOCX Reading** — upload Word documents\n"
		"• 📃 **TXT Reading** — upload text files\n"
		"• 🔍 **Smart Summaries** — get instant file summaries"
	), inline=False)
	embed.add_field(name="⏱️ How It Works", value=(
		"1️⃣ Click **Vote Now** below\n"
		"2️⃣ Vote on Top.gg (takes 10 seconds!)\n"
		"3️⃣ Your vote gets registered instantly!\n"
		"4️⃣ All features unlock for **12 hours** 🎉\n"
		"5️⃣ Vote again after 12 hours to keep access"
	), inline=False)
	embed.set_footer(text="🗳️ Voting is completely free and takes 10 seconds!")
	return embed

def _build_vote_view() -> discord.ui.View:
	view = discord.ui.View(timeout=None)
	view.add_item(discord.ui.Button(
		label="🗳️ Vote Now",
		url="https://top.gg/bot/1435987186502733878/vote",
		style=discord.ButtonStyle.link
	))
	return view

async def check_vote_status(user_id: int) -> bool:
	if user_id in OWNER_IDS:
		return True
	if user_id in BYPASS_IDS:
		return True
	now = time.time()
	unlock_time = user_vote_unlocks.get(user_id)
	if unlock_time and (now - unlock_time) < VOTE_DURATION:
		return True
	if await has_voted(user_id):
		user_vote_unlocks[user_id] = now
		if save_vote_unlocks:
			save_vote_unlocks()
		return True
	return False

async def require_vote_deferred(interaction: discord.Interaction) -> bool:
	voted = await check_vote_status(interaction.user.id)
	if not voted:
		await interaction.edit_original_response(
			content=None, embed=_build_vote_embed(), view=_build_vote_view()
		)
	return voted

async def require_vote_slash(interaction: discord.Interaction) -> bool:
	voted = await check_vote_status(interaction.user.id)
	if not voted:
		await interaction.response.send_message(
			embed=_build_vote_embed(), view=_build_vote_view(), ephemeral=False
		)
	return voted


# ── Configure group ───────────────────────────────────────────────────────────

class ConfigureGroup(app_commands.Group):
	def __init__(self):
		super().__init__(name="configure", description="Configure where the bot can chat in this server")

	async def _ensure_guild_owner(self, interaction: discord.Interaction) -> bool:
		if interaction.guild is None:
			await interaction.response.send_message("❌ This command can only be used inside a server.", ephemeral=True)
			return False
		if interaction.guild.owner_id != interaction.user.id:
			if interaction.response.is_done():
				await interaction.followup.send("❌ You are not the server owner.", ephemeral=True)
			else:
				await interaction.response.send_message("❌ You are not the server owner.", ephemeral=True)
			return False
		if set_server_mode is None or set_channels_mode is None or get_guild_config is None:
			await interaction.response.send_message("⚠️ Configuration system is not ready.", ephemeral=True)
			return False
		return True

	@app_commands.command(name="server", description="Allow the bot to chat in all channels in this server")
	async def configure_server(self, interaction: discord.Interaction):
		if not await self._ensure_guild_owner(interaction):
			return
		channel_ids = [ch.id for ch in interaction.guild.text_channels]
		set_server_mode(interaction.guild.id, channel_ids)
		await interaction.response.send_message(
			"✅ Configuration updated: I can now chat in **the whole server** when pinged.", ephemeral=False
		)

	@app_commands.command(name="channels", description="Restrict bot chat to selected channel(s) in this server")
	@app_commands.describe(
		channel_1="Required channel", channel_2="Optional channel",
		channel_3="Optional channel", channel_4="Optional channel", channel_5="Optional channel",
	)
	async def configure_channels(
		self, interaction: discord.Interaction,
		channel_1: app_commands.AppCommandChannel,
		channel_2: Optional[app_commands.AppCommandChannel] = None,
		channel_3: Optional[app_commands.AppCommandChannel] = None,
		channel_4: Optional[app_commands.AppCommandChannel] = None,
		channel_5: Optional[app_commands.AppCommandChannel] = None,
	):
		if not await self._ensure_guild_owner(interaction):
			return
		selected_channels = [ch for ch in [channel_1, channel_2, channel_3, channel_4, channel_5] if ch is not None]
		channel_ids = [ch.id for ch in selected_channels]
		set_channels_mode(interaction.guild.id, channel_ids)
		mentions = ", ".join(f"<#{ch.id}>" for ch in selected_channels)
		await interaction.response.send_message(
			f"✅ Configuration updated: I will now only chat in these channel(s): {mentions}", ephemeral=False
		)

	@configure_server.error
	@configure_channels.error
	async def configure_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
		print(f"[CONFIGURE ERROR] {error}")
		msg = "❌ Couldn't complete this configure request."
		if interaction.response.is_done():
			await interaction.followup.send(msg, ephemeral=True)
		else:
			await interaction.response.send_message(msg, ephemeral=True)


# ── Main Cog ──────────────────────────────────────────────────────────────────

class Codunot(commands.Cog):
	def __init__(self, bot: commands.Bot):
		self.bot = bot
		self.bot.tree.add_command(ConfigureGroup())
		self._lavalink_session: aiohttp.ClientSession | None = None

	# ── Lavalink connect ──────────────────────────────────────────────────────

	async def cog_load(self):
		if not LAVALINK_HOST:
			print("[LAVALINK] No LAVALINK_HOST configured — Lavalink disabled, Spotify will use yt-dlp fallback")
			return
		# Build a custom session with relaxed SSL to work around
		# TLSV1_UNRECOGNIZED_NAME errors on some Lavalink hosts.
		session: aiohttp.ClientSession | None = None
		if LAVALINK_SECURE:
			ctx = ssl.create_default_context()
			ctx.check_hostname = False
			ctx.verify_mode = ssl.CERT_NONE
			connector = aiohttp.TCPConnector(ssl=ctx)
			session = aiohttp.ClientSession(connector=connector)
			self._lavalink_session = session
		node = wavelink.Node(
			uri=f"{'https' if LAVALINK_SECURE else 'http'}://{LAVALINK_HOST}:{LAVALINK_PORT}",
			password=LAVALINK_PASSWORD,
			session=session,
			retries=3,
		)
		try:
			await wavelink.Pool.connect(nodes=[node], client=self.bot, cache_capacity=100)
			print(f"[LAVALINK] Connected to {LAVALINK_HOST}")
		except Exception as e:
			print(f"[LAVALINK] Failed to connect: {e} — Spotify will use yt-dlp fallback")
			try:
				await wavelink.Pool.close()
			except Exception as close_err:
				print(f"[LAVALINK] Pool cleanup error: {close_err}")

	async def cog_unload(self):
		try:
			await wavelink.Pool.close()
		except Exception:
			pass
		if self._lavalink_session and not self._lavalink_session.closed:
			await self._lavalink_session.close()

	def _lavalink_available(self) -> bool:
		try:
			nodes = wavelink.Pool.nodes
			return bool(nodes)
		except Exception:
			return False

	# ── Wavelink event ────────────────────────────────────────────────────────

	@commands.Cog.listener()
	async def on_wavelink_track_end(self, payload: wavelink.TrackEndEventPayload):
		player: wavelink.Player = payload.player
		if not player:
			return
		guild_id = player.guild.id
		print(f"[WAVELINK] Track ended for guild {guild_id}, reason={payload.reason}")
		if payload.reason in ("finished", "loadFailed"):
			await self._wavelink_auto_advance(guild_id, player)

	async def _wavelink_auto_advance(self, guild_id: int, player: wavelink.Player):
		await self._mark_now_playing_as_ended(guild_id)
		queue = player.queue
		if queue.is_empty:
			print(f"[WAVELINK] Queue empty, going idle for guild {guild_id}")
			guild_last_activity[guild_id] = asyncio.get_event_loop().time()
			asyncio.create_task(self._start_idle_timer(guild_id))
			return
		next_track = queue.get()
		try:
			await player.play(next_track)
			embed = self._build_now_playing_embed_from_wl(next_track, guild_id)
			view = MusicControls(self, guild_id)
			await self._post_now_playing(guild_id, embed, view)
		except Exception as e:
			print(f"[WAVELINK] Auto-advance error: {e}")

	# ── yt-dlp fallback engine ────────────────────────────────────────────────
	# Used when Lavalink is down or fails

	async def _start_idle_timer(self, guild_id: int):
		await asyncio.sleep(600)
		guild = self.bot.get_guild(guild_id)
		if guild is None:
			return
		voice_client = guild.voice_client
		if not voice_client:
			return
		if hasattr(voice_client, 'is_playing') and (voice_client.is_playing() or voice_client.is_paused()):
			return
		last = guild_last_activity.get(guild_id, 0)
		now = asyncio.get_event_loop().time()
		if now - last >= 600:
			try:
				await voice_client.disconnect()
				print(f"[MUSIC] Disconnected due to 10m inactivity guild={guild_id}")
			except Exception as e:
				print(f"[MUSIC] Disconnect error: {e}")

	async def _mark_now_playing_as_ended(self, guild_id: int):
		from collections import defaultdict
		message_info = guild_now_message.get(guild_id)
		if not message_info:
			return
		channel_id = message_info.get("channel_id")
		message_id = message_info.get("message_id")
		title = message_info.get("title", "Unknown")
		try:
			guild = self.bot.get_guild(guild_id)
			if guild is None:
				return
			channel = guild.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
			message = await channel.fetch_message(message_id)
			ended_embed = discord.Embed(title="⏹️ Ended", description=title, color=0x5C5C5C)
			ended_embed.set_footer(text="Song finished playing")
			await message.edit(embed=ended_embed, view=None)
		except Exception as e:
			print(f"[MUSIC] Failed to mark now-playing as ended: {e}")

	async def _post_now_playing(self, guild_id: int, embed: discord.Embed, view: discord.ui.View):
		queue_messages = guild_queue_messages.setdefault(guild_id, [])
		guild = self.bot.get_guild(guild_id)
		promoted = False

		if queue_messages:
			queued_msg_info = queue_messages.pop(0)
			try:
				channel = guild.get_channel(queued_msg_info["channel_id"]) or await self.bot.fetch_channel(queued_msg_info["channel_id"])
				message = await channel.fetch_message(queued_msg_info["message_id"])
				await message.edit(content=None, embed=embed, view=view)
				guild_now_message[guild_id] = {
					"channel_id": channel.id, "message_id": message.id,
					"title": embed.description or "Unknown"
				}
				promoted = True
			except Exception as e:
				print(f"[MUSIC] Failed to promote queued message: {e}")

		if not promoted:
			channel_id = guild_last_text_channel.get(guild_id)
			if channel_id:
				try:
					channel = guild.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
					message = await channel.send(embed=embed, view=view)
					guild_now_message[guild_id] = {
						"channel_id": channel.id, "message_id": message.id,
						"title": embed.description or "Unknown"
					}
				except Exception as e:
					print(f"[MUSIC] Failed to send now-playing: {e}")

	# ── Embed builders ────────────────────────────────────────────────────────

	def _build_now_playing_embed_from_wl(self, track: wavelink.Playable, guild_id: int) -> discord.Embed:
		title = track.title or "Unknown title"
		url = track.uri
		author = track.author or "Unknown"
		duration = _format_duration_seconds(track.length // 1000 if track.length else None)
		artwork = track.artwork

		description = f"[{title}]({url})" if url else title
		embed = discord.Embed(title="🎵 Now Playing", description=description, color=0x1DB954)
		if artwork:
			embed.set_thumbnail(url=artwork)
		embed.add_field(name="Artist", value=author, inline=True)
		embed.add_field(name="Duration", value=duration, inline=True)
		embed.add_field(name="Source", value="Lavalink", inline=True)
		embed.set_footer(text="Powered by Lavalink • nextgencoders.xyz")
		return embed

	def _build_now_playing_embed_from_ytdl(self, info: dict, requested_by: str, tier: str) -> discord.Embed:
		title = info.get("title") or "Unknown title"
		web_url = info.get("webpage_url") or info.get("url")
		uploader = info.get("uploader") or info.get("channel") or "Unknown"
		duration = _format_duration_seconds(info.get("duration"))
		thumbnail = info.get("thumbnail")
		quality = _get_quality_label(tier)

		description = f"[{title}]({web_url})" if web_url else title
		embed = discord.Embed(title="🎵 Now Playing", description=description, color=0x1DB954)
		if thumbnail:
			embed.set_thumbnail(url=thumbnail)
		embed.add_field(name="Artist/Channel", value=uploader, inline=True)
		embed.add_field(name="Duration", value=duration, inline=True)
		embed.add_field(name="Requested By", value=requested_by, inline=True)
		embed.add_field(name="Quality", value=quality, inline=True)
		embed.set_footer(text="HD free • 320kbps for Premium/Gold")
		return embed

	# ── Music control helpers ─────────────────────────────────────────────────

	def _dm_usage_key(self, interaction: discord.Interaction) -> str:
		return f"dm_{interaction.user.id}"

	def _bot_missing_from_guild(self, interaction: discord.Interaction) -> bool:
		if interaction.guild_id is None:
			return False
		guild = self.bot.get_guild(interaction.guild_id)
		if guild is None:
			return True
		return guild.get_member(self.bot.user.id) is None

	async def _resolve_paid_usage_key(self, interaction: discord.Interaction) -> str | None:
		if not self._bot_missing_from_guild(interaction):
			return None
		try:
			dm_channel = interaction.user.dm_channel or await interaction.user.create_dm()
			if dm_channel is not None:
				return str(dm_channel.id)
		except Exception as e:
			print(f"[PAID USAGE KEY] {e}")
		return self._dm_usage_key(interaction)

	def _should_deliver_paid_output_in_dm(self, interaction: discord.Interaction) -> bool:
		return self._bot_missing_from_guild(interaction)

	async def _deliver_paid_attachment(self, interaction, content, filename, payload_bytes):
		if not self._should_deliver_paid_output_in_dm(interaction):
			await interaction.followup.send(
				content=content, file=discord.File(io.BytesIO(payload_bytes), filename=filename)
			)
			return
		try:
			await interaction.user.send(
				f"{content}\n\n📩 Sent to DMs since I'm not in that server.",
				file=discord.File(io.BytesIO(payload_bytes), filename=filename),
			)
			await interaction.followup.send("📩 Result sent to your DMs.")
		except discord.Forbidden:
			await interaction.followup.send("⚠️ Couldn't DM you — please enable DMs and try again.")

	async def _ensure_music_control(self, interaction: discord.Interaction) -> bool:
		if interaction.guild is None:
			await interaction.followup.send("❌ This can only be used in a server.", ephemeral=False)
			return False
		voice_client = interaction.guild.voice_client
		if not voice_client or not voice_client.is_connected():
			await interaction.followup.send("❌ I'm not connected to a voice channel.", ephemeral=False)
			return False
		user_voice = interaction.user.voice
		if not user_voice or user_voice.channel.id != voice_client.channel.id:
			await interaction.followup.send(f"🎧 Join {voice_client.channel.mention} to control playback.", ephemeral=False)
			return False
		return True

	# ── Queue command ─────────────────────────────────────────────────────────

	@app_commands.command(name="queue", description="📋 Show the current music queue")
	async def queue_slash(self, interaction: discord.Interaction):
		if interaction.guild is None:
			await interaction.response.send_message("❌ This can only be used in a server.", ephemeral=True)
			return

		player: wavelink.Player | None = interaction.guild.voice_client if self._lavalink_available() else None
		embed = discord.Embed(title="📋 Music Queue", color=0x1DB954)

		if player and isinstance(player, wavelink.Player):
			current = player.current
			queue = player.queue
			if not current and queue.is_empty:
				await interaction.response.send_message("❌ The queue is empty and nothing is playing.", ephemeral=False)
				return
			if current:
				duration = _format_duration_seconds(current.length // 1000 if current.length else None)
				url = current.uri
				display = f"[{current.title}]({url})" if url else current.title
				embed.add_field(name="🎵 Now Playing", value=f"{display} `{duration}`", inline=False)
			if not queue.is_empty:
				lines = []
				for i, track in enumerate(list(queue)[:15], start=1):
					duration = _format_duration_seconds(track.length // 1000 if track.length else None)
					url = track.uri
					display = f"[{track.title}]({url})" if url else track.title
					lines.append(f"`{i}.` {display} `{duration}`")
				count = len(queue)
				if count > 15:
					lines.append(f"*...and {count - 15} more*")
				embed.add_field(name=f"⏳ Up Next ({count} tracks)", value="\n".join(lines), inline=False)
			else:
				embed.add_field(name="⏳ Up Next", value="Queue is empty.", inline=False)
		else:
			await interaction.response.send_message("❌ Nothing is playing right now.", ephemeral=False)
			return

		await interaction.response.send_message(embed=embed, ephemeral=False)

	# ── Music controls ────────────────────────────────────────────────────────

	async def _music_pause(self, interaction: discord.Interaction):
		player: wavelink.Player = interaction.guild.voice_client
		if player and isinstance(player, wavelink.Player) and player.playing:
			await player.pause(not player.paused)
			state = "⏸️ Paused." if player.paused else "▶️ Resumed."
			await interaction.followup.send(state, ephemeral=False)
		else:
			await interaction.followup.send("❌ Nothing is playing.", ephemeral=False)

	async def _music_resume(self, interaction: discord.Interaction):
		player: wavelink.Player = interaction.guild.voice_client
		if player and isinstance(player, wavelink.Player) and player.paused:
			await player.pause(False)
			await interaction.followup.send("▶️ Resumed.", ephemeral=False)
		else:
			await interaction.followup.send("❌ Nothing is paused.", ephemeral=False)

	async def _music_stop(self, interaction: discord.Interaction):
		player: wavelink.Player = interaction.guild.voice_client
		if player and isinstance(player, wavelink.Player):
			player.queue.clear()
			await player.stop()
			await player.disconnect()
		elif player:
			guild_ytdl_queue.pop(interaction.guild.id, None)
			player.stop()
			try:
				await player.disconnect(force=True)
			except Exception:
				pass
		guild_queue_messages.pop(interaction.guild.id, None)
		guild_now_message.pop(interaction.guild.id, None)
		ended_embed = discord.Embed(title="⏹️ Ended", description="Playback stopped.", color=0x5C5C5C)
		ended_embed.set_footer(text="Playback stopped • Queue cleared")
		try:
			await interaction.message.edit(embed=ended_embed, view=None)
		except Exception:
			await interaction.followup.send("⏹️ Stopped and disconnected.", ephemeral=False)

	async def _music_next(self, interaction: discord.Interaction):
		player: wavelink.Player = interaction.guild.voice_client
		if not player or not isinstance(player, wavelink.Player):
			# yt-dlp fallback skip
			vc = interaction.guild.voice_client
			if vc and hasattr(vc, 'is_playing') and vc.is_playing():
				queue = guild_ytdl_queue.get(interaction.guild.id, [])
				if not queue:
					await interaction.followup.send("❌ Queue is empty.", ephemeral=False)
					return
				vc.stop()  # triggers _after_playback → _ytdl_auto_advance
				await interaction.followup.send("⏭️ Skipped.", ephemeral=False)
				return
			await interaction.followup.send("❌ Not connected.", ephemeral=False)
			return
		if player.queue.is_empty:
			await interaction.followup.send("❌ Queue is empty.", ephemeral=False)
			return
		await player.stop()
		await interaction.followup.send("⏭️ Skipped.", ephemeral=False)

	async def _music_previous(self, interaction: discord.Interaction):
		history = guild_history.get(interaction.guild.id, [])
		if not history:
			await interaction.followup.send("❌ No previous tracks.", ephemeral=False)
			return
		previous_track = history.pop()
		player: wavelink.Player = interaction.guild.voice_client
		if not player or not isinstance(player, wavelink.Player):
			await interaction.followup.send("❌ Not connected.", ephemeral=False)
			return
		# Re-insert current track at front of queue
		if player.current:
			player.queue.put_at(0, player.current)
		await player.play(previous_track)
		embed = self._build_now_playing_embed_from_wl(previous_track, interaction.guild.id)
		view = MusicControls(self, interaction.guild.id)
		guild_last_text_channel[interaction.guild.id] = interaction.channel.id
		guild_now_message[interaction.guild.id] = {
			"channel_id": interaction.channel.id,
			"message_id": interaction.message.id,
			"title": embed.description or "Unknown",
		}
		try:
			await interaction.message.edit(embed=embed, view=view)
		except Exception:
			await interaction.followup.send(embed=embed, view=view)

	async def _music_adjust_volume(self, interaction: discord.Interaction, delta: int):
		"""Adjust guild playback volume by delta percentage points within 10%-200%."""
		voice_client = interaction.guild.voice_client
		if not voice_client or not voice_client.is_connected():
			await interaction.followup.send("❌ I'm not connected to a voice channel.", ephemeral=True)
			return

		guild_id = interaction.guild.id
		current = guild_volume.get(guild_id, 100)
		new_volume = max(10, min(200, current + delta))
		if new_volume == current:
			await interaction.followup.send(f"🔊 Volume is already at **{new_volume}%**.", ephemeral=True)
			return

		guild_volume[guild_id] = new_volume
		if isinstance(voice_client, wavelink.Player):
			await voice_client.set_volume(new_volume)
		elif isinstance(getattr(voice_client, "source", None), discord.PCMVolumeTransformer):
			voice_client.source.volume = new_volume / 100

		await interaction.followup.send(f"🔊 Volume set to **{new_volume}%**.", ephemeral=True)

	# ── Play command ──────────────────────────────────────────────────────────

	@app_commands.command(
		name="play",
		description="🎵 Play a song or playlist (YouTube, SoundCloud, Spotify)"
	)
	@app_commands.describe(song="Song name, URL, or playlist URL")
	async def play_slash(self, interaction: discord.Interaction, song: str):
		if interaction.guild is None:
			await interaction.response.send_message("❌ Server only.", ephemeral=True)
			return
		if not interaction.user.voice or not interaction.user.voice.channel:
			await interaction.response.send_message("🤔 Join a voice channel first, then use `/play [song name]` to start jamming! 🎵", ephemeral=True)
			return

		await interaction.response.defer()
		await interaction.edit_original_response(content="🗳️ Checking your vote status...")

		if not await require_vote_deferred(interaction):
			return

		await interaction.edit_original_response(content="🎵 Joining voice channel...")

		channel = interaction.user.voice.channel
		tier = get_tier_from_message(interaction)
		guild_last_text_channel[interaction.guild.id] = interaction.channel.id

		# ── Spotify → Lavalink ───────────────────────────────────────────────
		if _is_spotify_url(song) and self._lavalink_available():
			try:
				player: wavelink.Player = interaction.guild.voice_client
				if not player or not isinstance(player, wavelink.Player):
					player = await channel.connect(cls=wavelink.Player)
				elif player.channel.id != channel.id:
					await interaction.edit_original_response(
						content=f"❌ I'm already in {player.channel.mention}."
					)
					return
				await player.set_volume(guild_volume.get(interaction.guild.id, 100))

				await interaction.edit_original_response(content="🔍 Searching Spotify via Lavalink...")

				tracks = await wavelink.Playable.search(song)
				if not tracks:
					raise Exception("No results found.")

				if isinstance(tracks, wavelink.Playlist):
					added = 0
					first_track = None
					for track in tracks.tracks:
						if first_track is None and not player.playing:
							first_track = track
							await player.play(track)
						else:
							player.queue.put(track)
						added += 1

					embed = self._build_now_playing_embed_from_wl(
						first_track or tracks.tracks[0], interaction.guild.id
					)
					view = MusicControls(self, interaction.guild.id)
					status = f"📋 Playlist loaded! Playing first track, **{added - 1}** more queued."
					message = await interaction.followup.send(content=status, embed=embed, view=view, wait=True)
					guild_now_message[interaction.guild.id] = {
						"channel_id": message.channel.id, "message_id": message.id,
						"title": embed.description or "Unknown",
					}
				else:
					track = tracks[0] if isinstance(tracks, list) else tracks
					if player.playing:
						player.queue.put(track)
						position = len(player.queue)
						queued_msg = await interaction.followup.send(
							f"✅ Queued **{track.title}** at position {position}.", wait=True
						)
						queue_messages = guild_queue_messages.setdefault(interaction.guild.id, [])
						queue_messages.append({"channel_id": queued_msg.channel.id, "message_id": queued_msg.id})
					else:
						await player.play(track)
						history = guild_history.setdefault(interaction.guild.id, [])
						if len(history) > 25:
							history.pop(0)

						embed = self._build_now_playing_embed_from_wl(track, interaction.guild.id)
						view = MusicControls(self, interaction.guild.id)
						message = await interaction.followup.send(embed=embed, view=view, wait=True)
						guild_now_message[interaction.guild.id] = {
							"channel_id": message.channel.id, "message_id": message.id,
							"title": embed.description or "Unknown",
						}
				return

			except Exception as e:
				print(f"[LAVALINK] Spotify play error: {e}")
				await interaction.edit_original_response(
					content=f"❌ Lavalink failed to load this Spotify link: {e}"
				)
				return

		# ── Everything else → yt-dlp ─────────────────────────────────────────

		voice_client = interaction.guild.voice_client
		try:
			if voice_client and voice_client.is_connected():
				if hasattr(voice_client, 'channel') and voice_client.channel.id != channel.id:
					await interaction.edit_original_response(
						content=f"❌ I'm already in {voice_client.channel.mention}."
					)
					return
			else:
				if voice_client:
					try:
						await voice_client.disconnect(force=True)
					except Exception:
						pass
				voice_client = await channel.connect()
		except Exception as e:
			print(f"[YTDL] Voice connect error: {e}")
			await interaction.edit_original_response(content="❌ Couldn't connect to your voice channel.")
			return

		await interaction.edit_original_response(content="🔍 Searching...")

		# ── Playlist handling ────────────────────────────────────────────
		if _is_playlist_url(song):
			try:
				entries = await _ytdl_extract_playlist(song, tier)
			except Exception as e:
				print(f"[YTDL] Playlist extraction error: {e}")
				await interaction.edit_original_response(content="❌ Couldn't load that playlist.")
				return

			if not entries:
				await interaction.edit_original_response(content="❌ Playlist appears to be empty.")
				return

			first = entries[0]
			stream_url = first.get("url")
			if not stream_url:
				await interaction.edit_original_response(content="❌ Couldn't get a stream URL for the first track.")
				return

			# Queue remaining tracks
			remaining = entries[1:]
			queue = guild_ytdl_queue.setdefault(interaction.guild.id, [])
			for entry in remaining:
				if entry.get("url"):
					queue.append({
						"title": entry.get("title") or "Unknown",
						"web_url": entry.get("webpage_url") or entry.get("url"),
						"uploader": entry.get("uploader") or entry.get("channel") or "Unknown",
						"duration": entry.get("duration"),
						"thumbnail": entry.get("thumbnail"),
						"stream_url": entry.get("url"),
						"requested_by": interaction.user.mention,
						"tier": tier,
					})

			def _after_playback(error):
				if error:
					print(f"[YTDL] Playback error: {error}")
				asyncio.run_coroutine_threadsafe(
					self._ytdl_auto_advance(interaction.guild.id),
					self.bot.loop
				)

			volume = guild_volume.get(interaction.guild.id, 100) / 100
			source = discord.PCMVolumeTransformer(
				discord.FFmpegPCMAudio(stream_url, **_get_ffmpeg_options()),
				volume=volume,
			)
			voice_client.play(source, after=_after_playback)
			guild_last_activity[interaction.guild.id] = asyncio.get_event_loop().time()

			embed = self._build_now_playing_embed_from_ytdl(first, interaction.user.mention, tier)
			view = MusicControls(self, interaction.guild.id)
			total = len(entries)
			queued = len(remaining)
			status = f"📋 Playlist loaded! Playing first track, **{queued}** more queued." if queued else None
			message = await interaction.followup.send(content=status, embed=embed, view=view, wait=True)
			guild_now_message[interaction.guild.id] = {
				"channel_id": message.channel.id, "message_id": message.id,
				"title": embed.description or "Unknown",
			}
			return

		# ── Single track ─────────────────────────────────────────────────
		queries = _build_query_candidates(song)

		try:
			info = await _ytdl_extract(queries, tier)
		except Exception as e:
			print(f"[YTDL] Extraction error: {e}")
			await interaction.edit_original_response(content="❌ Couldn't find that song.")
			return

		stream_url = info.get("url")
		if not stream_url:
			await interaction.edit_original_response(content="❌ Found the song but couldn't get a stream URL.")
			return

		# Store track info for controls
		track_info = {
			"title": info.get("title") or "Unknown",
			"web_url": info.get("webpage_url") or info.get("url"),
			"uploader": info.get("uploader") or info.get("channel") or "Unknown",
			"duration": info.get("duration"),
			"thumbnail": info.get("thumbnail"),
			"stream_url": stream_url,
			"requested_by": interaction.user.mention,
			"tier": tier,
		}

		def _after_playback(error):
			if error:
				print(f"[YTDL] Playback error: {error}")
			asyncio.run_coroutine_threadsafe(
				self._ytdl_auto_advance(interaction.guild.id),
				self.bot.loop
			)

		volume = guild_volume.get(interaction.guild.id, 100) / 100
		source = discord.PCMVolumeTransformer(
			discord.FFmpegPCMAudio(stream_url, **_get_ffmpeg_options()),
			volume=volume,
		)
		voice_client.play(source, after=_after_playback)
		guild_last_activity[interaction.guild.id] = asyncio.get_event_loop().time()

		embed = self._build_now_playing_embed_from_ytdl(info, interaction.user.mention, tier)
		view = MusicControls(self, interaction.guild.id)
		message = await interaction.followup.send(embed=embed, view=view, wait=True)
		guild_now_message[interaction.guild.id] = {
			"channel_id": message.channel.id, "message_id": message.id,
			"title": embed.description or "Unknown",
		}

	async def _ytdl_auto_advance(self, guild_id: int):
		"""yt-dlp fallback auto-advance — plays next track from yt-dlp queue."""
		await self._mark_now_playing_as_ended(guild_id)
		guild_now_message.pop(guild_id, None)

		queue = guild_ytdl_queue.get(guild_id, [])
		if not queue:
			asyncio.create_task(self._start_idle_timer(guild_id))
			return

		next_track = queue.pop(0)
		stream_url = next_track.get("stream_url")
		if not stream_url:
			asyncio.create_task(self._ytdl_auto_advance(guild_id))
			return

		guild = self.bot.get_guild(guild_id)
		if guild is None:
			return
		voice_client = guild.voice_client
		if not voice_client or not voice_client.is_connected():
			guild_ytdl_queue.pop(guild_id, None)
			return

		def _after_playback(error):
			if error:
				print(f"[YTDL] Playback error: {error}")
			asyncio.run_coroutine_threadsafe(
				self._ytdl_auto_advance(guild_id),
				self.bot.loop
			)

		try:
			volume = guild_volume.get(guild_id, 100) / 100
			source = discord.PCMVolumeTransformer(
				discord.FFmpegPCMAudio(stream_url, **_get_ffmpeg_options()),
				volume=volume,
			)
			voice_client.play(source, after=_after_playback)
			guild_last_activity[guild_id] = asyncio.get_event_loop().time()

			info = {
				"title": next_track.get("title"),
				"webpage_url": next_track.get("web_url"),
				"uploader": next_track.get("uploader"),
				"duration": next_track.get("duration"),
				"thumbnail": next_track.get("thumbnail"),
			}
			embed = self._build_now_playing_embed_from_ytdl(
				info, next_track.get("requested_by", "Unknown"), next_track.get("tier", "free")
			)
			view = MusicControls(self, guild_id)
			await self._post_now_playing(guild_id, embed, view)
		except Exception as e:
			print(f"[YTDL] Auto-advance error: {e}")
			asyncio.create_task(self._ytdl_auto_advance(guild_id))

	# ── Mode commands ─────────────────────────────────────────────────────────

	@app_commands.command(name="funmode", description="😎 Activate Fun Mode - jokes, memes & chill vibes")
	async def funmode_slash(self, interaction: discord.Interaction):
		is_dm = isinstance(interaction.channel, discord.DMChannel)
		chan_id = f"dm_{interaction.user.id}" if is_dm else str(interaction.channel.id)
		channel_modes[chan_id] = "funny"
		memory.save_channel_mode(chan_id, "funny")
		channel_chess[chan_id] = False
		await interaction.response.send_message(
			"😎 **Fun mode activated!**\n"
			"🎮 **How to chat:**\n"
			"📍 In servers: `@Codunot AI your message`\n"
			"💬 In DMs: Just talk normally!\n\n"
			"I'll keep it fun, use emojis, and match your vibe. Try asking me anything! 💬✨",
			ephemeral=False
		)

	@app_commands.command(name="seriousmode", description="🤓 Activate Serious Mode - clean, fact-based help")
	async def seriousmode_slash(self, interaction: discord.Interaction):
		is_dm = isinstance(interaction.channel, discord.DMChannel)
		chan_id = f"dm_{interaction.user.id}" if is_dm else str(interaction.channel.id)
		channel_modes[chan_id] = "serious"
		memory.save_channel_mode(chan_id, "serious")
		channel_chess[chan_id] = False
		await interaction.response.send_message(
			"🤓 **Serious mode ON.**\n"
			"📍 In servers: `@Codunot AI your question`\n"
			"💬 In DMs: Just type your question directly.\n\n"
			"I'll give clear, structured answers — great for homework, research, or coding help.",
			ephemeral=False
		)

	@app_commands.command(name="roastmode", description="🔥 Activate Roast Mode - playful burns")
	async def roastmode_slash(self, interaction: discord.Interaction):
		is_dm = isinstance(interaction.channel, discord.DMChannel)
		chan_id = f"dm_{interaction.user.id}" if is_dm else str(interaction.channel.id)
		channel_modes[chan_id] = "roast"
		memory.save_channel_mode(chan_id, "roast")
		channel_chess[chan_id] = False
		await interaction.response.send_message(
			"🔥 **ROAST MODE ACTIVATED!**\n"
			"📍 In servers: `@Codunot AI roast me` or `@Codunot AI roast @someone`\n"
			"💬 In DMs: Just type who or what to roast!\n\n"
			"Brace yourself — I don't hold back (much) 😈",
			ephemeral=False
		)

	@app_commands.command(name="teachmerizz", description="💬 Activate Rizz Coach mode")
	@app_commands.describe(mode="Choose online (texting/DMs) or irl (real life)")
	@app_commands.choices(mode=[
		app_commands.Choice(name="online", value="online"),
		app_commands.Choice(name="irl", value="irl"),
	])
	async def teachmerizz_slash(self, interaction: discord.Interaction, mode: app_commands.Choice[str]):
		is_dm = isinstance(interaction.channel, discord.DMChannel)
		chan_id = f"dm_{interaction.user.id}" if is_dm else str(interaction.channel.id)
		if mode.value == "online":
			channel_modes[chan_id] = "rizz_online"
			memory.save_channel_mode(chan_id, "rizz_online")
			channel_chess[chan_id] = False
			await interaction.response.send_message(
				"💬 **Rizz Coach (Online) activated!**\n"
				"📍 In servers: `@Codunot AI` + your situation or screenshot\n"
				"💬 In DMs: Just type or paste your convo directly!\n\n"
				"Send a screenshot, paste a convo, or describe what's happening — I'll coach you through it 👇"
			)
		elif mode.value == "irl":
			channel_modes[chan_id] = "rizz_irl"
			memory.save_channel_mode(chan_id, "rizz_irl")
			channel_chess[chan_id] = False
			await interaction.response.send_message(
				"🗣️ **Rizz Coach (IRL) activated!**\n"
				"📍 In servers: `@Codunot AI` + describe your situation\n"
				"💬 In DMs: Just type what's going on!\n\n"
				"Describe the situation, ask for tips, or tell me what happened — I got you 👇"
			)

	@app_commands.command(name="chessmode", description="♟️ Activate Chess Mode - play chess with Codunot")
	async def chessmode_slash(self, interaction: discord.Interaction):
		is_dm = isinstance(interaction.channel, discord.DMChannel)
		chan_id = f"dm_{interaction.user.id}" if is_dm else str(interaction.channel.id)
		channel_chess[chan_id] = True
		channel_modes[chan_id] = "funny"
		chess_engine.new_board(chan_id)
		await interaction.response.send_message(
			"♟️ **Chess mode ACTIVATED!** You're playing white, I'm black.\n"
			"📍 **In servers:** Ping me with your move: `@Codunot AI e4`\n"
			"💬 **In DMs:** Just type your move directly: `e4`\n\n"
			"🎯 **Try these opening moves:**\n"
			"• `e4` — King's pawn\n"
			"• `d4` — Queen's pawn\n"
			"• `Nf3` — Knight to f3\n\n"
			"💡 Move formats: `e4`, `Nf3`, `Bxc4`, `O-O` (castle kingside), `O-O-O` (queenside)\n"
			"You can also ask for hints, resign, or chat about the position!\n"
			"Your move! ♟️",
			ephemeral=False
		)

	# ── AI generation commands ────────────────────────────────────────────────

	@app_commands.command(name="generate_image", description="🖼️ Generate an AI image from a text prompt")
	@app_commands.describe(prompt="Describe the image you want to generate")
	async def generate_image_slash(self, interaction: discord.Interaction, prompt: str):
		usage_key = await self._resolve_paid_usage_key(interaction)
		await interaction.response.defer()
		await interaction.edit_original_response(content="🗳️ **Checking your vote status...**")
		if not await require_vote_deferred(interaction):
			return
		await interaction.edit_original_response(content="✅ **Vote verified! You're good to go.**")
		if not check_limit(interaction, "attachments", usage_key=usage_key):
			await interaction.followup.send("🚫 You've hit your **daily image generation limit**.")
			return
		if not check_total_limit(interaction, "attachments", usage_key=usage_key):
			await interaction.followup.send("🚫 You've hit your **2 months' image generation limit**.")
			return
		await interaction.followup.send("🎨 **Cooking up your image... hang tight ✨**")
		try:
			boosted_prompt = await boost_image_prompt(prompt)
			image_bytes, balance = await generate_image(boosted_prompt, aspect_ratio="1:1")
			output_text = f"{interaction.user.mention} 🖼️ Generated: `{prompt[:150]}{'...' if len(prompt) > 150 else ''}`"
			await self._deliver_paid_attachment(interaction, output_text, "generated_image.png", image_bytes)
			consume(interaction, "attachments", usage_key=usage_key)
			consume_total(interaction, "attachments", usage_key=usage_key, money_left=balance)
			save_usage()
		except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError) as e:
			print(f"[SLASH IMAGE ERROR] {e}")
			traceback.print_exc()
			await interaction.followup.send(f"{interaction.user.mention} ⏱️ The image API timed out after multiple attempts. The server may be busy — please try again in a moment.")
		except ImageAPIError as e:
			print(f"[SLASH IMAGE ERROR] {e}")
			traceback.print_exc()
			await interaction.followup.send(f"{interaction.user.mention} ⏱️ The image API returned a server error after multiple attempts. The server may be busy — please try again in a moment.")
		except Exception as e:
			print(f"[SLASH IMAGE ERROR] {e}")
			traceback.print_exc()
			await interaction.followup.send(f"{interaction.user.mention} 🤔 Couldn't generate image right now.")

	@app_commands.command(name="generate_video", description="🎬 Generate an AI video from a text prompt")
	@app_commands.describe(prompt="Describe the video you want to generate")
	async def generate_video_slash(self, interaction: discord.Interaction, prompt: str):
		usage_key = await self._resolve_paid_usage_key(interaction)
		await interaction.response.defer()
		await interaction.edit_original_response(content="🗳️ **Checking your vote status...**")
		if not await require_vote_deferred(interaction):
			return
		await interaction.edit_original_response(content="✅ **Vote verified! You're good to go.**")
		if not check_limit(interaction, "attachments", usage_key=usage_key):
			await interaction.followup.send("🚫 You've hit your **daily video generation limit**.")
			return
		if not check_total_limit(interaction, "attachments", usage_key=usage_key):
			await interaction.followup.send("🚫 You've hit your **2 months' video generation limit**.")
			return
		await interaction.followup.send("🎬 **Rendering your video... this may take up to ~1 min ⏳**")
		try:
			boosted_prompt = await boost_video_prompt(prompt)
			video_bytes = await text_to_video_512(prompt=boosted_prompt)
			output_text = f"{interaction.user.mention} 🎬 Generated: `{prompt[:150]}{'...' if len(prompt) > 150 else ''}`"
			await self._deliver_paid_attachment(interaction, output_text, "generated_video.mp4", video_bytes)
			consume(interaction, "attachments", usage_key=usage_key)
			consume_total(interaction, "attachments", usage_key=usage_key)
			save_usage()
		except Exception as e:
			print(f"[SLASH VIDEO ERROR] {e}")
			traceback.print_exc()
			await interaction.followup.send(f"{interaction.user.mention} 🤔 Couldn't generate video right now.")

	@app_commands.command(name="generate_tts", description="🔊 Generate text-to-speech audio — pick a voice & language")
	@app_commands.describe(
		text="The text you want to convert to speech (minimum 20 characters)",
		language="Choose the language for the speech",
		voice="Choose a voice for the speech (pick language first)",
	)
	@app_commands.choices(
		language=[
			app_commands.Choice(name=display, value=code)
			for code, (display, _) in TTS_LANG_VOICES.items()
		],
	)
	async def generate_tts_slash(
		self,
		interaction: discord.Interaction,
		text: str,
		language: app_commands.Choice[str],
		voice: str,
	):
		if len(text) < 20:
			await interaction.response.send_message(
				"🚫 Your text must be at least **20 characters** long. Please provide a longer message.",
				ephemeral=True,
			)
			return
		lang_code = language.value
		lang_display, voices = TTS_LANG_VOICES[lang_code]
		valid_codes = set(voices.values())
		if voice not in valid_codes:
			await interaction.response.send_message(
				f"🚫 **{voice}** is not a valid voice for **{lang_display}**. "
				f"Available voices: {', '.join(voices.keys())}",
				ephemeral=True,
			)
			return
		voice_display = TTS_VOICE_CODE_TO_NAME.get(voice, voice)
		usage_key = await self._resolve_paid_usage_key(interaction)
		await interaction.response.defer()
		await interaction.edit_original_response(content="🗳️ **Checking your vote status...**")
		if not await require_vote_deferred(interaction):
			return
		await interaction.edit_original_response(content="✅ **Vote verified! You're good to go.**")
		if not check_limit(interaction, "attachments", usage_key=usage_key):
			await interaction.followup.send("🚫 You've hit your **daily TTS generation limit**.")
			return
		if not check_total_limit(interaction, "attachments", usage_key=usage_key):
			await interaction.followup.send("🚫 You've hit your **2 months' TTS generation limit**.")
			return
		await interaction.followup.send(
			f"🔊 **Generating your audio** (voice: **{voice_display}**, language: **{lang_display}**)... almost there 🎙️"
		)
		try:
			audio_url = await text_to_speech(
				text=text,
				model="Kokoro",
				voice=voice,
				lang=lang_code,
				speed=1,
				format="mp3",
				sample_rate=24000,
			)
			async with aiohttp.ClientSession() as session:
				async with session.get(audio_url) as resp:
					if resp.status != 200:
						raise Exception("Failed to download TTS audio")
					audio_bytes = await resp.read()
			output_text = f"{interaction.user.mention} 🔊 TTS ({voice_display}/{lang_display}): `{text[:200]}{'...' if len(text) > 200 else ''}`"
			await self._deliver_paid_attachment(interaction, output_text, "speech.mp3", audio_bytes)
			consume(interaction, "attachments", usage_key=usage_key)
			consume_total(interaction, "attachments", usage_key=usage_key)
			save_usage()
		except Exception as e:
			print(f"[SLASH TTS ERROR] {e}")
			await interaction.followup.send(f"{interaction.user.mention} 🤔 Couldn't generate speech right now.")

	@generate_tts_slash.autocomplete("voice")
	async def _tts_voice_autocomplete(
		self,
		interaction: discord.Interaction,
		current: str,
	) -> list[app_commands.Choice[str]]:
		lang_choice = getattr(interaction.namespace, "language", None)
		if lang_choice and hasattr(lang_choice, "value"):
			lang_code = lang_choice.value
		elif isinstance(lang_choice, str):
			lang_code = lang_choice
		else:
			lang_code = None
		if lang_code and lang_code in TTS_LANG_VOICES:
			_, voices = TTS_LANG_VOICES[lang_code]
		else:
			voices = TTS_ALL_VOICES
		return [
			app_commands.Choice(name=name, value=code)
			for name, code in voices.items()
			if current.lower() in name.lower()
		][:25]

	# ── Utility ───────────────────────────────────────────────────────────────

	async def _send_long_interaction_message(self, interaction: discord.Interaction, text: str):
		max_len = 2000
		remaining = (text or "").strip()
		while remaining:
			if len(remaining) <= max_len:
				await interaction.followup.send(remaining, ephemeral=False)
				break
			split_at = max(remaining.rfind("\n", 0, max_len), remaining.rfind(" ", 0, max_len))
			if split_at <= 0:
				split_at = max_len
			else:
				split_at += 1
			await interaction.followup.send(remaining[:split_at], ephemeral=False)
			remaining = remaining[split_at:]

	def _safe_json_parse(self, payload: str) -> dict | None:
		if not payload:
			return None
		cleaned = payload.strip()
		if cleaned.startswith("```"):
			cleaned = cleaned.strip("`")
			if cleaned.lower().startswith("json"):
				cleaned = cleaned[4:]
			cleaned = cleaned.strip()
		try:
			return json.loads(cleaned)
		except Exception:
			start = cleaned.find("{")
			end = cleaned.rfind("}")
			if start != -1 and end != -1 and start < end:
				try:
					return json.loads(cleaned[start:end + 1])
				except Exception:
					return None
		return None

	def _compact_message_for_prompt(self, text: str, max_len: int = 180) -> str:
		clean = " ".join((text or "").split())
		if not clean:
			return ""
		tokens = clean.split(" ")
		compacted: list[str] = []
		last = None
		repeat_count = 0
		for token in tokens:
			if token == last:
				repeat_count += 1
				if repeat_count <= 3:
					compacted.append(token)
				continue
			last = token
			repeat_count = 1
			compacted.append(token)
		result = " ".join(compacted)
		if len(result) > max_len:
			return result[:max_len].rstrip() + "..."
		return result

	def _clean_reasoning_items(self, items: list[str]) -> list[str]:
		seen = set()
		cleaned: list[str] = []
		for item in items:
			line = self._compact_message_for_prompt(str(item), max_len=170)
			if not line:
				continue
			key = line.lower()
			if key in seen:
				continue
			seen.add(key)
			cleaned.append(line)
			if len(cleaned) >= 4:
				break
		return cleaned

	async def _collect_recent_user_messages(self, channel, user_id, limit=60, max_scan=4000):
		messages: list[str] = []
		scanned = 0
		fetch_failed = False
		try:
			async for message in channel.history(limit=max_scan):
				scanned += 1
				if message.author.bot:
					continue
				if message.author.id != user_id:
					continue
				content = self._compact_message_for_prompt((message.content or "").strip(), max_len=180)
				if not content or len(content) < 3:
					continue
				messages.append(content)
				if len(messages) >= limit:
					break
		except Exception as e:
			fetch_failed = True
			print(f"[GUESSAGE FETCH ERROR] {e}")
		messages.reverse()
		return messages, scanned, fetch_failed

	async def _collect_recent_user_messages_across_guild(self, guild, user_id, exclude_channel_ids=None, limit=60, max_scan_per_channel=1200):
		messages: list[str] = []
		scanned_total = 0
		fetch_failed = False
		channels_used = 0
		exclude_ids = exclude_channel_ids or set()
		for channel in guild.text_channels:
			if channel.id in exclude_ids:
				continue
			channel_messages, scanned_count, failed = await self._collect_recent_user_messages(
				channel, user_id, limit=max(1, limit - len(messages)), max_scan=max_scan_per_channel,
			)
			scanned_total += scanned_count
			fetch_failed = fetch_failed or failed
			if channel_messages:
				channels_used += 1
				messages.extend(channel_messages)
			if len(messages) >= limit:
				break
		if len(messages) > limit:
			messages = messages[-limit:]
		return messages, scanned_total, fetch_failed, channels_used

	@app_commands.command(name="guessage", description="🔍 Guess a user's age range from recent messages (AI estimate)")
	@app_commands.describe(target_user="The user whose age you want estimated")
	async def guessage_slash(self, interaction: discord.Interaction, target_user: discord.User):
		if not isinstance(interaction.channel, (discord.TextChannel, discord.Thread, discord.DMChannel)):
			await interaction.response.send_message("❌ Can't use this here.", ephemeral=False)
			return
		await interaction.response.defer(ephemeral=False)
		await interaction.edit_original_response(content="🗳️ **Checking your vote status...**")
		if not await require_vote_deferred(interaction):
			return
		await interaction.edit_original_response(content="🔎 **Collecting recent messages...**")
		recent_messages, scanned_count, fetch_failed = await self._collect_recent_user_messages(
			interaction.channel, target_user.id, limit=60,
		)
		source_channels_used = 1 if recent_messages else 0
		if len(recent_messages) == 0 and interaction.guild is not None:
			await interaction.edit_original_response(content="🔎 **Searching other channels...**")
			exclude_channel_ids: set[int] = set()
			if interaction.channel_id is not None:
				exclude_channel_ids.add(interaction.channel_id)
			alt_messages, alt_scanned, alt_fetch_failed, alt_channels_used = await self._collect_recent_user_messages_across_guild(
				interaction.guild, target_user.id, exclude_channel_ids=exclude_channel_ids, limit=60,
			)
			scanned_count += alt_scanned
			fetch_failed = fetch_failed or alt_fetch_failed
			if alt_messages:
				recent_messages = alt_messages
				source_channels_used = alt_channels_used
		sample_count = len(recent_messages)
		if sample_count < 10:
			error_hint = " Missing **Read Message History** permission?" if fetch_failed else ""
			await interaction.followup.send(
				f"⚠️ Only **{sample_count}** messages found after scanning **{scanned_count}**. Need at least 10.{error_hint}"
			)
			return
		await interaction.edit_original_response(content="🧠 **Analyzing...**")
		joined_messages = "\n".join(f"- {line}" for line in recent_messages)
		prompt = (
			"You estimate an approximate age range from message-writing style only. "
			"Never claim certainty and keep it strictly as a moderation insight.\n\n"
			"Return ONLY strict JSON:\n"
			"{\n  \"age_range\": \"13-18\",\n  \"exact_guess\": 16,\n  \"confidence\": \"low|medium|high\",\n"
			"  \"reasoning\": [\"reason 1\", \"reason 2\", \"reason 3\"]\n}\n\n"
			f"Sample count: {sample_count}\n\nUser messages:\n{joined_messages}"
		)
		result_text = await call_google_ai_studio(prompt=prompt, temperature=0.2)
		payload = self._safe_json_parse(result_text or "")
		if not payload:
			await interaction.followup.send("🤔 Couldn't parse AI output. Try again.")
			return
		age_range = str(payload.get("age_range") or "Unknown")
		exact_guess = payload.get("exact_guess")
		confidence = str(payload.get("confidence") or "unknown").capitalize()
		reasoning = payload.get("reasoning") or []
		if not isinstance(reasoning, list):
			reasoning = [str(reasoning)]
		reasoning = self._clean_reasoning_items([str(i) for i in reasoning])
		reasoning_lines = "\n".join(f"• {item}" for item in reasoning) or "• Not enough signal."
		confidence_badge = {"high": "🟢 High", "medium": "🟡 Medium", "low": "🔴 Low"}.get(confidence.lower(), "⚪ Unknown")
		guess_display = str(exact_guess) if exact_guess is not None else "Unknown"
		embed = discord.Embed(
			title="🧭 Message Style Insight Panel",
			description=f"Target: {target_user.mention}\n**Range:** `{age_range}` • **Best Guess:** `{guess_display}` • **Confidence:** {confidence_badge}",
			color=0x8A63D2,
		)
		embed.add_field(name="📊 Stats", value=f"• Messages: **{sample_count}**\n• Scanned: **{scanned_count}**\n• Channels: **{source_channels_used}**", inline=False)
		embed.add_field(name="🧠 Why", value=reasoning_lines, inline=False)
		embed.add_field(name="⚠️ Important", value="Style-based estimate only. Never use for verification.", inline=False)
		embed.set_footer(text=f"Requested by {interaction.user.display_name} • /guessage")
		if target_user.display_avatar:
			embed.set_thumbnail(url=target_user.display_avatar.url)
		await interaction.edit_original_response(content=None, embed=embed)

	def _normalize_transcribe_url(self, url: str) -> str | None:
		from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
		try:
			parsed = urlparse((url or "").strip())
		except Exception:
			return None
		if parsed.scheme not in {"http", "https"}:
			return None
		host = (parsed.hostname or "").lower()
		if not host:
			return None
		host = TRANSCRIBE_HOST_NORMALIZATION.get(host, host)
		host_for_check = host[4:] if host.startswith("www.") else host
		allowed = host in ALLOWED_TRANSCRIBE_HOSTS or any(
			host_for_check == suffix or host_for_check.endswith(f".{suffix}")
			for suffix in ALLOWED_TRANSCRIBE_HOST_SUFFIXES
		)
		if not allowed:
			return None
		query_items = parse_qsl(parsed.query, keep_blank_values=True)
		filtered_query = urlencode([
			(k, v) for (k, v) in query_items
			if not k.lower().startswith("utm_") and k.lower() not in {"si", "feature", "pp"}
		])
		netloc = host
		if parsed.port:
			netloc = f"{host}:{parsed.port}"
		return urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, filtered_query, ""))

	def _transcribe_register_base(self) -> str:
		from urllib.parse import urlparse
		webhook_url = os.getenv("DEAPI_WEBHOOK_URL", "").strip()
		if webhook_url:
			parsed = urlparse(webhook_url)
			if parsed.scheme and parsed.netloc:
				return f"{parsed.scheme}://{parsed.netloc}"
		deapi_base = os.getenv("DEAPI_BASE_URL", "").strip().rstrip("/")
		if deapi_base:
			parsed = urlparse(deapi_base)
			if parsed.scheme and parsed.netloc:
				return f"{parsed.scheme}://{parsed.netloc}"
		return ""

	async def _send_transcription_fallback_result(self, *, request_id, channel_id, user_id, deliver_in_dm):
		try:
			transcript_text = await wait_for_transcription_text(request_id=request_id)
		except Exception as e:
			print(f"[TRANSCRIBE FALLBACK] {e}")
			return
		message = f"✅ **Transcription complete:**\n{transcript_text[:1900]}"
		try:
			if deliver_in_dm:
				user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
				await user.send(message)
			else:
				channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
				await channel.send(message)
		except Exception as e:
			print(f"[TRANSCRIBE FALLBACK] Discord send failed: {e}")

	@app_commands.command(name="transcribe", description="📝 Transcribe a supported video URL (max 30 mins)")
	@app_commands.describe(video_url="Supported: YouTube, Twitch VOD, X, Kick")
	async def transcribe_slash(self, interaction: discord.Interaction, video_url: str):
		usage_key = await self._resolve_paid_usage_key(interaction)
		normalized_video_url = self._normalize_transcribe_url(video_url)
		if not normalized_video_url:
			await interaction.response.send_message("❌ Only YouTube, Twitch VODs, X, and Kick URLs are allowed.", ephemeral=False)
			return
		await interaction.response.defer(ephemeral=False)
		await interaction.edit_original_response(content="🗳️ **Checking your vote status...**")
		if not await require_vote_deferred(interaction):
			return
		if not check_limit(interaction, "attachments", usage_key=usage_key):
			await interaction.edit_original_response(content="🚫 Daily transcription limit hit.")
			return
		if not check_total_limit(interaction, "attachments", usage_key=usage_key):
			await interaction.edit_original_response(content="🚫 2-month transcription limit hit.")
			return
		await interaction.edit_original_response(content="✅ **Submitting transcription...**")
		deliver_in_dm = self._should_deliver_paid_output_in_dm(interaction)
		try:
			request_id = await transcribe_video(video_url=normalized_video_url, max_minutes=30)
			register_base = self._transcribe_register_base()
			register_channel_id = interaction.channel.id
			if deliver_in_dm:
				if usage_key and usage_key.isdigit():
					register_channel_id = int(usage_key)
				else:
					try:
						dm_channel = interaction.user.dm_channel or await interaction.user.create_dm()
						if dm_channel is not None:
							register_channel_id = dm_channel.id
					except Exception as e:
						print(f"[TRANSCRIBE REGISTER] {e}")
			if register_base:
				try:
					async with aiohttp.ClientSession() as session:
						async with session.post(
							f"{register_base}/register-transcription",
							json={"request_id": request_id, "channel_id": register_channel_id, "user_id": interaction.user.id, "deliver_in_dm": deliver_in_dm},
							timeout=aiohttp.ClientTimeout(total=15),
						) as register_resp:
							if register_resp.status >= 300:
								print(f"[TRANSCRIBE REGISTER] failed ({register_resp.status})")
				except Exception as e:
					print(f"[TRANSCRIBE REGISTER] {e}")
			consume(interaction, "attachments", usage_key=usage_key)
			consume_total(interaction, "attachments", usage_key=usage_key)
			save_usage()
			asyncio.create_task(self._send_transcription_fallback_result(
				request_id=request_id, channel_id=register_channel_id,
				user_id=interaction.user.id, deliver_in_dm=deliver_in_dm,
			))
		except VideoToTextError as e:
			await interaction.edit_original_response(content=f"❌ {e}")
			return
		except Exception as e:
			print(f"[SLASH TRANSCRIBE ERROR] {e}")
			await interaction.edit_original_response(content="🤔 Couldn't transcribe this video right now.")
			return
		if deliver_in_dm:
			await interaction.edit_original_response(content="📝 Transcription submitted! Result coming to your DMs.")
		else:
			await interaction.edit_original_response(content="📝 Transcription submitted! I'll post the result here.")

	# ── Action GIFs ───────────────────────────────────────────────────────────

	async def _send_action_gif(self, interaction: discord.Interaction, action: str, target_user: discord.User):
		if target_user.id == interaction.user.id:
			await interaction.response.send_message(f"😅 You can't /{action} yourself!", ephemeral=False)
			return
		await interaction.response.defer()
		loading_msg = await interaction.followup.send("🎉 **Loading your GIF...**", wait=True)
		try:
			source_url = random.choice(ACTION_GIF_SOURCES[action])
			text = random.choice(ACTION_MESSAGES[action]).format(user=interaction.user.mention, target=target_user.mention)
			embed = discord.Embed(description=text, color=0xFFA500)
			embed.set_image(url=source_url)
			await asyncio.sleep(3)
			await loading_msg.edit(content=None, embed=embed)
		except Exception as e:
			print(f"[SLASH {action.upper()} ERROR] {e}")
			await loading_msg.edit(content=f"🤔 Couldn't load a {action} GIF right now.")

	@app_commands.command(name="hug", description="🤗 Hug any user with a random GIF")
	@app_commands.describe(target_user="The user you want to hug")
	async def hug_slash(self, interaction: discord.Interaction, target_user: discord.User):
		await self._send_action_gif(interaction, "hug", target_user)

	@app_commands.command(name="kiss", description="💋 Kiss any user with a random GIF")
	@app_commands.describe(target_user="The user you want to kiss")
	async def kiss_slash(self, interaction: discord.Interaction, target_user: discord.User):
		await self._send_action_gif(interaction, "kiss", target_user)

	@app_commands.command(name="kick", description="🥋 Kick any user with a random anime GIF")
	@app_commands.describe(target_user="The user you want to kick")
	async def kick_slash(self, interaction: discord.Interaction, target_user: discord.User):
		await self._send_action_gif(interaction, "kick", target_user)

	@app_commands.command(name="slap", description="🖐️ Slap any user with a random anime GIF")
	@app_commands.describe(target_user="The user you want to slap")
	async def slap_slash(self, interaction: discord.Interaction, target_user: discord.User):
		await self._send_action_gif(interaction, "slap", target_user)

	@app_commands.command(name="wish_goodmorning", description="🌅 Wish someone a good morning with a GIF")
	@app_commands.describe(target_user="The user you want to wish good morning")
	async def wish_goodmorning_slash(self, interaction: discord.Interaction, target_user: discord.User):
		await self._send_action_gif(interaction, "wish_goodmorning", target_user)

	@app_commands.command(name="bet", description="🪙 Bet on heads or tails with a coin flip")
	@app_commands.describe(side="Choose heads or tails")
	@app_commands.choices(side=[
		app_commands.Choice(name="heads", value="heads"),
		app_commands.Choice(name="tails", value="tails"),
	])
	async def bet_slash(self, interaction: discord.Interaction, side: app_commands.Choice[str]):
		await interaction.response.defer()
		await interaction.followup.send("🪙 **Flipping the coin...**")
		result = random.choice(["heads", "tails"])
		did_win = side.value == result
		if did_win:
			msg = f"🪙 The coin landed on **{result}**! {interaction.user.mention} guessed correctly and wins! 🎉"
		else:
			msg = f"🪙 The coin landed on **{result}**! {interaction.user.mention} guessed **{side.value}** and lost this round."
		await interaction.followup.send(msg)

	@app_commands.command(name="meme", description="😂 Send a random meme")
	async def meme_slash(self, interaction: discord.Interaction):
		await interaction.response.defer()
		await interaction.followup.send("😂 **Loading your meme...**")
		meme_url = random.choice(MEME_SOURCES)
		embed = discord.Embed(title="😂 Random Meme", color=0x00BFFF)
		embed.set_image(url=meme_url)
		await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
	cog = Codunot(bot)
	await bot.add_cog(cog)
	print(f"[COG] Loaded Codunot cog with {len(cog.get_app_commands())} app commands")
