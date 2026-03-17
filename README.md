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

- Spotify tracks and playlists are played via **Lavalink** — set `LAVALINK_HOST`, `LAVALINK_PORT`, `LAVALINK_PASSWORD`, and `LAVALINK_SECURE`.
- YouTube and other sources are played via **yt-dlp** (no Lavalink needed).
- If Lavalink is not configured, Spotify links will show an error — everything else still works.
- Manual requirements:
  - A running **Lavalink server** with a Spotify plugin (e.g. [LavaSrc](https://github.com/topi314/LavaSrc)).
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
| `LAVALINK_HOST` | No | Hostname of a Lavalink server. **Required for Spotify** playback |
| `LAVALINK_PORT` | No | Lavalink port (defaults to `443`). Only set if you use Lavalink |
| `LAVALINK_PASSWORD` | No | Lavalink password. **Required for Spotify** playback |
| `LAVALINK_SECURE` | No | `true` for HTTPS, `false` for HTTP (defaults to `true`). Only set if you use Lavalink |

### Running locally

Set at least `DISCORD_TOKEN` and `GROQ_API_KEY` as environment variables before running:

```bash
export DISCORD_TOKEN="your-token-here"
export GROQ_API_KEY="your-key-here"
python groq_bot.py
```

For local runs the code also supports `YTDL_COOKIE_CONTENT` (instead of `YTDL_COOKIES_CONTENT` used in GitHub Actions).

### Why `mod_data.json` looks like `gAAAAA...` instead of JSON

This is expected. Moderation data is encrypted with **Fernet** before being saved.

- `mod_commands.py` saves/loads moderation data via `save_encrypted(...)` and `load_encrypted(...)`.
- `encryption.py` uses your `ENCRYPTION_KEY` to encrypt on write and decrypt on read.
- Fernet tokens usually begin with `gAAAAA...`, so the file will not be human-readable plain JSON.

If you open `mod_data.json` directly, you'll see ciphertext. The bot decrypts it automatically at runtime.

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
