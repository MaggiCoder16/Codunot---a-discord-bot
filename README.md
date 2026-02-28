# 🤖 Codunot — AI That Lives Inside Discord

> Built by a 13-year-old developer.

## 🌐 Website

The full website is in `website/` with these pages:

- `index.html` — Hero, uptime, top.gg widget, communities strip, fun command highlights
- `features.html` — Full feature explanations + how to use modes
- `commands.html` — Human-language command center
- `stats.html` — Uptime/stats + top.gg widget
- `reviews.html` — User feedback section
- `roadmap.html` — Planned next features
- `changelog.html` — Recent updates
- `faq.html` — Practical usage answers
- `support.html` — Owner contact and quick links

## ▶️ Run locally

```bash
cd website
python -m http.server 8080
```

Open: `http://localhost:8080/index.html`

## 🎵 Spotify support notes

- You **do not need a Spotify API key** for `/play` Spotify links in this bot.
- Spotify links are resolved through `yt-dlp` metadata and then searched on playable sources.
- Manual requirements:
  - Use **public** Spotify track/playlist links.
  - Keep bot voice dependencies working (`ffmpeg`, `discord.py[voice]`, `yt_dlp`).
  - If source sites rate-limit/age-gate some tracks, provide cookies via `YTDL_COOKIE_CONTENT` or `YTDL_COOKIES_TXT`.

## 🧩 Communities data (Discord API export)

To refresh `website/communities.json` from the Discord API:

```bash
# Windows CMD
set DISCORD_BOT_TOKEN=YOUR_BOT_TOKEN
python website\tools\export_communities.py
```

Optional invite mapping:

```bash
set COMMUNITY_INVITES_JSON={"GUILD_ID":"https://discord.gg/yourinvite"}
```

## 🔗 Core links

- Add to Server: https://discord.com/oauth2/authorize?client_id=1435987186502733878&permissions=277025643520&integration_type=0&scope=applications.commands+bot
- Add as App/Login: https://discord.com/oauth2/authorize?client_id=1435987186502733878&integration_type=1&scope=applications.commands
- Vote: https://top.gg/bot/1435987186502733878/vote
- Official Discord: https://discord.gg/GVuFk5gxtW
