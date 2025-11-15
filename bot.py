import discord  
import asyncio  
import random  
import time  
from google.genai import Client as GenAIClient  
from config import GEMINI_API_KEY, DISCORD_TOKEN, OWNER_ID  

intents = discord.Intents.default()  
intents.message_content = True  
client = discord.Client(intents=intents)  
gen = GenAIClient(api_key=GEMINI_API_KEY)  

last_activity = {}  
IDLE_TIMEOUT = 180  
MAX_LEN = 80  

async def idle_loop():  
    await client.wait_until_ready()  
    while not client.is_closed():  
        now = time.time()  
        for cid, ts in list(last_activity.items()):  
            if now - ts > IDLE_TIMEOUT:  
                ch = client.get_channel(int(cid))  
                if isinstance(ch, discord.TextChannel):  
                    await ch.send("It's dead in here... anyone wanna talk?")  
                    last_activity[cid] = now  
        await asyncio.sleep(20)  

def build_prompt(msg_content):  
    return (  
        f"server name - RoyalRacer Fans\n"  
        f"creator - @Realboy9000\n"  
        f"bot creator - @aarav-2022\n"  
        f"Message: {msg_content}\n"  
        "If someone insults me, roast them hard, especially @Ardunot. "  
        "Sometimes I start roasting him too. Otherwise reply energetic or tired. "  
        "Max 67 characters."  
    )  

async def gen_reply(msg_content):  
    prompt = build_prompt(msg_content)  
    try:  
        def call():  
            return gen.models.generate_content(  
                model="gemini-2.5-flash",  
                contents=prompt  
            ).text or ""  
        text = await asyncio.wait_for(asyncio.to_thread(call), timeout=5)  
    except:  
        text = "ugh, can't brain rn 😑"  
    return text.strip()[:MAX_LEN]  

@client.event  
async def on_message(message):  
    if message.author.bot:  
        return  
    last_activity[message.channel.id] = time.time()  
    lower = message.content.lower()  
    reply = None  

    if "who made you" in lower:  
        if message.author.id == OWNER_ID:  
            reply = "You made me, buddy. Ty for making me real 😎"  
        else:  
            reply = f"<@{OWNER_ID}> made me"  
    else:  
        reply = await gen_reply(message.content)  

    await message.channel.send(reply)  

async def main():  
    await asyncio.gather(client.start(DISCORD_TOKEN), idle_loop())  

asyncio.run(main())  
