import discord
import asyncio
import random
from google import genai
from config import GEMINI_API_KEY, DISCORD_TOKEN
from memory import add_message_to_memory, add_topic, update_mood, memory
from humanizer import humanize, detect_mood, human_delay, is_roast_trigger, generate_safe_roast

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

gen = genai.Client(api_key=GEMINI_API_KEY)

MAX_REPLY_LEN = 67

def build_prompt(channel_id):
    channel_mem = memory.get(channel_id, {})
    msgs = "\n".join(channel_mem.get("messages", []))
    topics = ", ".join(channel_mem.get("topics", []))
    moods = channel_mem.get("user_moods", {})
    mood_lines = "\n".join([f"{u} feels {m}" for u, m in moods.items()])
    personality = """
You are Codunot. A tired human teen in Discord chats.
You talk casually, a bit lazy, sometimes sarcastic.
Use emojis lightly. Keep it short.
Never say you're a bot or AI.
"""
    return f"{personality}\nTopics: {topics}\nMoods:\n{mood_lines}\nChat:\n{msgs}\nReply like a real human teen."

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
        roast = humanize(roast)[:MAX_REPLY_LEN]
        await asyncio.sleep(human_delay())
        await message.reply(roast)
        add_message_to_memory(cid, "Codunot", roast)
        return

    if any(word in msg.lower() for word in ["today", "topic", "talk"]):
        add_topic(cid, msg)

    if random.random() < 0.5:
        prompt = build_prompt(cid)
        response = gen.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        reply = (response.text or "").strip()[:MAX_REPLY_LEN]
        reply = humanize(reply)

        await asyncio.sleep(human_delay())
        await message.reply(reply)
        add_message_to_memory(cid, "Codunot", reply)

client.run(DISCORD_TOKEN)
