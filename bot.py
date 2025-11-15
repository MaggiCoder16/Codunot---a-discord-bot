import discord
import asyncio
import random
from google.genai import Client as GenAIClient
from config import GEMINI_API_KEY, DISCORD_TOKEN, OWNER_ID

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.guilds = True

client = discord.Client(intents=intents)
gen = GenAIClient(api_key=GEMINI_API_KEY)

SERVER_NAME = "RoyalRacer Fans"
CREATOR = "@Realboy9000"

last_activity = {}

async def idle_check():
    await client.wait_until_ready()
    while not client.is_closed():
        now = asyncio.get_event_loop().time()
        for channel_id, last_time in list(last_activity.items()):
            if now - last_time > 180:
                channel = client.get_channel(channel_id)
                if channel:
                    await channel.send("hi!!!! where is everybody? anyone wanna talk?")
                    last_activity[channel_id] = now
        await asyncio.sleep(30)

def create_prompt(user_name, msg_content):
    return f"""
Server name: {SERVER_NAME}
Creator: {CREATOR}
User: {user_name}
Message: {msg_content}
Admins: see from roles
Mods: see from roles
Respond like a bot that is mostly energetic, sometimes tired, always keeps the conversation, roasts back if roasted, sometimes starts roasting, short replies max 67 chars.
"""

async def generate_reply(user_name, msg_content):
    prompt = create_prompt(user_name, msg_content)
    try:
        response = gen.responses.create(
            model="gemini-2.5-flash",
            input=prompt,
            max_output_tokens=50
        )
        reply = response.output_text.strip()
        return reply if reply else "..."
    except:
        return "huh?"

@client.event
async def on_ready():
    print(f"{client.user} connected to Discord!")

@client.event
async def on_message(message):
    if message.author == client.user:
        return
    last_activity[message.channel.id] = asyncio.get_event_loop().time()
    lower = message.content.lower()
    if "who made you" in lower:
        reply = f"<@{OWNER_ID}> made me, buddy. ty for bringing me to this world!"
        await message.reply(reply)
        return
    chance = random.random()
    if chance < 0.7:
        try:
            await message.reply(await generate_reply(message.author.display_name, message.content))
        except:
            await message.channel.send(await generate_reply(message.author.display_name, message.content))
    else:
        await message.channel.send(await generate_reply(message.author.display_name, message.content))

async def main():
    await client.start(DISCORD_TOKEN)

asyncio.run(asyncio.gather(main(), idle_check()))
