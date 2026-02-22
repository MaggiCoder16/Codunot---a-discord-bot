import asyncio
import discord
import os

# Bot token from GitHub Actions secret
TOKEN = os.environ["DISCORD_TOKEN"]

CHANNEL_ID = 1420865735026278550

intents = discord.Intents.default()
intents.message_content = True
intents.dm_messages = True
intents.guilds = True

client = discord.Client(intents=intents)

@client.event
async def on_ready():
    try:
        print(f"Bot logged in as {client.user}")
        
        try:
            channel = await client.fetch_channel(CHANNEL_ID)
        except discord.Forbidden:
            print(
                "Missing access to the configured channel. "
                "Verify CHANNEL_ID points to a channel the bot can view and that "
                "the bot has 'View Channel' and 'Read Message History' permissions."
            )
            return
        except discord.NotFound:
            print(
                "Configured CHANNEL_ID was not found. "
                "Double-check that the ID is correct and from a server where the bot is present."
            )
            return
        print(f"Found channel: {channel} (Type: {type(channel).__name__})")
        
        # Check if it's a valid channel type (DM or server text channel)
        if not isinstance(channel, (discord.TextChannel, discord.DMChannel)):
            raise RuntimeError(f"Channel is {type(channel).__name__}, not a TextChannel or DMChannel")
        
        deleted = 0
        async for message in channel.history(limit=100):
            # Only delete messages sent by your bot
            if message.author.id == client.user.id:
                try:
                    await message.delete()
                    deleted += 1
                    print(f"Deleted message {deleted}: {message.content[:50]}...")
                    await asyncio.sleep(0.5)  # Avoid rate limits
                except discord.Forbidden:
                    print(f"No permission to delete message")
                except Exception as e:
                    print(f"Error deleting message: {e}")
                
                if deleted >= 2:  # Stop after deleting 2 messages
                    break
        
        print(f"Deleted {deleted} bot messages")
    
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        await client.close()

async def main():
    async with client:
        await client.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
