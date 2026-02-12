import discord
from discord import app_commands
from discord.ext import commands
import os
import time
import io
import aiohttp

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
boost_image_prompt = None
save_vote_unlocks = None

# =========================
#  GUILD CHECK / DECORATOR
# =========================

async def require_bot_in_guild(interaction: discord.Interaction) -> bool:
    """
    Allows command in DMs or in servers where the bot is present.
    Blocks execution in servers where the bot isn't present.
    """
    # Allow DMs
    if isinstance(interaction.channel, discord.DMChannel):
        return True

    # Allow if bot is in the guild
    if interaction.guild and interaction.guild.get_member(interaction.client.user.id):
        return True

    # Block if bot isn't in the guild
    await interaction.response.send_message(
        "🚫 I am not in this server, so this command cannot be used here.",
        ephemeral=True
    )
    return False

def guild_only_command(func):
    """Decorator to apply the guild check to a slash command."""
    async def wrapper(self, interaction: discord.Interaction, *args, **kwargs):
        allowed = await require_bot_in_guild(interaction)
        if not allowed:
            return  # Stop execution
        return await func(self, interaction, *args, **kwargs)
    return wrapper

# =========================
#  VOTE CHECK
# =========================

async def require_vote_slash(interaction: discord.Interaction) -> bool:
    # Owner bypass
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
        "🗳️ Vote to unlock **Image generations & editing, Video generations, "
        "Text-To-Speech & File tools** for **12 hours** 💙\n\n"
        "👉 https://top.gg/bot/1435987186502733878/vote\n\n"
        "⏱️ After 12 hours, you'll need to vote again to regain access.\n"
        "⏳ Once you vote, please wait for **5-10 minutes** before retrying.",
        ephemeral=False
    )
    return False

class Codunot(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ============ MODE COMMANDS ============

    @app_commands.command(name="funmode", description="😎 Activate Fun Mode - jokes, memes & chill vibes")
    @guild_only_command
    async def funmode_slash(self, interaction: discord.Interaction):
        is_dm = isinstance(interaction.channel, discord.DMChannel)
        chan_id = f"dm_{interaction.user.id}" if is_dm else str(interaction.channel.id)

        channel_modes[chan_id] = "funny"
        memory.save_channel_mode(chan_id, "funny")
        channel_chess[chan_id] = False

        await interaction.response.send_message("😎 Fun mode activated!", ephemeral=False)

    @app_commands.command(name="seriousmode", description="🤓 Activate Serious Mode - clean, fact-based help")
    @guild_only_command
    async def seriousmode_slash(self, interaction: discord.Interaction):
        is_dm = isinstance(interaction.channel, discord.DMChannel)
        chan_id = f"dm_{interaction.user.id}" if is_dm else str(interaction.channel.id)

        channel_modes[chan_id] = "serious"
        memory.save_channel_mode(chan_id, "serious")
        channel_chess[chan_id] = False

        await interaction.response.send_message("🤓 Serious mode ON", ephemeral=False)

    @app_commands.command(name="roastmode", description="🔥 Activate Roast Mode - playful burns")
    @guild_only_command
    async def roastmode_slash(self, interaction: discord.Interaction):
        is_dm = isinstance(interaction.channel, discord.DMChannel)
        chan_id = f"dm_{interaction.user.id}" if is_dm else str(interaction.channel.id)

        channel_modes[chan_id] = "roast"
        memory.save_channel_mode(chan_id, "roast")
        channel_chess[chan_id] = False

        await interaction.response.send_message("🔥 ROAST MODE ACTIVATED", ephemeral=False)

    @app_commands.command(name="chessmode", description="♟️ Activate Chess Mode - play chess with Codunot")
    @guild_only_command
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
    @guild_only_command
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
                "🚫 You've hit your **total image generation limit**.\n"
                "Contact aarav_2022 for an upgrade.",
                ephemeral=False
            )
            return

        await interaction.response.defer()

        try:
            boosted_prompt = await boost_image_prompt(prompt)
            image_bytes = await generate_image(boosted_prompt, aspect_ratio="16:9", steps=15)

            await interaction.followup.send(
                content=f"{interaction.user.mention} 🖼️ Generated: `{prompt[:100]}...`" if len(prompt) > 100 else f"{interaction.user.mention} 🖼️ Generated: `{prompt}`",
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
    @guild_only_command
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
                "🚫 You've hit your **total video generation limit**.\n"
                "Contact aarav_2022 for an upgrade.",
                ephemeral=False
            )
            return

        await interaction.response.defer()

        try:
            boosted_prompt = await boost_image_prompt(prompt)
            video_bytes = await text_to_video_512(prompt=boosted_prompt)

            await interaction.followup.send(
                content=f"{interaction.user.mention} 🎬 Generated: `{prompt[:100]}...`" if len(prompt) > 100 else f"{interaction.user.mention} 🎬 Generated: `{prompt}`",
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
    @guild_only_command
    async def generate_tts_slash(self, interaction: discord.Interaction, text: str):
        if not await require_vote_slash(interaction):
            return

        if not check_limit(interaction, "attachments"):
            await interaction.response.send_message(
                "🚫 You've hit your **daily TTS generation limit**.\n"
                "Try again tomorrow or contact aarav_2022 for an upgrade.",
                ephemeral=False
            )
            return

        if not check_total_limit(interaction, "attachments"):
            await interaction.response.send_message(
                "🚫 You've hit your **total TTS generation limit**.\n"
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
                content=f"{interaction.user.mention} 🔊 TTS: `{text[:100]}...`" if len(text) > 100 else f"{interaction.user.mention} 🔊 TTS: `{text}`",
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


async def setup(bot: commands.Bot):
    await bot.add_cog(Codunot(bot))
