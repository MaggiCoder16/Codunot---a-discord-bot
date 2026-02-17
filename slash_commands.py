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
            "• 😂 `/meme` — get a random hot meme\n\n"
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


class Codunot(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

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

    @app_commands.command(name="generate_image", description="🖼️ Generate an AI image from a text prompt")
    @app_commands.describe(prompt="Describe the image you want to generate")
    async def generate_image_slash(self, interaction: discord.Interaction, prompt: str):
        await interaction.response.defer()
        await interaction.edit_original_response(content="🗳️ **Checking your vote status...**")

        if not await require_vote_deferred(interaction):
            return

        await interaction.edit_original_response(content="✅ **Vote verified! You're good to go.**")

        if not check_limit(interaction, "attachments"):
            await interaction.followup.send(
                "🚫 You've hit your **daily image generation limit**.\nTry again tomorrow or contact aarav_2022 for an upgrade."
            )
            return

        if not check_total_limit(interaction, "attachments"):
            await interaction.followup.send(
                "🚫 You've hit your **2 months' image generation limit**.\nContact aarav_2022 for an upgrade."
            )
            return

        await interaction.followup.send("🎨 **Cooking up your image... hang tight ✨**")

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
        await interaction.response.defer()
        await interaction.edit_original_response(content="🗳️ **Checking your vote status...**")

        if not await require_vote_deferred(interaction):
            return

        await interaction.edit_original_response(content="✅ **Vote verified! You're good to go.**")

        if not check_limit(interaction, "attachments"):
            await interaction.followup.send(
                "🚫 You've hit your **daily video generation limit**.\nTry again tomorrow or contact aarav_2022 for an upgrade."
            )
            return

        if not check_total_limit(interaction, "attachments"):
            await interaction.followup.send(
                "🚫 You've hit your **2 months' video generation limit**.\nContact aarav_2022 for an upgrade."
            )
            return

        await interaction.followup.send("🎬 **Rendering your video... this may take up to ~1 min ⏳**")

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

        if not check_limit(interaction, "attachments"):
            await interaction.followup.send(
                "🚫 You've hit your **daily TTS generation limit**.\nTry again tomorrow or contact aarav_2022 for an upgrade."
            )
            return

        if not check_total_limit(interaction, "attachments"):
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
