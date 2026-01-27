import os
import requests

# Get token from environment variable
TOKEN = os.getenv("DISCORD_TOKEN")

# Your new bot bio
bio_text = """**Codunot** is a Discord bot made for fun and utility. It can joke, roast, give serious help, and play chess, with different modes you can switch anytime.
In servers, you must ping @Codunot to use it; pinging is not required in DMs.

**Commands**
`!funmode`
`!roastmode`
`!seriousmode`
`!chessmode`
`!codunot_help` (all about the bot)

**Contact the owner:** `@aarav_2022` for all details, help, and commands.
"""

url = "https://discord.com/api/v9/users/@me"
headers = {
    "Authorization": f"Bot {TOKEN}",
    "Content-Type": "application/json"
}
data = {
    "bio": bio_text
}

response = requests.patch(url, headers=headers, json=data)

if response.status_code == 200:
    print("Bot bio updated successfully!")
else:
    print(f"Failed to update bio: {response.status_code}")
    print(response.text)
