from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import os
import uvicorn
import json
import time
import hmac
import hashlib
from pathlib import Path

app = FastAPI()
RESULTS = {}

# TOP.GG CONFIG
VOTE_FILE = Path("topgg_votes.json")
VOTE_DURATION_SECONDS = 60 * 60 * 12  # 12 hours


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
