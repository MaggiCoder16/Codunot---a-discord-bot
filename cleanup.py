import asyncio
import discord
import os

# Bot token from GitHub Actions secret
TOKEN = os.environ["DISCORD_TOKEN"]

# Hardcoded DM channel ID
DM_CHANNEL_ID = 1439456449813151764

intents = discord.Intents.default()
intents.message_content = True
intents.dm_messages = True

client = discord.Client(intents=intents)

@client.event
async def on_ready():
    try:
        channel = await client.fetch_channel(DM_CHANNEL_ID)
        if not isinstance(channel, discord.DMChannel):
            raise RuntimeError("Channel is not a DM")

        deleted = 0

        async for message in channel.history(limit=100):
            # Only delete messages sent by your bot
            if message.author.id == client.user.id:
                try:
                    await message.delete()
                    deleted += 1
                except discord.Forbidden:
                    pass

                if deleted >= 10:  # Stop after deleting 45 messages
                    break

        print(f"Deleted {deleted} bot messages")

    finally:
        await client.close()

asyncio.run(client.start(TOKEN))
