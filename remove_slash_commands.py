import discord
import asyncio
import os

TOKEN = os.getenv("DISCORD_TOKEN")  # from GitHub Secrets

intents = discord.Intents.default()
bot = discord.Bot(intents=intents)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")

    # Remove all global slash commands
    await bot.tree.clear_commands(guild=None)
    await bot.tree.sync()
    print("✅ All global slash commands removed")

    await bot.close()

bot.run(TOKEN)
