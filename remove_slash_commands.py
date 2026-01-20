import os
import discord

# Get Discord token
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    raise ValueError("DISCORD_TOKEN is missing! Set it in your environment or GitHub Secrets.")

intents = discord.Intents.default()
bot = discord.Bot(intents=intents)  # Discord.py 2.0 bot

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}!")

    # Clear all global slash commands (affects all servers)
    await bot.tree.clear_commands()
    print("Cleared all global slash commands across all servers!")

    # Stop the bot
    await bot.close()

bot.run(DISCORD_TOKEN)
