import discord
import os
import asyncio

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]

bot = discord.Bot()  # Pycord's bot with slash command support

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}!")
    # Clear all global commands
    await bot.application_commands.clear()  # <- correct in latest Pycord
    print("All slash commands removed!")
    await bot.close()  # Stop the bot after clearing

bot.run(DISCORD_TOKEN)
