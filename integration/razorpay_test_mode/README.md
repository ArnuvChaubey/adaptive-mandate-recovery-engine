# integration/razorpay_test_mode/

The scripted, repeatable seed process against real Razorpay test-mode APIs. This is a **qualitative
integration proof** — evidence the system calls real APIs end to end — not a statistically powered validation
set. At the scale available (~15-20 live cases), it cannot carry the recovery-rate or lift claim; that claim
rests entirely on `simulator/` and `eval/`. See A30 and `docs/positioning.md`.

Day 1 (today): SDK client wired to `.env` test-mode credentials, no live calls yet.
Day 2: webhook receiver behind a public tunnel (ngrok), first real end-to-end webhook received and logged
into the same `audit/` schema as the simulator, tagged `source: live_test_mode`.
Milestone 6 (Day 10): full ~15-20 case scripted batch run, timed close to the video-recording date to respect
the 3-day test-mode token window (A29).
