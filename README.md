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
- Optional fallback if Spotify blocks anonymous access in your region:
  - `SPOTIFY_ACCESS_TOKEN` (Bearer token), or
  - `SPOTIFY_CLIENT_ID` + `SPOTIFY_CLIENT_SECRET` (client credentials flow).
- How to get Spotify credentials:
  - Go to **https://developer.spotify.com/dashboard** and create an app.
  - Copy **Client ID** and **Client Secret** into `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET`.
  - If you already have a valid short-lived bearer token, you can set `SPOTIFY_ACCESS_TOKEN` instead.
- Manual requirements:
  - Use **public** Spotify track/playlist links.
  - Keep bot voice dependencies working (`ffmpeg`, `discord.py[voice]`, `yt_dlp`).
  - If source sites rate-limit/age-gate some tracks, provide cookies via `YTDL_COOKIE_CONTENT` (code env), or `YTDL_COOKIES_CONTENT` in GitHub Actions workflow (written to `YTDL_COOKIES_TXT` path).

## 🔐 Secrets / environment variables

> **TL;DR — You only need two secrets to run the bot: `DISCORD_TOKEN` and `GROQ_API_KEY`.**  
> Everything else is optional and only needed for specific features.

### GitHub Actions

Set secrets in: **GitHub repo → Settings → Secrets and variables → Actions → New repository secret**.

| Secret | Required? | Where to get it |
|--------|-----------|-----------------|
| `DISCORD_TOKEN` | **Yes** | **Discord Developer Portal** → Your App → **Bot** → *Reset Token* / copy token |
| `GROQ_API_KEY` | **Yes** | **Groq Console** → API Keys |
| `DEAPI_API_KEY` | No | **deAPI.ai** account/API dashboard (image/video/transcription features) |
| `TEST_API_KEY` | No | Image generation API provider configured in `test_api.py` |
| `HUGGINGFACE_API_KEY_IMAGE_GEN` | No | **Hugging Face** → Settings → Access Tokens |
| `REPLICATE_API_TOKEN` | No | **Replicate** → Account → API tokens |
| `GEMINI_API_KEY` | No | **Google AI Studio** (also accepts `GOOGLE_AI_STUDIO_API_KEY`) |
| `TOPGG_TOKEN` | No | **top.gg** bot page (vote checks) |
| `TOPGG_WEBHOOK_AUTH` | No | Same value configured in top.gg webhook settings |
| `YTDL_COOKIES_CONTENT` | No | Netscape cookie-jar text (helps bypass age-gated content) |
| `LAVALINK_HOST` | **No** | Hostname of a Lavalink server. **You do not need this** — leave empty and music plays via yt-dlp |
| `LAVALINK_PORT` | **No** | Lavalink port (defaults to `443`). Only needed if you set `LAVALINK_HOST` |
| `LAVALINK_PASSWORD` | **No** | Lavalink password. Only needed if you set `LAVALINK_HOST` |
| `LAVALINK_SECURE` | **No** | `true` for HTTPS, `false` for HTTP (defaults to `true`). Only needed if you set `LAVALINK_HOST` |

### Running locally

Set at least `DISCORD_TOKEN` and `GROQ_API_KEY` as environment variables before running:

```bash
export DISCORD_TOKEN="your-token-here"
export GROQ_API_KEY="your-key-here"
python groq_bot.py
```

For local runs the code also supports `YTDL_COOKIE_CONTENT` (instead of `YTDL_COOKIES_CONTENT` used in GitHub Actions).

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
