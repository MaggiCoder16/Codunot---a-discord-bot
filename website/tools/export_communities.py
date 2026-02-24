"""Export bot guilds to website/communities.json using Discord API.

Usage:
  set DISCORD_BOT_TOKEN=...   (Windows)
  python website/tools/export_communities.py

Optional:
  set COMMUNITY_INVITES_JSON={"123":"https://discord.gg/abc"}
"""

import json
import os
from urllib.request import Request, urlopen

BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise SystemExit("Missing DISCORD_BOT_TOKEN environment variable.")

invites_raw = os.getenv("COMMUNITY_INVITES_JSON", "{}").strip()
invites_map = json.loads(invites_raw) if invites_raw else {}

req = Request(
    "https://discord.com/api/v10/users/@me/guilds",
    headers={"Authorization": f"Bot {BOT_TOKEN}"},
)

with urlopen(req, timeout=20) as resp:
    guilds = json.loads(resp.read().decode("utf-8"))

output = []
for g in guilds:
    gid = str(g.get("id", ""))
    icon_hash = g.get("icon")
    if icon_hash:
        icon = f"https://cdn.discordapp.com/icons/{gid}/{icon_hash}.png?size=128"
    else:
        icon = "https://cdn.top.gg/icons/799571124189618176/041c2d0d7f2919cb19e56f2e1f8a0d79e7dc9940f870adf07feab99dd3ce0a04.webp"

    output.append(
        {
            "id": gid,
            "name": g.get("name", "Unknown Server"),
            "members": "Members hidden",
            "icon": icon,
            "invite": invites_map.get(gid, "https://discord.gg/GVuFk5gxtW"),
        }
    )

with open("website/communities.json", "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2)

print(f"Exported {len(output)} communities to website/communities.json")
