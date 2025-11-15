import discord
import asyncio
from google import genai
from config import GEMINI_API_KEY, DISCORD_TOKEN
from memory import add_message_to_memory, add_topic, update_mood, memory
from humanizer import humanize, detect_mood, human_delay, is_roast_trigger, generate_safe_roast

client = discord.Client(intents=discord.Intents.all())
gen = genai.Client(api_key=GEMINI_API_KEY)

def build_prompt(channel_id):
    channel_mem = memory.get(channel_id, {})
    msgs = "\n".join(channel_mem.get("messages", []))
    topics = ", ".join(channel_mem.get("topics", []))
    moods = channel_mem.get("user_moods", {})
    mood_lines = "\n".join([f"{u} feels {m}" for u, m in moods.items()])
    personality = """
You are Codunot. A normal human teen in Discord chats.
You talk casually, freely, without being mentioned.
You use emojis, typos, slang, sarcasm, randomness.
You never say you're a bot or AI.
Stay natural and messy like a real human.
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
        roast = humanize(roast)
        await asyncio.sleep(human_delay())
        await message.channel.send(roast)
        add_message_to_memory(cid, "Codunot", roast)
        return

    if any(word in msg.lower() for word in ["today", "topic", "talk"]):
        add_topic(cid, msg)

    prompt = build_prompt(cid)

    response = gen.models.generate_content(
        model="gemini-1.5-flash-latest",
        contents=prompt
    )

    reply = response.text or ""
    reply = reply.strip()
    reply = humanize(reply)

    await asyncio.sleep(human_delay())
    await message.channel.send(reply)
    add_message_to_memory(cid, "Codunot", reply)

client.run(DISCORD_TOKEN)
