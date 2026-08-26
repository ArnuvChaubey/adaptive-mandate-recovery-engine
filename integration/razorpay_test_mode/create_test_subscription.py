"""Day 2 spike: scripted creation of a test Plan -> Customer -> Subscription.

This is the seed process M1/M6 both depend on -- it must be scriptable and repeatable, not a
one-off manual dashboard click-through, per the 3-day test-mode token window constraint.

Run: python -m integration.razorpay_test_mode.create_test_subscription
"""

import time

from integration.razorpay_test_mode.client import get_client


def main():
    client = get_client()

    plan = client.plan.create({
        "period": "monthly",
        "interval": 1,
        "item": {
            "name": "Adaptive Mandate Recovery Test Plan",
            "amount": 10000,  # paise -> INR 100.00
            "currency": "INR",
            "description": "Day 2 connectivity spike -- not a real product",
        },
    })
    print(f"Created plan: {plan['id']}")

    # fail_existing:0 was supposed to make this idempotent (reuse the customer if the email already
    # exists) but the API rejected it anyway on a repeat run. Rather than chase that down, a unique
    # email per run sidesteps the collision entirely -- simpler and just as good for a throwaway
    # test customer that only exists to exercise the API.
    customer = client.customer.create({
        "name": "Test Customer",
        "email": f"test.customer.{int(time.time())}@example.com",
        "contact": "9999999999",
    })
    print(f"Created customer: {customer['id']}")

    subscription = client.subscription.create({
        "plan_id": plan["id"],
        "customer_notify": 0,  # we'll authorize manually via short_url, no need to email a dummy address
        "total_count": 4,      # matches the project's own 4-attempt stopping-rule cap (A20)
        "notes": {
            "project": "adaptive-mandate-recovery-engine",
            "purpose": "day2-webhook-spike",
        },
    })
    print(f"Created subscription: {subscription['id']}")
    print(f"Status: {subscription['status']}")
    print(f"Authorize this mandate at: {subscription['short_url']}")
    print()
    print("Next: open that URL and complete authorization with a Razorpay-published test card")
    print("or UPI VPA to activate the mandate. Then watch the webhook receiver log.")


if __name__ == "__main__":
    main()
