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

## 🔐 GitHub Secrets to set (and where to get them)

Set secrets in: **GitHub repo → Settings → Secrets and variables → Actions → New repository secret**.

### Minimum needed to run the advanced bot workflow

- `DISCORD_TOKEN`  
  Get from **Discord Developer Portal** → Your App → **Bot** → *Reset Token* / copy token.
- `GROQ_API_KEY`  
  Get from **Groq Console** → API Keys.

### Common optional secrets (feature-based)

- `DEAPI_API_KEY`  
  Get from your **deAPI.ai** account/API dashboard (used for image/video/transcription features).
- `TEST_API_KEY`  
  Get from the image generation API provider you configured for `test_api.py` (`imggen-api-production.up.railway.app` in this repo).
- `HUGGINGFACE_API_KEY_IMAGE_GEN`  
  Get from **Hugging Face** → Settings → Access Tokens.
- `REPLICATE_API_TOKEN`  
  Get from **Replicate** → Account → API tokens.
- `GEMINI_API_KEY` (or `GOOGLE_AI_STUDIO_API_KEY`)  
  Get from **Google AI Studio**.
- `TOPGG_TOKEN`  
  Get from **top.gg** bot page (used for vote checks).
- `TOPGG_WEBHOOK_AUTH`  
  Set this to the same webhook auth value configured in top.gg webhook settings (if using webhook route).
- `YTDL_COOKIES_CONTENT`  
  Use this exact secret name in GitHub Actions. The workflow writes it to `cookies.txt` and passes the path as `YTDL_COOKIES_TXT`.

### Notes

- If you only need basic bot startup, start with `DISCORD_TOKEN` + `GROQ_API_KEY`.
- Add other secrets only for the features you use.
- For local runs (not GitHub Actions), the code also supports `YTDL_COOKIE_CONTENT` directly.

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
