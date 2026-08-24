"""Loads Razorpay TEST MODE credentials from .env and constructs an SDK client.

No live API calls happen at import time. Run this file directly for a one-off connectivity
smoke test once you've filled in .env with real test-mode keys.
"""

import os
import sys

from dotenv import load_dotenv
import razorpay

load_dotenv()


def get_client() -> razorpay.Client:
    key_id = os.environ.get("RAZORPAY_KEY_ID")
    key_secret = os.environ.get("RAZORPAY_KEY_SECRET")

    if not key_id or not key_secret:
        raise RuntimeError(
            "RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET missing. Copy .env.example to .env "
            "and fill in your Test Mode keys (Dashboard, toggled to Test Mode -> "
            "Account & Settings -> API Keys)."
        )
    if not key_id.startswith("rzp_test_"):
        raise RuntimeError(
            f"Key ID '{key_id[:12]}...' does not look like a test-mode key "
            "(expected an 'rzp_test_' prefix). Refusing to proceed -- this project "
            "must never touch Live Mode keys."
        )

    return razorpay.Client(auth=(key_id, key_secret))


if __name__ == "__main__":
    client = get_client()
    try:
        # Read-only call, no side effects: lists existing test-mode plans (likely empty on a
        # fresh account). Confirms the key pair actually authenticates.
        result = client.plan.all()
        print(f"Connected OK. {result.get('count', 0)} existing test-mode plan(s) found.")
    except Exception as exc:  # surfaced deliberately broad for a Day 1 smoke test
        print(f"Connection failed: {exc}", file=sys.stderr)
        sys.exit(1)
