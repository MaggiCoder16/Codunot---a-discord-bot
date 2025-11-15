# bot.py
"""
Codunot - Fully human-like Discord bot with safe Roast Mode using Gemini AI.
Run: python bot.py

Environment variables:
  DISCORD_TOKEN - Discord bot token
  GEMINI_API_KEY - Gemini API key
"""

import os
import asyncio
import random
from datetime import datetime, timedelta
import discord
from discord import Message
from dotenv import load_dotenv

from memory import add_message_to_memory, add_topic, update_mood
from humanizer import human_delay, humanize, is_roast_trigger, generate_safe_roast, detect_mood
from config import GEMINI_API_KEY, DISCORD_TOKEN
from gemini_client import call_gemini  # your Gemini async call wrapper

load_dotenv()

BOT_NAME = "Codunot"
DEAD_CHANNEL_INTERVAL = 180  # seconds
CONTEXT_LENGTH = 12  # number of recent messages to include in prompt

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)


async def send_human_reply(channel, text: str):
    """Simulate human typing and send message."""
    await asyncio.sleep(human_delay())
    await channel.send(humanize(text))


async def dead_channel_check():
    """Post once in dead channels."""
    while True:
        for channel in client.get_all_channels():
            if isinstance(channel, discord.TextChannel):
                # Here, just post once every interval
                await send_human_reply(channel, "its dead in here... anyone wanna talk?")
        await asyncio.sleep(DEAD_CHANNEL_INTERVAL)


def build_prompt(channel_id, is_roast=False, target_name=None):
    """Build Gemini prompt from memory."""
    recent = []
    # Get recent messages from memory
    # memory.py stores only messages as strings
    # fallback to last 12 messages
    try:
        recent = memory[channel_id]["messages"][-CONTEXT_LENGTH:]
    except KeyError:
        recent = []

    history_text = "\n".join(recent)
    if is_roast and target_name:
        prompt = (
            f"You are Codunot, a witty human friend. "
            f"Write a short, funny, safe roast targeting {target_name}. "
            f"Do NOT attack identity or protected classes. Use slang, emojis, casual tone.\n"
            f"Recent chat:\n{history_text}\n\nGive one playful roast as Codunot:"
        )
    else:
        prompt = (
            f"You are Codunot, a human friend in Discord chat. "
            f"Reply casually, short, playful, with slang and emojis. "
            f"React naturally to jokes, sad moments, or surprise. "
            f"Recent chat:\n{history_text}\n\nReply as Codunot (1 short message):"
        )
    return prompt


@client.event
async def on_ready():
    print(f"[{datetime.utcnow().isoformat()}] Logged in as {client.user} (Codunot)")
    asyncio.create_task(dead_channel_check())


@client.event
async def on_message(message: Message):
    if message.author == client.user or message.author.bot:
        return

    channel_id = str(message.channel.id)
    user_name = message.author.display_name
    msg_text = message.content

    # store message
    add_message_to_memory(channel_id, user_name, msg_text)

    # Decide whether to respond
    respond_chance = 0.2
    if client.user.mentioned_in(message):
        respond_chance = 0.95
    elif len(msg_text) < 40:
        respond_chance = min(0.85, respond_chance + 0.25)

    if random.random() > respond_chance:
        return

    # Handle roast triggers
    if is_roast_trigger(msg_text):
        target = None
        for u in message.mentions:
            if u.display_name.lower() == "ardunot" and random.random() < 0.85:
                target = u.display_name
                break
        if not target:
            target = message.mentions[0].display_name if message.mentions else "you"

        prompt = build_prompt(channel_id, is_roast=True, target_name=target)
        try:
            roast_text = await call_gemini(prompt)
            roast_text = humanize(roast_text)
        except Exception:
            roast_text = generate_safe_roast(target)

        await send_human_reply(message.channel, roast_text)
        add_message_to_memory(channel_id, BOT_NAME, roast_text)
        return

    # General reply
    prompt = build_prompt(channel_id)
    try:
        reply_text = await call_gemini(prompt)
        reply_text = humanize(reply_text)
    except Exception:
        reply_text = random.choice(["lol", "idk bruh", "true", "omg"])

    await send_human_reply(message.channel, reply_text)
    add_message_to_memory(channel_id, BOT_NAME, reply_text)


def run():
    client.run(DISCORD_TOKEN)


if __name__ == "__main__":
    run()
