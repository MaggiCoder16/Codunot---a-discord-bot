import os
import discord
from discord.ext import commands

# Get your token from environment
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    raise ValueError("DISCORD_TOKEN is missing! Set it in your environment or GitHub Secrets.")

# Create bot (Discord.py 2.x style)
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)  # command_prefix is required, even if unused

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}!")

    # Clear all global slash commands
    await bot.tree.clear_commands()
    print("Cleared all global slash commands across all servers!")

    await bot.close()

bot.run(DISCORD_TOKEN)
