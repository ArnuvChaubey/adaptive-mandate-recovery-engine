"""Fallback for the Day 2 spike: a plain one-time Payment Link instead of a Subscription.

Subscriptions mandatorily tokenize the card (RBI CoFT), which routes through an OTP/login
flow that's proven unreliable to drive manually in test mode. A one-time payment doesn't
require saving a card, so it should hit the simple mock bank Success/Failure page instead.
This still produces a real payment.captured/payment.failed webhook -- sufficient to prove
the tunnel + signature verification + logging mechanism end to end.

Run: python -m integration.razorpay_test_mode.create_test_payment_link
"""

from integration.razorpay_test_mode.client import get_client


def main():
    client = get_client()

    link = client.payment_link.create({
        "amount": 10000,  # paise -> INR 100.00
        "currency": "INR",
        "description": "Day 2 webhook connectivity spike -- one-time, not a real product",
        "customer": {
            "name": "Test Customer",
            "email": "test.customer@example.com",
            "contact": "+919123456789",
        },
        "notify": {"sms": False, "email": False},
        "notes": {
            "project": "adaptive-mandate-recovery-engine",
            "purpose": "day2-webhook-spike-fallback",
        },
    })
    print(f"Created payment link: {link['id']}")
    print(f"Pay at: {link['short_url']}")


if __name__ == "__main__":
    main()
