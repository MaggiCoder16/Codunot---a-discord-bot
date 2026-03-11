import asyncio
import os
import discord
from dotenv import load_dotenv

load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

def build_announce_embed(guild: discord.Guild) -> discord.Embed:
    embed = discord.Embed(
        title="🚀 Big Codunot Update — New Models, More Voices, Better Music & More!",
        description=(
            "Hey everyone! We just dropped a major feature update to make Codunot "
            "way more customizable, expressive, and fun to use 🎉"
        ),
        color=0xFFA500,
    )

    embed.add_field(
        name="🧠 1) Model Switching is Live (`/model`)",
        value=(
            "You can now switch chat models per channel/DM using `/model`\n\n"
            "**Available models:**\n"
            "• GPT-OSS-120B *(default)*\n"
            "• `moonshotai/kimi-k2-instruct`\n"
            "• `allam-2-7b`\n"
            "• `qwen/qwen3-32b`\n"
            "• `llama-3.3-70b-versatile`\n"
            "• `meta-llama/llama-4-scout-17b-16e-instruct`\n"
            "• `llama-3.1-8b-instant`\n\n"
            "When you switch, Codunot confirms the old/new model and resets memory for a fresh conversation context."
        ),
        inline=False,
    )

    embed.add_field(
        name="🌍 2) Massive Edge TTS Language + Voice Expansion",
        value=(
            "Text-to-speech got a huge upgrade:\n"
            "• Tons of new voices added across many regions/languages\n"
            "• Better language grouping\n"
            "• Cleaner language experience\n\n"
            "✅ Users now see language names (like **English**, **Hindi**, **Arabic**, **Japanese**) "
            "instead of technical IDs."
        ),
        inline=False,
    )

    embed.add_field(
        name="🔊 3) Better Music Controls",
        value=(
            "Music got quality-of-life buffs:\n"
            "• `/volume_up` and `/volume_down` commands\n"
            "• `/autoplay` toggle — keeps playing after the queue ends\n"
            "• `/lyrics` — fetch full lyrics for the current track"
        ),
        inline=False,
    )

    embed.add_field(
        name="🖼️ 4) Free Image Search (`/image_search`)",
        value=(
            "New free command — no vote needed!\n"
            "Search images from **Wikimedia Commons** and **Openverse** by typing any query. "
            "Find any image instantly without leaving Discord."
        ),
        inline=False,
    )

    embed.add_field(
        name="💬 Why this matters",
        value=(
            "• More control over AI behavior (model selection)\n"
            "• Way better voice diversity in TTS\n"
            "• Smoother music experience\n"
            "• Quick visual search tools"
        ),
        inline=False,
    )

    embed.set_footer(text="Codunot — ty for using codu! please support me by voting on top.gg 🙂 — by aarav_2022")
    return embed

def pick_channel(guild: discord.Guild) -> discord.TextChannel | None:
    me = guild.me
    priority_names = ["announcements", "general", "bot-commands", "bot-spam", "bots", "chat"]

    for name in priority_names:
        ch = discord.utils.get(guild.text_channels, name=name)
        if ch and ch.permissions_for(me).send_messages:
            return ch

    for ch in guild.text_channels:
        if ch.permissions_for(me).send_messages:
            return ch

    return None

class AnnouncerBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.guilds = True
        super().__init__(intents=intents)

    async def on_ready(self):
        print(f"[ANNOUNCER] Logged in as {self.user} ({self.user.id})")
        print(f"[ANNOUNCER] Sending to {len(self.guilds)} server(s)...\n")

        success = []
        failed  = []
        skipped = []

        for guild in self.guilds:
            channel = pick_channel(guild)
            if channel is None:
                skipped.append(f"{guild.name} ({guild.id}) — no writable channel found")
                continue

            try:
                embed = build_announce_embed(guild)
                await channel.send(embed=embed)
                success.append(f"✅ {guild.name} → #{channel.name}")
                print(f"  ✅ Sent to {guild.name} → #{channel.name}")
            except Exception as e:
                failed.append(f"❌ {guild.name} ({guild.id}) — {e}")
                print(f"  ❌ Failed {guild.name}: {e}")

            await asyncio.sleep(1.5)

        print("\n── SUMMARY ─────────────────────────────")
        print(f"Sent:    {len(success)}")
        print(f"Failed:  {len(failed)}")
        print(f"Skipped: {len(skipped)}")

        if failed:
            print("\nFailed servers:")
            for f in failed:
                print(f"  {f}")

        if skipped:
            print("\nSkipped servers (no writable channel):")
            for s in skipped:
                print(f"  {s}")

        print("\n[ANNOUNCER] Done. Closing.")
        await self.close()


if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("ERROR: DISCORD_TOKEN not set in .env")
        exit(1)

    client = AnnouncerBot()
    client.run(DISCORD_TOKEN)
