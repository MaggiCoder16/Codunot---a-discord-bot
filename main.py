from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import os
import uvicorn

app = FastAPI()
RESULTS = {}

@app.post("/webhook")
async def deapi_webhook(req: Request):
    """
    Receives webhook callbacks from deAPI when image generation completes
    Handles both 'job.processing' and 'job.completed' events
    """
    payload = await req.json()
    
    # Get event type
    event_type = payload.get("event", "unknown")
    data = payload.get("data", {})
    request_id = data.get("job_request_id")
    
    print(f"[Webhook] 📨 Received event: {event_type} for request_id={request_id}")
    
    # Handle job.processing event
    if event_type == "job.processing":
        status = data.get("status")
        print(f"[Webhook] ⏳ Job {request_id} is {status}")
        return JSONResponse(status_code=200, content={"status": "acknowledged"})
    
    # Handle job.completed event (or fallback to old format)
    if event_type == "job.completed" or "result_url" in data:
        result_url = data.get("result_url")
        
        if request_id and result_url:
            RESULTS[request_id] = result_url
            print(f"[Webhook] ✅ Job completed for request_id={request_id}")
            print(f"[Webhook] 🖼️  Image URL: {result_url}")
            return JSONResponse(status_code=200, content={"status": "ok"})
    
    # Unknown or incomplete payload
    print(f"[Webhook] ⚠️  Unhandled event or missing data: {payload}")
    return JSONResponse(status_code=200, content={"status": "acknowledged"})

@app.get("/result/{request_id}")
async def get_result(request_id: str):
    """
    Poll endpoint - returns image URL when ready
    """
    if request_id in RESULTS:
        print(f"[Result] ✅ Serving result for {request_id}")
        return {"status": "done", "result_url": RESULTS[request_id]}
    
    print(f"[Result] ⏳ Pending for {request_id}")
    return {"status": "pending"}

@app.get("/")
async def root():
    """
    Health check endpoint
    """
    return {
        "status": "running",
        "service": "deAPI Webhook Server",
        "endpoints": {
            "webhook": "/webhook (POST)",
            "result": "/result/{request_id} (GET)",
            "health": "/ (GET)"
        },
        "active_results": len(RESULTS)
    }

@app.head("/")
async def root_head():
    """
    Handle HEAD requests for health checks
    """
    return JSONResponse(status_code=200, content={})

@app.get("/health")
async def health():
    """
    Additional health check endpoint
    """
    return {"status": "healthy", "active_results": len(RESULTS)}

# Handle invalid methods on webhook endpoint
@app.get("/webhook")
async def webhook_get():
    return JSONResponse(
        status_code=405,
        content={"detail": "Method not allowed. Use POST for this endpoint."}
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"🚀 Starting webhook server on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
