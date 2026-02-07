from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import os
import uvicorn

app = FastAPI()

RESULTS = {}

@app.post("/webhook")
async def deapi_webhook(req: Request):
    payload = await req.json()
    data = payload.get("data", {})

    request_id = data.get("job_request_id")
    result_url = data.get("result_url")

    if request_id and result_url:
        RESULTS[request_id] = result_url
        print(f"[Webhook] Received result for request_id={request_id}")
    else:
        print("[Webhook] Invalid payload received:", payload)

    return JSONResponse(status_code=200, content={"status": "ok"})

@app.get("/result/{request_id}")
async def get_result(request_id: str):
    if request_id in RESULTS:
        return {"status": "done", "result_url": RESULTS[request_id]}
    return {"status": "pending"}

@app.get("/")
async def root():
    return {"status": "Webhook server is running!"}

@app.get("/webhook")
async def webhook_get():
    return JSONResponse(
        status_code=405,
        content={"detail": "Use POST for this endpoint"}
    )

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
