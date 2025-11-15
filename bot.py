import discord
import asyncio
from google import genai
from config import GEMINI_API_KEY, DISCORD_TOKEN
from memory import add_message_to_memory, add_topic, update_mood, memory
from humanizer import humanize, detect_mood, human_delay, is_roast_trigger, generate_safe_roast
import random

client = discord.Client(intents=discord.Intents.all())
gen = genai.Client(api_key=GEMINI_API_KEY)
MAX_CHAR = 67
OWNER_ID = "aarav-2022"

def build_prompt(channel_id):
    channel_mem = memory.get(channel_id, {})
    msgs = "\n".join(channel_mem.get("messages", []))
    topics = ", ".join(channel_mem.get("topics", []))
    moods = channel_mem.get("user_moods", {})
    mood_lines = "\n".join([f"{u} feels {m}" for u, m in moods.items()])
    personality = """
You are Codunot. A human teen, casual, short, not always GenZ slang.
Talk tired but interested, short messages max 67 chars.
Never say you're AI.
"""
    return f"{personality}\nTopics: {topics}\nMoods:\n{mood_lines}\nChat:\n{msgs}\nReply like a human teen."

@client.event
async def on_message(message):
    if message.author.bot:
        return

    cid = str(message.channel.id)
    user = str(message.author)
    msg = message.content

    add_message_to_memory(cid, user, msg)
    update_mood(cid, user, detect_mood(msg))

    if is_roast_trigger(msg):
        roast = generate_safe_roast(user)
        roast = humanize(roast)[:MAX_CHAR]
        await asyncio.sleep(human_delay())
        await message.channel.send(roast)
        add_message_to_memory(cid, "Codunot", roast)
        return

    if any(word in msg.lower() for word in ["today", "topic", "talk"]):
        add_topic(cid, msg)

    lower_msg = msg.lower()
    reply = ""
    if "who made you" in lower_msg:
        if str(message.author) == OWNER_ID:
            reply = "You made me, buddy. Ty for making me enter this world"
        else:
            reply = f"<@{OWNER_ID}> made me"
    else:
        prompt = build_prompt(cid)
        try:
            response = gen.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt
            )
            reply = (response.text or "").strip()
        except:
            reply = "uuhh idk lol"
    
    reply = humanize(reply)[:MAX_CHAR]

    await asyncio.sleep(human_delay())
    try:
        if random.random() < 0.6 and message.reference is None:
            await message.reply(reply)
        else:
            await message.channel.send(reply)
    except:
        await message.channel.send(reply)

    add_message_to_memory(cid, "Codunot", reply)

client.run(DISCORD_TOKEN)
