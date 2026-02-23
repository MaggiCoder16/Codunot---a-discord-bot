from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import os
import uvicorn
import json
import time
import hmac
import hashlib
import httpx
from pathlib import Path

app = FastAPI()
RESULTS = {}

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()

VOTE_FILE = Path("topgg_votes.json")
VOTE_DURATION_SECONDS = 60 * 60 * 12

PENDING_TRANSCRIPTIONS: dict[str, dict] = {}

def load_votes():
    if not VOTE_FILE.exists():
        return {}
    try:
        with VOTE_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_votes(data):
    with VOTE_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f)


async def send_discord_message(channel_id: int, content: str):
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers = {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
        "Content-Type": "application/json",
    }
    chunks = []
    while content:
        if len(content) <= 2000:
            chunks.append(content)
            break
        split_at = content.rfind("\n", 0, 2000)
        if split_at <= 0:
            split_at = content.rfind(" ", 0, 2000)
        if split_at <= 0:
            split_at = 2000
        chunks.append(content[:split_at])
        content = content[split_at:].lstrip()

    async with httpx.AsyncClient() as client:
        for chunk in chunks:
            await client.post(url, headers=headers, json={"content": chunk})


async def send_discord_dm(user_id: int, content: str):
    headers = {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient() as client:
        dm_resp = await client.post(
            "https://discord.com/api/v10/users/@me/channels",
            headers=headers,
            json={"recipient_id": str(user_id)},
        )
        if dm_resp.status_code >= 300:
            print(f"[Webhook] Failed to create DM channel for user {user_id}: {dm_resp.status_code}")
            return

        dm_channel_id = dm_resp.json().get("id")
        if not dm_channel_id:
            print(f"[Webhook] DM channel missing for user {user_id}")
            return

        await send_discord_message(int(dm_channel_id), content)


@app.post("/register-transcription")
async def register_transcription(req: Request):
    body = await req.json()
    request_id = body.get("request_id")
    channel_id = body.get("channel_id")
    user_id = body.get("user_id")
    deliver_in_dm = bool(body.get("deliver_in_dm", False))
    if request_id and channel_id:
        PENDING_TRANSCRIPTIONS[request_id] = {
            "channel_id": int(channel_id),
            "user_id": int(user_id) if user_id else None,
            "deliver_in_dm": deliver_in_dm,
        }
        print(f"[Register] request_id={request_id} → channel_id={channel_id} dm={deliver_in_dm}")
    return {"status": "ok"}


@app.post("/webhook")
async def deapi_webhook(req: Request):
    payload = await req.json()
    event_type = payload.get("event", "unknown")
    data = payload.get("data", {})
    request_id = data.get("job_request_id")

    print(f"[Webhook] {event_type} | request_id={request_id}")

    if event_type == "job.processing":
        return JSONResponse(status_code=200, content={"status": "ack"})

    if event_type == "job.completed" or "result_url" in data or "transcription" in data or "text" in data:
        if request_id:
            RESULTS[request_id] = data
            print(f"[Webhook] Completed: {request_id}")

            transcript = (
                data.get("transcription")
                or data.get("transcript")
                or data.get("text")
            )

            delivery = PENDING_TRANSCRIPTIONS.pop(request_id, None)
            if delivery and transcript and DISCORD_BOT_TOKEN:
                channel_id = delivery.get("channel_id")
                user_id = delivery.get("user_id")
                deliver_in_dm = bool(delivery.get("deliver_in_dm"))

                if deliver_in_dm and user_id:
                    print(f"[Webhook] Sending transcript to user DM {user_id}")
                    await send_discord_dm(user_id, f"✅ **Transcription complete:**\n{transcript}")
                elif channel_id:
                    print(f"[Webhook] Sending transcript to channel {channel_id}")
                    await send_discord_message(channel_id, f"✅ **Transcription complete:**\n{transcript}")
            elif delivery and not transcript:
                channel_id = delivery.get("channel_id")
                user_id = delivery.get("user_id")
                deliver_in_dm = bool(delivery.get("deliver_in_dm"))
                if deliver_in_dm and user_id:
                    await send_discord_dm(user_id, "⚠️ Transcription completed but returned empty text.")
                elif channel_id:
                    await send_discord_message(channel_id, "⚠️ Transcription completed but returned empty text.")

            return JSONResponse(status_code=200, content={"status": "ok"})

    return JSONResponse(status_code=200, content={"status": "ack"})


@app.post("/topgg-webhook")
async def topgg_webhook(req: Request):
    secret = os.getenv("TOPGG_WEBHOOK_AUTH")
    signature_header = req.headers.get("x-topgg-signature")
    if not secret:
        return JSONResponse(status_code=500, content={"error": "Webhook secret not configured"})
    if not signature_header:
        return JSONResponse(status_code=401, content={"error": "Missing signature header"})
    try:
        parts = dict(item.split("=") for item in signature_header.split(","))
        timestamp = parts.get("t")
        signature = parts.get("v1")
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid signature format"})
    if not timestamp or not signature:
        return JSONResponse(status_code=400, content={"error": "Malformed signature header"})

    raw_body = await req.body()
    message = f"{timestamp}.".encode() + raw_body
    expected_signature = hmac.new(
        secret.encode(),
        message,
        hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected_signature, signature):
        return JSONResponse(status_code=401, content={"error": "Invalid signature"})

    payload = json.loads(raw_body)
    event_type = payload.get("type")
    if event_type == "vote.create":
        user_id = payload["data"]["user"]["platform_id"]
        votes = load_votes()
        votes[str(user_id)] = int(time.time() + VOTE_DURATION_SECONDS)
        save_votes(votes)
        print(f"[Top.gg] Vote received for user {user_id}")
    elif event_type == "webhook.test":
        print("[Top.gg] Webhook test received")

    return {"status": "ok"}


@app.get("/result/{request_id}")
async def get_result(request_id: str):
    if request_id in RESULTS:
        return {"status": "done", "data": RESULTS[request_id]}
    return {"status": "pending"}


@app.get("/")
async def root():
    return {"status": "running"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
