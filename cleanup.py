import asyncio
import os

import discord

# Bot token from GitHub Actions secret
TOKEN = os.environ["DISCORD_TOKEN"]

# Optional channel ID override (defaults to previous hardcoded value)
DEFAULT_CHANNEL_ID = 1420865735026278550
raw_channel_id = os.getenv("CHANNEL_ID", str(DEFAULT_CHANNEL_ID)).strip()

try:
    CHANNEL_ID = int(raw_channel_id)
except ValueError:
    CHANNEL_ID = None

intents = discord.Intents.default()
intents.message_content = True
intents.dm_messages = True
intents.guilds = True

client = discord.Client(intents=intents)


@client.event
async def on_ready():
    try:
        print(f"Bot logged in as {client.user}")

        if CHANNEL_ID is None:
            print(
                f"Invalid CHANNEL_ID value: {raw_channel_id!r}. "
                "Set CHANNEL_ID to a numeric channel ID."
            )
            return

        try:
            channel = await client.fetch_channel(CHANNEL_ID)
        except discord.Forbidden:
            print(
                "Cannot access the configured channel. If your bot is being used as an "
                "external app (slash commands without joining the server), this is expected "
                "and cleanup will be skipped."
            )
            return
        except discord.NotFound:
            print(
                "Configured CHANNEL_ID was not found. "
                "Double-check that the ID is correct and from a place this bot can access."
            )
            return

        print(f"Found channel: {channel} (Type: {type(channel).__name__})")

        if not isinstance(channel, (discord.TextChannel, discord.DMChannel)):
            raise RuntimeError(
                f"Channel is {type(channel).__name__}, not a TextChannel or DMChannel"
            )

        deleted = 0
        async for message in channel.history(limit=100):
            if message.author.id == client.user.id:
                try:
                    await message.delete()
                    deleted += 1
                    print(f"Deleted message {deleted}: {message.content[:50]}...")
                    await asyncio.sleep(0.5)  # Avoid rate limits
                except discord.Forbidden:
                    print("No permission to delete message")
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
