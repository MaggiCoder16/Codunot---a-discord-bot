import discord
import random
import asyncio
from config import DISCORD_TOKEN, GEMINI_API_KEY, OWNER_ID
from google import genai

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.guilds = True
intents.members = True

client = discord.Client(intents=intents)
gen = genai.GenAI(api_key=GEMINI_API_KEY)

last_active = {}

async def idle_check():
    await client.wait_until_ready()
    while not client.is_closed():
        for channel in client.get_all_channels():
            if isinstance(channel, discord.TextChannel):
                now = asyncio.get_event_loop().time()
                last = last_active.get(channel.id, now)
                if now - last > 180:  # 3 mins
                    await channel.send("hi!!!! where is everybody? anyone wanna talk?")
                    last_active[channel.id] = now
        await asyncio.sleep(60)

def is_roast(msg):
    roast_keywords = ["stupid", "dumb", "bot", "trash", "useless"]
    return any(word in msg.lower() for word in roast_keywords)

def get_server_context(message):
    guild = message.guild
    admins = [role.name for role in guild.roles if role.permissions.administrator]
    mods = [role.name for role in guild.roles if role.permissions.kick_members or role.permissions.ban_members]
    context = f"server name - {guild.name}\ncreator - @Realboy9000\nadmins - {', '.join(admins)}\nmods - {', '.join(mods)}"
    return context

@client.event
async def on_message(message):
    if message.author.bot:
        return

    last_active[message.channel.id] = asyncio.get_event_loop().time()
    content = message.content.lower()
    reply = ""

    if "who made you" in content:
        if str(message.author.id) == OWNER_ID:
            reply = "you made me, buddy. ty for making me enter this world"
        else:
            reply = f"<@{OWNER_ID}> made me"
    elif is_roast(content):
        roast_lines = [
            "lol u tryna roast me? pls, try harder 😏",
            "ha, weak roast. I expected more",
            "bro, ur brain got lagged mid-roast? 😂",
        ]
        reply = random.choice(roast_lines)
    else:
        server_context = get_server_context(message)
        prompts = [
            f"server context: {server_context}\nfull energetic response, 67 chars max",
            f"server context: {server_context}\ncasual witty reply, short and coherent"
        ]
        try:
            resp = gen.models.generate_content(
                model="gemini-2.5",
                prompt=random.choice(prompts) + f"\nUser: {message.content}\nBot:",
                temperature=0.7,
                max_output_tokens=50
            )
            reply = resp.output_text.strip()[:67]
        except:
            reply = "uhh idk what to say 😅"

    if reply:
        try:
            if random.random() < 0.5:
                await message.reply(reply)
            else:
                await message.channel.send(reply)
        except:
            pass

client.loop.create_task(idle_check())
client.run(DISCORD_TOKEN)
