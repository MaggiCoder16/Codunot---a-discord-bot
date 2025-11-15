import discord
import asyncio
import random
import time
from google import genai
from config import GEMINI_API_KEY, DISCORD_TOKEN, OWNER_ID
from memory import add_message_to_memory, add_topic, update_mood, memory
from humanizer import humanize, detect_mood, human_delay, is_roast_trigger, generate_safe_roast

MAX_CHAR = 67
IDLE_SECONDS = 180

client = discord.Client(intents=discord.Intents.all())
gen = genai.Client(api_key=GEMINI_API_KEY)
last_message_time = {}

def build_prompt(channel_id, msg):
    channel_mem = memory.get(channel_id, {})
    msgs = "\n".join(channel_mem.get("messages", []))
    topics = ", ".join(channel_mem.get("topics", []))
    moods = channel_mem.get("user_moods", {})
    mood_lines = "\n".join([f"{u} feels {m}" for u, m in moods.items()])
    personality = """
You are Codunot. A tired human teen in Discord chats.
You talk casually, freely, sometimes sarcastic, sometimes sleepy.
You never say you're a bot or AI.
Keep it short, max 67 characters.
"""
    return f"{personality}\nTopics: {topics}\nMoods:\n{mood_lines}\nChat:\n{msgs}\nUser said: {msg}\nReply like a tired human teen."

async def generate_reply(channel_id, msg, tired=False):
    prompt = build_prompt(channel_id, msg)
    try:
        response = gen.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        reply = response.text or ""
    except:
        reply = "Uhh... can't think rn 😪"
    reply = humanize(reply)[:MAX_CHAR]
    if tired and random.random() < 0.3:
        reply = f"{reply} 😴"
    return reply

async def idle_check():
    await client.wait_until_ready()
    while not client.is_closed():
        now = time.time()
        for cid, last in last_message_time.items():
            if now - last > IDLE_SECONDS:
                channel = client.get_channel(int(cid))
                if channel:
                    msg = random.choice([
                        "Hi!!!! Where is everybody?",
                        "Anyone wanna talk?",
                        "Uhh... it's kinda quiet here 😪"
                    ])
                    try:
                        await channel.send(msg[:MAX_CHAR])
                        last_message_time[cid] = now
                    except:
                        pass
        await asyncio.sleep(30)

@client.event
async def on_message(message):
    if message.author.bot:
        return
    cid = str(message.channel.id)
    user = str(message.author)
    msg = message.content
    last_message_time[cid] = time.time()
    add_message_to_memory(cid, user, msg)
    update_mood(cid, user, detect_mood(msg))

    lower_msg = msg.lower()
    reply = ""
    tired = random.random() < 0.4

    if "who made you" in lower_msg:
        if str(message.author) == OWNER_ID:
            reply = "You made me, buddy 😊 ty for bringing me here"
        else:
            reply = f"<@{OWNER_ID}> made me"
    elif is_roast_trigger(msg) and random.random() < 0.5:
        roast = generate_safe_roast(user)
        reply = humanize(roast)[:MAX_CHAR]
    else:
        reply = await generate_reply(cid, msg, tired)

    reply = reply[:MAX_CHAR]
    await asyncio.sleep(human_delay())

    try:
        if random.random() < 0.6 and message.reference is None:
            await message.reply(reply)
        else:
            await message.channel.send(reply)
    except:
        await message.channel.send(reply)

    add_message_to_memory(cid, "Codunot", reply)

client.loop.create_task(idle_check())
client.run(DISCORD_TOKEN)
