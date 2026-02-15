import discord
from discord import app_commands
from discord.ext import commands
import os
import time
import io
import aiohttp
import random

from memory import MemoryManager
from deAPI_client_image import generate_image
from deAPI_client_text2vid import generate_video as text_to_video_512
from deAPI_client_text2speech import text_to_speech

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
BOT_NAME = "Codunot"
MAX_TTS_LENGTH = 150
boost_image_prompt = None
boost_video_prompt = None
save_vote_unlocks = None

ACTION_GIF_SOURCES = {
    "hug": [
        "https://media1.giphy.com/media/v1.Y2lkPTc5MGI3NjExYjFxbWd0djU0Y240MHE3d2t3dnIyZWtsaGI0aTFleGVncWswcDdkYyZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/uakdGGShmMS0KYfTgp/giphy.gif",
        "https://media.tenor.com/bVN5MdTrelYAAAAj/yaseen1.gif",
        "https://media.tenor.com/FNX3Xvr6yGwAAAAi/snek-bubu.gif",
        "https://i.imgur.com/uXL0iTg.gif",
    ],
    "kiss": [
        "https://media0.giphy.com/media/v1.Y2lkPTc5MGI3NjExOGVoeXMxd3FteTF0cGRmMDQzNjRxMm0ybWV1Zno2ZGJycGs3enlhcSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/G3va31oEEnIkM/giphy.gif",
        "https://media.giphy.com/media/bGm9FuBCGg4SY/giphy.gif",
        "https://media1.tenor.com/m/dd4mZNppytYAAAAd/1.gif",
        "https://media1.tenor.com/m/Y2AdPDiQoK8AAAAC/kiss-love.gif",
    ],
    "kick": [
        "https://media0.giphy.com/media/v1.Y2lkPTc5MGI3NjExcHpjMHQ4NnNxZjMzOWdpOXozamNpbmRrOG9jZ2xpcnNmb3V3M3pxdiZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/DfI1LsaCkWD20xRc4r/giphy.gif",
        "https://media0.giphy.com/media/v1.Y2lkPTc5MGI3NjExaG1raWhsZWZoYTRmNTB5ZXJqano3dDdtcnN2cGtpazJoMm1zZDBpcSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/3o7TKwVQMoQh2At9qU/giphy.gif",
        "https://media.tenor.com/TDQXdEBNNjUAAAAi/milk-and-mocha.gif",
        "https://media.tenor.com/ztHpFwsax84AAAAi/hau-zozo-smile.gif",
    ],
    "slap": [
        "https://media.tenor.com/TVPYqh_E1JYAAAAj/peach-goma-peach-and-goma.gif",
        "https://media.tenor.com/tMVS_yML7t0AAAAj/slap-slaps.gif",
        "https://media1.tenor.com/m/OTr4wv64hwwAAAAd/come-here-come-closer.gif",
        "https://media1.tenor.com/m/4Ut_QPbeCZIAAAAd/i-see-you-i-see.gif",
        "https://c.tenor.com/LHlITawhrEcAAAAd/tenor.gif",
    ],
    "wish_goodmorning": [
        "https://media.tenor.com/xwlZJGC0EqwAAAAj/pengu-pudgy.gif",
        "https://tenor.com/view/have-a-great-day-good-day-have-a-good-day-nice-day-enjoy-your-day-gif-16328321276428216691",
        "https://media.tenor.com/xlwtvJtC6FAAAAAM/jjk-jujutsu-kaisen.gif",
        "https://c.tenor.com/6VbeqshMfkEAAAAd/tenor.gif",
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
                raise Exception(f"Failed to fetch gif: HTTP {resp.status}")
            return await resp.read()


# =========================
#  VOTE CHECK
# =========================

async def require_vote_slash(interaction: discord.Interaction) -> bool:
    if interaction.user.id in OWNER_IDS:
        return True

    user_id = interaction.user.id
    now = time.time()
    unlock_time = user_vote_unlocks.get(user_id)
    if unlock_time and (now - unlock_time) < VOTE_DURATION:
        return True

    if await has_voted(user_id):
        user_vote_unlocks[user_id] = now
        if save_vote_unlocks:
            save_vote_unlocks()
        return True

    await interaction.response.send_message(
        "🚫 **This feature requires a Top.gg vote**\n\n"
        "🗳️ Vote to unlock **Image generations, merging & editing, Video generations, "
        "Text-To-Speech & File tools** for **12 hours** 💙\n\n"
        "👉 https://top.gg/bot/1435987186502733878/vote\n\n"
        "⏱️ After 12 hours, you'll need to vote again to regain access.\n"
        "⏳ Once you vote, please wait for **5-10 minutes** before retrying.",
        ephemeral=False
    )
    return False

# =========================
#  COG
# =========================

class Codunot(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ============ MODE COMMANDS ============

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

    @app_commands.command(name="chessmode", description="♟️ Activate Chess Mode - play chess with Codunot")
    async def chessmode_slash(self, interaction: discord.Interaction):
        is_dm = isinstance(interaction.channel, discord.DMChannel)
        chan_id = f"dm_{interaction.user.id}" if is_dm else str(interaction.channel.id)

        channel_chess[chan_id] = True
        channel_modes[chan_id] = "funny"
        chess_engine.new_board(chan_id)

        await interaction.response.send_message("♟️ Chess mode ACTIVATED. You are white, start!", ephemeral=False)

    # ============ GENERATION COMMANDS ============

    @app_commands.command(name="generate_image", description="🖼️ Generate an AI image from a text prompt")
    @app_commands.describe(prompt="Describe the image you want to generate")
    async def generate_image_slash(self, interaction: discord.Interaction, prompt: str):
        if not await require_vote_slash(interaction):
            return

        if not check_limit(interaction, "attachments"):
            await interaction.response.send_message(
                "🚫 You've hit your **daily image generation limit**.\n"
                "Try again tomorrow or contact aarav_2022 for an upgrade.",
                ephemeral=False
            )
            return

        if not check_total_limit(interaction, "attachments"):
            await interaction.response.send_message(
                "🚫 You've hit your **2 months' image generation limit**.\n"
                "Contact aarav_2022 for an upgrade.",
                ephemeral=False
            )
            return

        await interaction.response.defer()

        try:
            boosted_prompt = await boost_image_prompt(prompt)
            image_bytes = await generate_image(boosted_prompt, aspect_ratio="16:9", steps=15)

            await interaction.followup.send(
                content=f"{interaction.user.mention} 🖼️ Generated: `{prompt[:150]}...`" if len(prompt) > 150 else f"{interaction.user.mention} 🖼️ Generated: `{prompt}`",
                file=discord.File(io.BytesIO(image_bytes), filename="generated_image.png")
            )

            consume(interaction, "attachments")
            consume_total(interaction, "attachments")
            save_usage()

        except Exception as e:
            print(f"[SLASH IMAGE ERROR] {e}")
            await interaction.followup.send(
                f"{interaction.user.mention} 🤔 Couldn't generate image right now. Please try again later."
            )

    @app_commands.command(name="generate_video", description="🎬 Generate an AI video from a text prompt")
    @app_commands.describe(prompt="Describe the video you want to generate")
    async def generate_video_slash(self, interaction: discord.Interaction, prompt: str):
        if not await require_vote_slash(interaction):
            return
    
        if not check_limit(interaction, "attachments"):
            await interaction.response.send_message(
                "🚫 You've hit your **daily video generation limit**.\n"
                "Try again tomorrow or contact aarav_2022 for an upgrade.",
                ephemeral=False
            )
            return
    
        if not check_total_limit(interaction, "attachments"):
            await interaction.response.send_message(
                "🚫 You've hit your **2 months' video generation limit**.\n"
                "Contact aarav_2022 for an upgrade.",
                ephemeral=False
            )
            return
    
        await interaction.response.defer()
    
        try:
            boosted_prompt = await boost_video_prompt(prompt)
            video_bytes = await text_to_video_512(prompt=boosted_prompt)
    
            await interaction.followup.send(
                content=(
                    f"{interaction.user.mention} 🎬 Generated: `{prompt[:150]}...`"
                    if len(prompt) > 150
                    else f"{interaction.user.mention} 🎬 Generated: `{prompt}`"
                ),
                file=discord.File(io.BytesIO(video_bytes), filename="generated_video.mp4")
            )
    
            consume(interaction, "attachments")
            consume_total(interaction, "attachments")
            save_usage()
    
        except Exception as e:
            print(f"[SLASH VIDEO ERROR] {e}")
            await interaction.followup.send(
                f"{interaction.user.mention} 🤔 Couldn't generate video right now. Please try again later."
            )

    @app_commands.command(name="generate_tts", description="🔊 Generate text-to-speech audio")
    @app_commands.describe(text="The text you want to convert to speech")
    async def generate_tts_slash(self, interaction: discord.Interaction, text: str):
        if not await require_vote_slash(interaction):
            return

        if len(text) > MAX_TTS_LENGTH:
            await interaction.response.send_message(
                f"🚫 Text is too long! Maximum {MAX_TTS_LENGTH} characters allowed.\n"
                f"Your text: {len(text)} characters.",
                ephemeral=False
            )
            return

        if not check_limit(interaction, "attachments"):
            await interaction.response.send_message(
                "🚫 You've hit your **daily text-to-speech generation limit**.\n"
                "Try again tomorrow or contact aarav_2022 for an upgrade.",
                ephemeral=False
            )
            return

        if not check_total_limit(interaction, "attachments"):
            await interaction.response.send_message(
                "🚫 You've hit your **2 months' text-to-speech generation limit**.\n"
                "Contact aarav_2022 for an upgrade.",
                ephemeral=False
            )
            return

        await interaction.response.defer()

        try:
            audio_url = await text_to_speech(text=text, voice="am_michael")

            async with aiohttp.ClientSession() as session:
                async with session.get(audio_url) as resp:
                    if resp.status != 200:
                        raise Exception("Failed to download TTS audio")
                    audio_bytes = await resp.read()

            await interaction.followup.send(
                content=f"{interaction.user.mention} 🔊 TTS: `{text[:150]}...`" if len(text) > 150 else f"{interaction.user.mention} 🔊 TTS: `{text}`",
                file=discord.File(io.BytesIO(audio_bytes), filename="speech.mp3")
            )

            consume(interaction, "attachments")
            consume_total(interaction, "attachments")
            save_usage()

        except Exception as e:
            print(f"[SLASH TTS ERROR] {e}")
            await interaction.followup.send(
                f"{interaction.user.mention} 🤔 Couldn't generate speech right now. Please try again later."
            )


    async def _send_action_gif(self, interaction: discord.Interaction, action: str, target_user: discord.User):
        if target_user.id == interaction.user.id:
            await interaction.response.send_message(
                f"😅 You can't /{action} yourself. Pick someone else!",
                ephemeral=False
            )
            return

        await interaction.response.defer()

        try:
            source_url = random.choice(ACTION_GIF_SOURCES[action])
            text = random.choice(ACTION_MESSAGES[action]).format(
                user=interaction.user.mention,
                target=target_user.mention
            )
            
            embed = discord.Embed(
                description=text,
                color=0xFFA500
            )
            embed.set_image(url=source_url)
            
            await interaction.followup.send(embed=embed)
        except Exception as e:
            print(f"[SLASH {action.upper()} ERROR] {e}")
            await interaction.followup.send(
                f"🤔 Couldn't generate a {action} GIF right now. Try again in a bit."
            )

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

    @app_commands.command(name="wish_goodmorning", description="🌅 Wish someone a very good morning with a GIF")
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
        result = random.choice(["heads", "tails"])
        did_win = side.value == result

        if did_win:
            message = (
                f"🪙 The coin landed on **{result}**! {interaction.user.mention} guessed correctly and wins! 🎉"
            )
        else:
            message = (
                f"🪙 The coin landed on **{result}**! {interaction.user.mention} guessed **{side.value}** and lost this round."
            )

        await interaction.response.send_message(message, ephemeral=False)

    @app_commands.command(name="meme", description="😂 Send a random meme")
    async def meme_slash(self, interaction: discord.Interaction):
        meme_url = random.choice(MEME_SOURCES)
        embed = discord.Embed(
            title="😂 Random Meme",
            color=0x00BFFF,
        )
        embed.set_image(url=meme_url)
        await interaction.response.send_message(embed=embed, ephemeral=False)

async def setup(bot: commands.Bot):
    await bot.add_cog(Codunot(bot))
