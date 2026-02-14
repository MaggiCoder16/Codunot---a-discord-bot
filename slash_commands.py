import discord
from discord import app_commands
from discord.ext import commands
import os
import time
import io
import aiohttp
import random
from PIL import Image, ImageDraw, ImageFont, ImageSequence

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
    ],
    "kiss": [
        "https://media0.giphy.com/media/v1.Y2lkPTc5MGI3NjExOGVoeXMxd3FteTF0cGRmMDQzNjRxMm0ybWV1Zno2ZGJycGs3enlhcSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/G3va31oEEnIkM/giphy.gif",
        "https://media.giphy.com/media/bGm9FuBCGg4SY/giphy.gif",
    ],
    "kick": [
        "https://media0.giphy.com/media/v1.Y2lkPTc5MGI3NjExcHpjMHQ4NnNxZjMzOWdpOXozamNpbmRrOG9jZ2xpcnNmb3V3M3pxdiZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/DfI1LsaCkWD20xRc4r/giphy.gif",
        "https://media0.giphy.com/media/v1.Y2lkPTc5MGI3NjExaG1raWhsZWZoYTRmNTB5ZXJqano3dDdtcnN2cGtpazJoMm1zZDBpcSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/3o7TKwVQMoQh2At9qU/giphy.gif",
    ],
}


def _fit_text(draw: ImageDraw.ImageDraw, text: str, max_width: int, base_size: int = 42) -> tuple[ImageFont.ImageFont, str]:
    """Pick a font size that fits inside max_width."""
    size = base_size
    while size >= 18:
        try:
            font = ImageFont.truetype("DejaVuSans-Bold.ttf", size)
        except Exception:
            font = ImageFont.load_default()
        content = text
        bbox = draw.textbbox((0, 0), content, font=font)
        if bbox[2] - bbox[0] <= max_width:
            return font, content
        size -= 2

    if len(text) > 70:
        text = text[:67] + "..."
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 18)
    except Exception:
        font = ImageFont.load_default()
    return font, text


def _draw_outlined_text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], txt: str, font: ImageFont.ImageFont):
    x, y = xy
    for ox, oy in [(-2, -2), (-2, 0), (-2, 2), (0, -2), (0, 2), (2, -2), (2, 0), (2, 2)]:
        draw.text((x + ox, y + oy), txt, font=font, fill=(0, 0, 0))
    draw.text((x, y), txt, font=font, fill=(255, 255, 255))


async def fetch_bytes(url: str) -> bytes:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                raise Exception(f"Failed to fetch gif: HTTP {resp.status}")
            return await resp.read()


def overlay_action_text_on_gif(gif_bytes: bytes, action_word: str, actor_name: str, target_name: str) -> bytes:
    """Overlay title + participant labels on each GIF frame."""
    gif = Image.open(io.BytesIO(gif_bytes))

    frames = []
    durations = []
    loop = gif.info.get("loop", 0)

    for frame in ImageSequence.Iterator(gif):
        rgba = frame.convert("RGBA")
        w, h = rgba.size

        band_height = max(80, int(h * 0.24))
        canvas = Image.new("RGBA", (w, h + band_height), (0, 0, 0, 220))
        canvas.alpha_composite(rgba, dest=(0, band_height))

        draw = ImageDraw.Draw(canvas)

        title = f"{actor_name} {action_word} {target_name}"
        title_font, title_text = _fit_text(draw, title, max_width=w - 24, base_size=40)
        title_bbox = draw.textbbox((0, 0), title_text, font=title_font)
        title_w = title_bbox[2] - title_bbox[0]
        _draw_outlined_text(draw, ((w - title_w) // 2, 8), title_text, title_font)


        frames.append(canvas.convert("P", palette=Image.ADAPTIVE))
        durations.append(frame.info.get("duration", gif.info.get("duration", 80)))

    output = io.BytesIO()
    frames[0].save(
        output,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=loop,
        optimize=False,
        disposal=2,
    )
    output.seek(0)
    return output.read()


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
                ephemeral=True
            )
            return

        await interaction.response.defer()

        try:
            source_url = random.choice(ACTION_GIF_SOURCES[action])
            source_bytes = await fetch_bytes(source_url)
            gif_bytes = overlay_action_text_on_gif(
                source_bytes,
                action,
                interaction.user.display_name,
                target_user.display_name,
            )

            await interaction.followup.send(
                content=f"{interaction.user.mention} {action} {target_user.mention}",
                file=discord.File(io.BytesIO(gif_bytes), filename=f"{action}.gif")
            )
        except Exception as e:
            print(f"[SLASH {action.upper()} ERROR] {e}")
            await interaction.followup.send(
                f"🤔 Couldn't generate a {action} GIF right now. Try again in a bit."
            )

    @app_commands.command(name="hug", description="🤗 Send a hugging GIF with custom names")
    @app_commands.describe(target_user="The user you want to hug")
    async def hug_slash(self, interaction: discord.Interaction, target_user: discord.User):
        await self._send_action_gif(interaction, "hug", target_user)

    @app_commands.command(name="kiss", description="💋 Send a kissing GIF with custom names")
    @app_commands.describe(target_user="The user you want to kiss")
    async def kiss_slash(self, interaction: discord.Interaction, target_user: discord.User):
        await self._send_action_gif(interaction, "kiss", target_user)

    @app_commands.command(name="kick", description="🥋 Send an anime kick GIF with custom names")
    @app_commands.describe(target_user="The user you want to kick")
    async def kick_slash(self, interaction: discord.Interaction, target_user: discord.User):
        await self._send_action_gif(interaction, "kick", target_user)


async def setup(bot: commands.Bot):
    await bot.add_cog(Codunot(bot))
