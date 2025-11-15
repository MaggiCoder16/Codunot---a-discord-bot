import discord
import asyncio
import time
from config import GEMINI_API_KEY, DISCORD_TOKEN, OWNER_ID
from google.genai import models

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.members = True

client = discord.Client(intents=intents)

last_message_time = {}
IDLE_SECONDS = 180

async def generate_dynamic_reply(prompt: str) -> str:
    prompt = (
        f"Server name - RoyalRacer Fans\n"
        f"Creator - @Realboy9000\n"
        f"Admins & Mods - see from roles\n"
        f"Message: {prompt}\n"
        f"Bot should respond naturally, sometimes roast back if insulted, sometimes just talk. "
        f"Max 67 chars."
    )
    try:
        response = models.TextGenerationModel().generate(
            model="gemini-2.5-flash",
            prompt=prompt,
            temperature=0.7,
            max_output_tokens=30
        )
        return response.output_text[:67]
    except Exception:
        return "ugh nvm I don't like it 😑"

async def send_reply(message, content):
    if random.random() < 0.6:
        await message.reply(content)
    else:
        await message.channel.send(content)

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")

@client.event
async def on_message(message):
    global last_message_time
    if message.author == client.user:
        return
    last_message_time[message.channel.id] = time.time()
    lower = message.content.lower()
    reply = ""
    if "who made you" in lower:
        if message.author.id == OWNER_ID:
            reply = "You made me, buddy. Ty for creating me 🙏"
        else:
            reply = f"<@{OWNER_ID}> made me 😎"
    else:
        reply = await generate_dynamic_reply(message.content)
    if reply:
        await send_reply(message, reply)

async def idle_check():
    await client.wait_until_ready()
    while not client.is_closed():
        now = time.time()
        for channel in client.get_all_channels():
            if isinstance(channel, discord.TextChannel):
                last = last_message_time.get(channel.id, now)
                if now - last > IDLE_SECONDS:
                    await channel.send("Hi!!!! Where is everybody? Anyone wanna talk?")
                    last_message_time[channel.id] = now
        await asyncio.sleep(10)

async def runner():
    await asyncio.gather(client.start(DISCORD_TOKEN), idle_check())

asyncio.run(runner())
