import discord
from discord import app_commands
from discord.ext import commands
import os
import time
import io
import json
import aiohttp
import asyncio
import random
import traceback
from typing import Optional

from memory import MemoryManager
from deAPI_client_image import generate_image
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
MAX_TTS_LENGTH = 150
boost_image_prompt = None
boost_video_prompt = None
save_vote_unlocks = None
set_server_mode = None
set_channels_mode = None
get_guild_config = None
pending_transcriptions: dict[str, int] = {}

ALLOWED_TRANSCRIBE_HOSTS = (
	"youtube.com",
	"www.youtube.com",
	"m.youtube.com",
	"youtu.be",
	"twitch.tv",
	"www.twitch.tv",
	"x.com",
	"www.x.com",
	"twitter.com",
	"www.twitter.com",
	"kick.com",
	"www.kick.com",
)

ALLOWED_TRANSCRIBE_HOST_SUFFIXES = (
	"youtube.com",
	"twitch.tv",
	"x.com",
	"twitter.com",
	"kick.com",
)

TRANSCRIBE_HOST_NORMALIZATION = {
	"m.youtube.com": "www.youtube.com",
	"music.youtube.com": "www.youtube.com",
	"m.twitch.tv": "www.twitch.tv",
	"m.x.com": "x.com",
	"mobile.x.com": "x.com",
	"m.twitter.com": "twitter.com",
	"mobile.twitter.com": "twitter.com",
	"m.kick.com": "www.kick.com",
}

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
		"https://i.giphy.com/G3va31oEEnIkM.webp",
		"https://i.giphy.com/bGm9FuBCGg4SY.webp",
		"https://c.tenor.com/dd4mZNppytYAAAAd/tenor.gif",
		"https://c.tenor.com/Y2AdPDiQoK8AAAAC/tenor.gif",
		"https://i.giphy.com/PBbFIL4bF8uS4.webp",
		"https://i.giphy.com/rFdqmnaIxx6qk.webp",
		"https://i.giphy.com/MqbZjCY1ghSAo.webp",
		"https://i.giphy.com/6Q9P2ry85GGOKbxKiC.webp",
	],
	"kick": [
		"https://i.giphy.com/DfI1LsaCkWD20xRc4r.webp",
		"https://i.giphy.com/3o7TKwVQMoQh2At9qU.webp",
		"https://media.tenor.com/TDQXdEBNNjUAAAAi/milk-and-mocha.gif",
		"https://media.tenor.com/ztHpFwsax84AAAAi/hau-zozo-smile.gif",
		"https://i.giphy.com/l3V0j3ytFyGHqiV7W.webp",
		"https://i.giphy.com/k3j9oaRV4FAT3ksIG1.webp",
		"https://i.giphy.com/xr9FpQBn2sPUOVtnNZ.webp",
		"https://i.giphy.com/RN96CaqhRoRHk4DlLV.webp",
		"https://i.giphy.com/qiiimDJtLj4XK.webp",
	],
	"slap": [
		"https://media.tenor.com/TVPYqh_E1JYAAAAj/peach-goma-peach-and-goma.gif",
		"https://media.tenor.com/tMVS_yML7t0AAAAj/slap-slaps.gif",
		"https://c.tenor.com/OTr4wv64hwwAAAAd/tenor.gif",
		"https://c.tenor.com/4Ut_QPbeCZIAAAAd/tenor.gif",
		"https://c.tenor.com/LHlITawhrEcAAAAd/tenor.gif",
		"https://i.giphy.com/3oriNXBCGHrzCYIbZK.webp",
		"https://i.giphy.com/qyjexFwQwJp9yUvMxq.webp",
		"https://media1.giphy.com/media/v1.Y2lkPWVjZjA1ZTQ3MDN6cnRhbzg1OGZodjQybXBmbXJkNDNrdTU3cDNmZzN6Nm42NmxlZyZlcD12MV9naWZzX3NlYXJjaCZjdD1n/E2MeuITk1M4pi/200.webp",
		"https://i.giphy.com/RYOYNPbKoRORepL80E.webp",
	],
	"wish_goodmorning": [
		"https://media.tenor.com/xwlZJGC0EqwAAAAj/pengu-pudgy.gif",
		"https://media.tenor.com/4pnZsJP06XMAAAAj/have-a-great-day-good-day.gif",
		"https://media.tenor.com/xlwtvJtC6FAAAAAM/jjk-jujutsu-kaisen.gif",
		"https://c.tenor.com/6VbeqshMfkEAAAAd/tenor.gif",
		"https://i.giphy.com/jhQ6s2Qwjhqpivlitm.webp",
		"https://i.giphy.com/GjfNsZPvCFs9dQrw36.webp",
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
	"https://i.imgur.com/giaxzSP.jpeg",
	"https://i.imgur.com/ELuCb1H.jpeg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/relatable-memes-jokes-memespointt-10-677cf9f8b57aa__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/relatable-memes-jokes-memespointt-35-677e714a64c1c__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/relatable-memes-jokes-memespointt-32-677e7089d37ed__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/relatable-memes-jokes-memespointt-37-677e71d07e283__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/relatable-memes-jokes-memespointt-19-677d015a22631__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/relatable-memes-jokes-memespointt-34-677e70e5ef167__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/relatable-memes-jokes-memespointt-4-677cf70d35587__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/relatable-memes-jokes-memespointt-31-677e705b1f746__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/relatable-memes-jokes-memespointt-33-677e70b520281__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/relatable-memes-jokes-memespointt-2-677cf62608ccb__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/relatable-memes-jokes-memespointt-6-677cf836e20bd__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/relatable-memes-jokes-memespointt-14-677cfece125a2__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/relatable-memes-jokes-memespointt-12-677cfdd8e5ab7__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/relatable-memes-jokes-memespointt-27-677d12eff1187__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/relatable-memes-jokes-memespointt-39-677e72289295d__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/relatable-memes-jokes-memespointt-41-677e72a6ee6a8__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/relatable-memes-jokes-memespointt-30-677d14da83f61__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/relatable-memes-jokes-memespointt-40-677e727a2bbb6__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/Cw95ZfXSSkf-png__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/relatable-memes-jokes-memespointt-24-677d109751518__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/CyGhEAHSRoY-png__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/relatable-memes-jokes-memespointt-43-677e7303d7dd4__700.jpg",
]


async def fetch_bytes(url: str) -> bytes:
	async with aiohttp.ClientSession() as session:
		async with session.get(url) as resp:
			if resp.status != 200:
				raise Exception(f"Failed to fetch image: HTTP {resp.status}")
			return await resp.read()


def _build_vote_embed() -> discord.Embed:
	embed = discord.Embed(
		title="🔒 Vote Required to Unlock This Feature",
		description=(
			"This feature is locked behind a **free vote** on Top.gg!\n"
			"Vote once every 12 hours to unlock a ton of powerful features 💙"
		),
		color=0x5865F2
	)
	embed.add_field(
		name="🎨 Creative Tools",
		value=(
			"• 🖼️ **Image Analysis** — send any image\n"
			"• 🎨 **Generate Image** — `/generate_image`\n"
			"• 🖌️ **Edit Images** — send image + instruction\n"
			"• 🖼️ **Merge Images** — attach 2+ images + say merge\n"
			"• 🎬 **Generate Video** — `/generate_video`\n"
			"• 🔊 **Text-to-Speech** — `/generate_tts`"
		),
		inline=False
	)
	embed.add_field(
		name="📁 File Tools",
		value=(
			"• 📄 **PDF Reading** — upload any PDF\n"
			"• 📝 **DOCX Reading** — upload Word documents\n"
			"• 📃 **TXT Reading** — upload text files\n"
			"• 🔍 **Smart Summaries** — get instant file summaries"
		),
		inline=False
	)
	embed.add_field(
		name="💬 Slash Action Commands",
		value=(
			"• 🤗 `/hug @user` — give someone a warm hug\n"
			"• 💋 `/kiss @user` — send a kiss with a GIF\n"
			"• 🥋 `/kick @user` — kick someone (playfully!)\n"
			"• 🖐️ `/slap @user` — slap with dramatic effect\n"
			"• 🌅 `/wish_goodmorning @user` — brighten someone's day\n"
			"• 🪙 `/bet [heads/tails]` — flip a coin and bet\n"
			"• 😂 `/meme` — get a random funny meme\n\n"
			"*Each sends a random GIF with custom text!*"
		),
		inline=False
	)
	embed.add_field(
		name="⏱️ How It Works",
		value=(
			"1️⃣ Click **Vote Now** below\n"
			"2️⃣ Vote on Top.gg (takes 10 seconds!)\n"
			"3️⃣ Your vote gets registered instantly! You may then use the features listed above!\n"
			"4️⃣ All features unlock for **12 hours** 🎉\n"
			"5️⃣ Vote again after 12 hours to keep access"
		),
		inline=False
	)
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
			content=None,
			embed=_build_vote_embed(),
			view=_build_vote_view()
		)
	return voted


async def require_vote_slash(interaction: discord.Interaction) -> bool:
	voted = await check_vote_status(interaction.user.id)
	if not voted:
		await interaction.response.send_message(
			embed=_build_vote_embed(),
			view=_build_vote_view(),
			ephemeral=False
		)
	return voted




class ConfigureGroup(app_commands.Group):
	def __init__(self):
		super().__init__(name="configure", description="Configure where the bot can chat in this server")

	async def _ensure_guild_owner(self, interaction: discord.Interaction) -> bool:
		if interaction.guild is None:
			await interaction.response.send_message(
				"❌ This command can only be used inside a server.",
				ephemeral=True
			)
			return False

		if interaction.guild.owner_id != interaction.user.id:
			if interaction.response.is_done():
				await interaction.followup.send("❌ You are not the server owner.", ephemeral=True)
			else:
				await interaction.response.send_message("❌ You are not the server owner.", ephemeral=True)
			return False

		if set_server_mode is None or set_channels_mode is None or get_guild_config is None:
			await interaction.response.send_message(
				"⚠️ Configuration system is not ready. Please try again in a moment.",
				ephemeral=True
			)
			return False

		return True

	@app_commands.command(name="server", description="Allow the bot to chat in all channels in this server")
	async def configure_server(self, interaction: discord.Interaction):
		if not await self._ensure_guild_owner(interaction):
			return

		channel_ids = [ch.id for ch in interaction.guild.text_channels]
		set_server_mode(interaction.guild.id, channel_ids)
		await interaction.response.send_message(
			"✅ Configuration updated: I can now chat in **the whole server** when pinged.",
			ephemeral=False
		)

	@app_commands.command(name="channels", description="Restrict bot chat to selected channel(s) in this server")
	@app_commands.describe(
		channel_1="Required channel",
		channel_2="Optional channel",
		channel_3="Optional channel",
		channel_4="Optional channel",
		channel_5="Optional channel",
	)
	async def configure_channels(
		self,
		interaction: discord.Interaction,
		channel_1: discord.TextChannel,
		channel_2: Optional[discord.TextChannel] = None,
		channel_3: Optional[discord.TextChannel] = None,
		channel_4: Optional[discord.TextChannel] = None,
		channel_5: Optional[discord.TextChannel] = None,
	):
		if not await self._ensure_guild_owner(interaction):
			return

		selected_channels = [
			ch for ch in [channel_1, channel_2, channel_3, channel_4, channel_5]
			if ch is not None
		]
		channel_ids = [ch.id for ch in selected_channels]

		set_channels_mode(interaction.guild.id, channel_ids)

		mentions = ", ".join(ch.mention for ch in selected_channels)
		await interaction.response.send_message(
			f"✅ Configuration updated: I will now only chat in these channel(s): {mentions}",
			ephemeral=False
		)

	@configure_server.error
	@configure_channels.error
	async def configure_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
		print(f"[CONFIGURE ERROR] {error}")
		if interaction.response.is_done():
			await interaction.followup.send("❌ You are not the server owner.", ephemeral=True)
		else:
			await interaction.response.send_message("❌ You are not the server owner.", ephemeral=True)


class Codunot(commands.Cog):
	def __init__(self, bot: commands.Bot):
		self.bot = bot
		self.bot.tree.add_command(ConfigureGroup())

	def _dm_usage_key(self, interaction: discord.Interaction) -> str:
		return f"dm_{interaction.user.id}"

	def _bot_missing_from_guild(self, interaction: discord.Interaction) -> bool:
		if interaction.guild_id is None:
			return False
	
		print(f"[DEBUG] guild={interaction.guild} guild_id={interaction.guild_id} is_user_integration={getattr(interaction, 'is_user_integration', lambda: 'N/A')()}")
	
		if interaction.guild is not None:
			return False
	
		if hasattr(interaction, "is_user_integration") and interaction.is_user_integration():
			return True
	
		return False

	async def _resolve_paid_usage_key(self, interaction: discord.Interaction) -> str | None:
		if not self._bot_missing_from_guild(interaction):
			return None

		try:
			dm_channel = interaction.user.dm_channel or await interaction.user.create_dm()
			if dm_channel is not None:
				return str(dm_channel.id)
		except Exception as e:
			print(f"[PAID USAGE KEY] Failed to resolve DM channel ID: {e}")

		return self._dm_usage_key(interaction)

	def _should_deliver_paid_output_in_dm(self, interaction: discord.Interaction) -> bool:
		return self._bot_missing_from_guild(interaction)

	async def _deliver_paid_attachment(
		self,
		interaction: discord.Interaction,
		content: str,
		filename: str,
		payload_bytes: bytes,
	):
		if not self._should_deliver_paid_output_in_dm(interaction):
			await interaction.followup.send(
				content=content,
				file=discord.File(io.BytesIO(payload_bytes), filename=filename),
			)
			return

		try:
			await interaction.user.send(
				f"{content}\n\n📩 I generated this in DMs because I'm not in that server, so I can't post the full output there.",
				file=discord.File(io.BytesIO(payload_bytes), filename=filename),
			)
			await interaction.followup.send(
				"📩 I generated your result, but since I'm not in this server I sent the full output to your DMs."
			)
		except discord.Forbidden:
			await interaction.followup.send(
				"⚠️ I generated your result but couldn't DM you (DMs are closed). Please enable DMs and try again."
			)

	@app_commands.command(name="funmode", description="😎 Activate Fun Mode - jokes, memes & chill vibes")
	async def funmode_slash(self, interaction: discord.Interaction):
		is_dm = isinstance(interaction.channel, discord.DMChannel)
		chan_id = f"dm_{interaction.user.id}" if is_dm else str(interaction.channel.id)
		channel_modes[chan_id] = "funny"
		memory.save_channel_mode(chan_id, "funny")
		channel_chess[chan_id] = False
		await interaction.response.send_message("😎 Fun mode activated!", ephemeral=False)

	@app_commands.command(name="seriousmode", description="🤓 Activate Serious Mode - clean, fact-based help")
	async def seriousmode_slash(self, interaction: discord.Interaction):
		is_dm = isinstance(interaction.channel, discord.DMChannel)
		chan_id = f"dm_{interaction.user.id}" if is_dm else str(interaction.channel.id)
		channel_modes[chan_id] = "serious"
		memory.save_channel_mode(chan_id, "serious")
		channel_chess[chan_id] = False
		await interaction.response.send_message("🤓 Serious mode ON", ephemeral=False)

	@app_commands.command(name="roastmode", description="🔥 Activate Roast Mode - playful burns")
	async def roastmode_slash(self, interaction: discord.Interaction):
		is_dm = isinstance(interaction.channel, discord.DMChannel)
		chan_id = f"dm_{interaction.user.id}" if is_dm else str(interaction.channel.id)
		channel_modes[chan_id] = "roast"
		memory.save_channel_mode(chan_id, "roast")
		channel_chess[chan_id] = False
		await interaction.response.send_message("🔥 ROAST MODE ACTIVATED", ephemeral=False)

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
				"Send your situation, paste a convo, or just ask anything 👇"
			)
	
		elif mode.value == "irl":
			channel_modes[chan_id] = "rizz_irl"
			memory.save_channel_mode(chan_id, "rizz_irl")
			channel_chess[chan_id] = False
			await interaction.response.send_message(
				"🗣️ **Rizz Coach (IRL) activated!**\n"
				"Describe your situation, ask for tips, or tell me what happened 👇"
			)

	@app_commands.command(name="chessmode", description="♟️ Activate Chess Mode - play chess with Codunot")
	async def chessmode_slash(self, interaction: discord.Interaction):
		is_dm = isinstance(interaction.channel, discord.DMChannel)
		chan_id = f"dm_{interaction.user.id}" if is_dm else str(interaction.channel.id)
		channel_chess[chan_id] = True
		channel_modes[chan_id] = "funny"
		chess_engine.new_board(chan_id)
		await interaction.response.send_message("♟️ Chess mode ACTIVATED. You are white, start!", ephemeral=False)

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
			await interaction.followup.send(
				"🚫 You've hit your **daily image generation limit**.\nTry again tomorrow or contact aarav_2022 for an upgrade."
			)
			return

		if not check_total_limit(interaction, "attachments", usage_key=usage_key):
			await interaction.followup.send(
				"🚫 You've hit your **2 months' image generation limit**.\nContact aarav_2022 for an upgrade."
			)
			return

		await interaction.followup.send("🎨 **Cooking up your image... hang tight ✨**")

		try:
			boosted_prompt = await boost_image_prompt(prompt)
			image_bytes = await generate_image(boosted_prompt, aspect_ratio="1:1", steps=15)

			output_text = (
				f"{interaction.user.mention} 🖼️ Generated: `{prompt[:150]}...`"
				if len(prompt) > 150
				else f"{interaction.user.mention} 🖼️ Generated: `{prompt}`"
			)
			await self._deliver_paid_attachment(
				interaction,
				output_text,
				"generated_image.png",
				image_bytes,
			)

			consume(interaction, "attachments", usage_key=usage_key)
			consume_total(interaction, "attachments", usage_key=usage_key)
			save_usage()

		except Exception as e:
			print(f"[SLASH IMAGE ERROR] type={type(e).__name__} err={e}")
			traceback.print_exc()
			await interaction.followup.send(
				f"{interaction.user.mention} 🤔 Couldn't generate image right now. Please try again later."
			)

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
			await interaction.followup.send(
				"🚫 You've hit your **daily video generation limit**.\nTry again tomorrow or contact aarav_2022 for an upgrade."
			)
			return

		if not check_total_limit(interaction, "attachments", usage_key=usage_key):
			await interaction.followup.send(
				"🚫 You've hit your **2 months' video generation limit**.\nContact aarav_2022 for an upgrade."
			)
			return

		await interaction.followup.send("🎬 **Rendering your video... this may take up to ~1 min ⏳**")

		try:
			boosted_prompt = await boost_video_prompt(prompt)
			video_bytes = await text_to_video_512(prompt=boosted_prompt)

			output_text = (
				f"{interaction.user.mention} 🎬 Generated: `{prompt[:150]}...`"
				if len(prompt) > 150
				else f"{interaction.user.mention} 🎬 Generated: `{prompt}`"
			)
			await self._deliver_paid_attachment(
				interaction,
				output_text,
				"generated_video.mp4",
				video_bytes,
			)

			consume(interaction, "attachments", usage_key=usage_key)
			consume_total(interaction, "attachments", usage_key=usage_key)
			save_usage()

		except Exception as e:
			print(f"[SLASH VIDEO ERROR] type={type(e).__name__} err={e}")
			traceback.print_exc()
			await interaction.followup.send(
				f"{interaction.user.mention} 🤔 Couldn't generate video right now. Please try again later."
			)

	@app_commands.command(name="generate_tts", description="🔊 Generate text-to-speech audio")
	@app_commands.describe(text="The text you want to convert to speech")
	async def generate_tts_slash(self, interaction: discord.Interaction, text: str):
		usage_key = await self._resolve_paid_usage_key(interaction)
		await interaction.response.defer()
		await interaction.edit_original_response(content="🗳️ **Checking your vote status...**")

		if not await require_vote_deferred(interaction):
			return

		await interaction.edit_original_response(content="✅ **Vote verified! You're good to go.**")

		if len(text) > MAX_TTS_LENGTH:
			await interaction.followup.send(
				f"🚫 Text is too long! Maximum {MAX_TTS_LENGTH} characters allowed.\nYour text: {len(text)} characters."
			)
			return

		if not check_limit(interaction, "attachments", usage_key=usage_key):
			await interaction.followup.send(
				"🚫 You've hit your **daily TTS generation limit**.\nTry again tomorrow or contact aarav_2022 for an upgrade."
			)
			return

		if not check_total_limit(interaction, "attachments", usage_key=usage_key):
			await interaction.followup.send(
				"🚫 You've hit your **2 months' TTS generation limit**.\nContact aarav_2022 for an upgrade."
			)
			return

		await interaction.followup.send("🔊 **Generating your audio... almost there 🎙️**")

		try:
			audio_url = await text_to_speech(text=text, voice="am_michael")

			async with aiohttp.ClientSession() as session:
				async with session.get(audio_url) as resp:
					if resp.status != 200:
						raise Exception("Failed to download TTS audio")
					audio_bytes = await resp.read()

			output_text = (
				f"{interaction.user.mention} 🔊 TTS: `{text[:150]}...`"
				if len(text) > 150
				else f"{interaction.user.mention} 🔊 TTS: `{text}`"
			)
			await self._deliver_paid_attachment(
				interaction,
				output_text,
				"speech.mp3",
				audio_bytes,
			)

			consume(interaction, "attachments", usage_key=usage_key)
			consume_total(interaction, "attachments", usage_key=usage_key)
			save_usage()

		except Exception as e:
			print(f"[SLASH TTS ERROR] {e}")
			await interaction.followup.send(
				f"{interaction.user.mention} 🤔 Couldn't generate speech right now. Please try again later."
			)

	async def _send_long_interaction_message(self, interaction: discord.Interaction, text: str):
		max_len = 2000
		remaining = (text or "").strip()
		while remaining:
			if len(remaining) <= max_len:
				await interaction.followup.send(remaining, ephemeral=False)
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
			await interaction.followup.send(chunk, ephemeral=False)

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

	async def _collect_recent_user_messages(
		self,
		channel: discord.abc.Messageable,
		user_id: int,
		limit: int = 60,
		max_scan: int = 4000,
	) -> tuple[list[str], int, bool]:
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
				if not content:
					continue
				if len(content) < 3:
					continue

				messages.append(content)
				if len(messages) >= limit:
					break
		except Exception as e:
			fetch_failed = True
			print(f"[GUESSAGE FETCH ERROR] {e}")

		messages.reverse()
		return messages, scanned, fetch_failed

	async def _collect_recent_user_messages_across_guild(
		self,
		guild: discord.Guild,
		user_id: int,
		exclude_channel_ids: set[int] | None = None,
		limit: int = 60,
		max_scan_per_channel: int = 1200,
	) -> tuple[list[str], int, bool, int]:
		messages: list[str] = []
		scanned_total = 0
		fetch_failed = False
		channels_used = 0
		exclude_ids = exclude_channel_ids or set()

		for channel in guild.text_channels:
			if channel.id in exclude_ids:
				continue

			channel_messages, scanned_count, failed = await self._collect_recent_user_messages(
				channel,
				user_id,
				limit=max(1, limit - len(messages)),
				max_scan=max_scan_per_channel,
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
			await interaction.response.send_message("❌ This command can only be used in DMs, server channels, or threads.", ephemeral=False)
			return

		await interaction.response.defer(ephemeral=False)
		await interaction.edit_original_response(content="🗳️ **Checking your vote status...**")

		if not await require_vote_deferred(interaction):
			return

		await interaction.edit_original_response(content="✅ **Vote verified! You're good to go.**")
		await interaction.edit_original_response(content="🔎 **Collecting recent messages...**")

		recent_messages, scanned_count, fetch_failed = await self._collect_recent_user_messages(
			interaction.channel,
			target_user.id,
			limit=60,
		)
		source_channels_used = 1 if recent_messages else 0

		if len(recent_messages) == 0 and interaction.guild is not None:
			await interaction.edit_original_response(content="🔎 **No messages in this channel. Searching other server channels...**")
			exclude_channel_ids: set[int] = set()
			if interaction.channel_id is not None:
				exclude_channel_ids.add(interaction.channel_id)
			if isinstance(interaction.channel, discord.Thread) and interaction.channel.parent_id:
				exclude_channel_ids.add(interaction.channel.parent_id)

			alt_messages, alt_scanned, alt_fetch_failed, alt_channels_used = await self._collect_recent_user_messages_across_guild(
				interaction.guild,
				target_user.id,
				exclude_channel_ids=exclude_channel_ids,
				limit=60,
			)
			scanned_count += alt_scanned
			fetch_failed = fetch_failed or alt_fetch_failed
			if alt_messages:
				recent_messages = alt_messages
				source_channels_used = alt_channels_used

		sample_count = len(recent_messages)
		if sample_count < 10:
			error_hint = ""
			if fetch_failed:
				error_hint = " I may be missing **Read Message History** permission in one or more channels."
			await interaction.followup.send(
				f"⚠️ I found only **{sample_count}** recent messages from {target_user.mention} "
				f"after scanning **{scanned_count}** channel messages. "
				"I need at least **10** messages for a better estimate."
				f"{error_hint}"
			)
			return

		await interaction.edit_original_response(content="🧠 **Analyzing message data...**")

		joined_messages = "\n".join(f"- {line}" for line in recent_messages)
		prompt = (
			"You estimate an approximate age range from message-writing style only. "
			"Never claim certainty and keep it strictly as a moderation insight.\n\n"
			"Return ONLY strict JSON with this exact schema:\n"
			"{\n"
			"  \"age_range\": \"13-18\",\n"
			"  \"exact_guess\": 16,\n"
			"  \"confidence\": \"low|medium|high\",\n"
			"  \"reasoning\": [\"short reason 1\", \"short reason 2\", \"short reason 3\"]\n"
			"}\n\n"
			"Rules:"
			"\n- Do not mention protected attributes."
			"\n- Use writing style only (slang density, punctuation style, topic maturity, sentence complexity)."
			"\n- Reasoning bullets must be short (<= 140 chars), non-repetitive, and no copied long phrases from messages."
			"\n- Be concise, max 4 reasoning bullets."
			"\n- If uncertain, widen the range and set confidence low."
			"\n- Keep exact_guess inside age_range."
			"\n- If sample_count < 20, confidence must be low or medium."
			"\n- If sample_count >= 40 and signals are consistent, confidence may be high."
			f"\n\nSample count: {sample_count}"
			"\n\nUser messages:\n"
			f"{joined_messages}"
		)

		result_text = await call_google_ai_studio(prompt=prompt, temperature=0.2)
		payload = self._safe_json_parse(result_text or "")

		if not payload:
			await interaction.followup.send("🤔 I couldn't parse the AI output this time. Please try `/guessage` again.")
			return

		age_range = str(payload.get("age_range") or "Unknown")
		exact_guess = payload.get("exact_guess")
		confidence = str(payload.get("confidence") or "unknown").capitalize()
		reasoning = payload.get("reasoning") or []
		if not isinstance(reasoning, list):
			reasoning = [str(reasoning)]
		reasoning = self._clean_reasoning_items([str(item) for item in reasoning])
		reasoning_lines = "\n".join(f"• {item}" for item in reasoning) or "• Not enough signal from messages."

		await interaction.edit_original_response(content="✨ **Designing your new age insight card...**")
		await asyncio.sleep(1.0)

		confidence_lower = confidence.lower()
		confidence_badge = {
			"high": "🟢 High",
			"medium": "🟡 Medium",
			"low": "🔴 Low",
		}.get(confidence_lower, "⚪ Unknown")

		guess_display = str(exact_guess) if exact_guess is not None else "Unknown"
		summary_line = f"**Range:** `{age_range}` • **Best Guess:** `{guess_display}` • **Confidence:** {confidence_badge}"

		embed = discord.Embed(
			title="🧭 Message Style Insight Panel",
			description=(
				f"Target: {target_user.mention}\n"
				f"{summary_line}"
			),
			color=0x8A63D2,
		)
		embed.add_field(
			name="📊 Analysis Stats",
			value=(
				f"• Messages analyzed: **{sample_count}**\n"
				f"• Channel messages scanned: **{scanned_count}**\n"
				f"• Source channels used: **{source_channels_used}**"
			),
			inline=False,
		)
		embed.add_field(name="🧠 Why this estimate", value=reasoning_lines, inline=False)
		embed.add_field(
			name="⚠️ Important",
			value="Style-based model estimate only. Use as a soft moderation signal, never for verification.",
			inline=False,
		)
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
		if host.startswith("www."):
			host_for_check = host[4:]
		else:
			host_for_check = host

		allowed = host in ALLOWED_TRANSCRIBE_HOSTS or any(
			host_for_check == suffix or host_for_check.endswith(f".{suffix}")
			for suffix in ALLOWED_TRANSCRIBE_HOST_SUFFIXES
		)
		if not allowed:
			return None

		query_items = parse_qsl(parsed.query, keep_blank_values=True)
		filtered_query = urlencode([
			(k, v)
			for (k, v) in query_items
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

	async def _send_transcription_fallback_result(
		self,
		*,
		request_id: str,
		channel_id: int,
		user_id: int,
		deliver_in_dm: bool,
	):
		try:
			transcript_text = await wait_for_transcription_text(request_id=request_id)
		except Exception as e:
			print(f"[TRANSCRIBE FALLBACK] Could not fetch transcript for {request_id}: {e}")
			return

		message = f"✅ **Transcription complete:**\n{transcript_text[:1900]}"
		try:
			if deliver_in_dm:
				user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
				await user.send(message)
			else:
				channel = self.bot.get_channel(channel_id)
				if channel is None:
					channel = await self.bot.fetch_channel(channel_id)
				await channel.send(message)
			print(f"[TRANSCRIBE FALLBACK] Delivered transcript for {request_id}")
		except Exception as e:
			print(f"[TRANSCRIBE FALLBACK] Discord send failed for {request_id}: {e}")

	@app_commands.command(name="transcribe", description="📝 Transcribe a supported video URL (max 30 mins)")
	@app_commands.describe(video_url="Supported: YouTube, Twitch VOD, X, Kick")
	async def transcribe_slash(self, interaction: discord.Interaction, video_url: str):
		usage_key = await self._resolve_paid_usage_key(interaction)
		normalized_video_url = self._normalize_transcribe_url(video_url)
		if not normalized_video_url:
			await interaction.response.send_message(
				"❌ Only YouTube, Twitch VODs, X, and Kick video URLs are allowed.",
				ephemeral=False,
			)
			return
	
		await interaction.response.defer(ephemeral=False)
		await interaction.edit_original_response(content="🗳️ **Checking your vote status...**")
	
		if not await require_vote_deferred(interaction):
			return

		if not check_limit(interaction, "attachments", usage_key=usage_key):
			await interaction.edit_original_response(
				content="🚫 You've hit your **daily transcription limit**.\nTry again tomorrow or contact aarav_2022 for an upgrade."
			)
			return

		if not check_total_limit(interaction, "attachments", usage_key=usage_key):
			await interaction.edit_original_response(
				content="🚫 You've hit your **2 months' transcription limit**.\nContact aarav_2022 for an upgrade."
			)
			return

		await interaction.edit_original_response(content="✅ **Vote verified! Submitting transcription...**")
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
						print(f"[TRANSCRIBE REGISTER] DM channel resolve failed: {e}")

			if register_base:
				try:
					async with aiohttp.ClientSession() as session:
						async with session.post(
							f"{register_base}/register-transcription",
							json={
								"request_id": request_id,
								"channel_id": register_channel_id,
								"user_id": interaction.user.id,
								"deliver_in_dm": deliver_in_dm,
							},
							timeout=aiohttp.ClientTimeout(total=15),
						) as register_resp:
							if register_resp.status >= 300:
								print(
									f"[TRANSCRIBE REGISTER] registration failed ({register_resp.status}): {await register_resp.text()}"
								)
				except Exception as register_error:
					print(f"[TRANSCRIBE REGISTER] register-transcription error: {register_error}")

			consume(interaction, "attachments", usage_key=usage_key)
			consume_total(interaction, "attachments", usage_key=usage_key)
			save_usage()

			asyncio.create_task(
				self._send_transcription_fallback_result(
					request_id=request_id,
					channel_id=register_channel_id,
					user_id=interaction.user.id,
					deliver_in_dm=deliver_in_dm,
				)
			)
	
		except VideoToTextError as e:
			await interaction.edit_original_response(content=f"❌ {e}")
			return
		except Exception as e:
			print(f"[SLASH TRANSCRIBE ERROR] {e}")
			await interaction.edit_original_response(content="🤔 Couldn't transcribe this video right now.")
			return
	
		if deliver_in_dm:
			await interaction.edit_original_response(
				content="📝 Transcription submitted! I'm not in this server, so I'll send the final transcript to your DMs."
			)
		else:
			await interaction.edit_original_response(
				content="📝 Transcription submitted! I'll post the result here when it's ready."
			)

	async def _send_action_gif(self, interaction: discord.Interaction, action: str, target_user: discord.User):
		if target_user.id == interaction.user.id:
			await interaction.response.send_message(
				f"😅 You can't /{action} yourself. Pick someone else!",
				ephemeral=False
			)
			return

		await interaction.response.defer()
		await interaction.edit_original_response(content="🗳️ **Checking your vote status...**")

		if not await require_vote_deferred(interaction):
			return

		await interaction.edit_original_response(content="✅ **Vote verified! You're good to go.**")

		loading_msg = await interaction.followup.send("🎉 **Loading your GIF...**", wait=True)

		try:
			source_url = random.choice(ACTION_GIF_SOURCES[action])
			text = random.choice(ACTION_MESSAGES[action]).format(
				user=interaction.user.mention,
				target=target_user.mention
			)

			embed = discord.Embed(description=text, color=0xFFA500)
			embed.set_image(url=source_url)

			await asyncio.sleep(3)
			await loading_msg.edit(content=None, embed=embed)

		except Exception as e:
			print(f"[SLASH {action.upper()} ERROR] {e}")
			await loading_msg.edit(content=f"🤔 Couldn't generate a {action} GIF right now. Try again in a bit.")

	@app_commands.command(name="hug", description="🤗 Hug any user with a random GIF (Vote Required)")
	@app_commands.describe(target_user="The user you want to hug")
	async def hug_slash(self, interaction: discord.Interaction, target_user: discord.User):
		await self._send_action_gif(interaction, "hug", target_user)

	@app_commands.command(name="kiss", description="💋 Kiss any user with a random GIF (Vote Required)")
	@app_commands.describe(target_user="The user you want to kiss")
	async def kiss_slash(self, interaction: discord.Interaction, target_user: discord.User):
		await self._send_action_gif(interaction, "kiss", target_user)

	@app_commands.command(name="kick", description="🥋 Kick any user with a random anime GIF (Vote Required)")
	@app_commands.describe(target_user="The user you want to kick")
	async def kick_slash(self, interaction: discord.Interaction, target_user: discord.User):
		await self._send_action_gif(interaction, "kick", target_user)

	@app_commands.command(name="slap", description="🖐️ Slap any user with a random anime GIF (Vote Required)")
	@app_commands.describe(target_user="The user you want to slap")
	async def slap_slash(self, interaction: discord.Interaction, target_user: discord.User):
		await self._send_action_gif(interaction, "slap", target_user)

	@app_commands.command(name="wish_goodmorning", description="🌅 Wish someone a very good morning with a GIF (Vote Required)")
	@app_commands.describe(target_user="The user you want to wish good morning")
	async def wish_goodmorning_slash(self, interaction: discord.Interaction, target_user: discord.User):
		await self._send_action_gif(interaction, "wish_goodmorning", target_user)

	@app_commands.command(name="bet", description="🪙 Bet on heads or tails with a coin flip (Vote Required)")
	@app_commands.describe(side="Choose heads or tails")
	@app_commands.choices(side=[
		app_commands.Choice(name="heads", value="heads"),
		app_commands.Choice(name="tails", value="tails"),
	])
	async def bet_slash(self, interaction: discord.Interaction, side: app_commands.Choice[str]):
		await interaction.response.defer()
		await interaction.edit_original_response(content="🗳️ **Checking your vote status...**")

		if not await require_vote_deferred(interaction):
			return

		await interaction.edit_original_response(content="✅ **Vote verified! You're good to go.**")

		await interaction.followup.send("🪙 **Flipping the coin...**")

		result = random.choice(["heads", "tails"])
		did_win = side.value == result

		if did_win:
			msg = f"🪙 The coin landed on **{result}**! {interaction.user.mention} guessed correctly and wins! 🎉"
		else:
			msg = f"🪙 The coin landed on **{result}**! {interaction.user.mention} guessed **{side.value}** and lost this round."

		await interaction.followup.send(msg)

	@app_commands.command(name="meme", description="😂 Send a random meme (Vote Required)")
	async def meme_slash(self, interaction: discord.Interaction):
		await interaction.response.defer()
		await interaction.edit_original_response(content="🗳️ **Checking your vote status...**")

		if not await require_vote_deferred(interaction):
			return

		await interaction.edit_original_response(content="✅ **Vote verified! You're good to go.**")

		await interaction.followup.send("😂 **Loading your meme...**")

		meme_url = random.choice(MEME_SOURCES)
		embed = discord.Embed(title="😂 Random Meme", color=0x00BFFF)
		embed.set_image(url=meme_url)
		await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
	cog = Codunot(bot)
	await bot.add_cog(cog)
	print(f"[COG] Loaded Codunot cog with {len(cog.get_app_commands())} app commands")
