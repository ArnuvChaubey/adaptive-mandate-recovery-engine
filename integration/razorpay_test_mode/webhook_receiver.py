"""Minimal webhook receiver for the Day 2 connectivity spike.

Verifies the X-Razorpay-Signature header (HMAC-SHA256, keyed with RAZORPAY_WEBHOOK_SECRET)
before trusting a payload, then logs it. This is a smoke-test logger, not the real audit
schema -- that's decision_log_schema, built at Milestone 2 (Day 3-4) once the simulator
exists too, so simulated and live events share one format.
"""

import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request

load_dotenv()

app = FastAPI()

LOG_PATH = Path(__file__).parent / "webhook_smoke_test_log.jsonl"


def verify_signature(raw_body: bytes, received_signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, received_signature)


@app.post("/webhook")
async def receive_webhook(request: Request):
    secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(status_code=500, detail="RAZORPAY_WEBHOOK_SECRET not set in .env")

    signature = request.headers.get("X-Razorpay-Signature", "")
    raw_body = await request.body()  # must be the raw body -- do not parse before verifying

    if not verify_signature(raw_body, signature, secret):
        raise HTTPException(status_code=400, detail="signature verification failed")

    payload = json.loads(raw_body)
    record = {
        "received_at": datetime.now(timezone.utc).isoformat(),
        "event": payload.get("event"),
        "signature_verified": True,
        "payload": payload,
    }

    with LOG_PATH.open("a") as f:
        f.write(json.dumps(record) + "\n")

    print(f"[webhook] verified + logged: {record['event']}")
    return {"status": "ok"}


@app.get("/health")
async def health():
    return {"status": "listening"}
