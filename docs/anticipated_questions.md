# Anticipated panel questions

Five gaps came out of research honestly, not from laziness — no public source exists for them. This doc is
the prepared, rehearsed answer for each, so the honest gap reads as engineering judgment in the room, not as
something we got caught not knowing. Structure for each: acknowledge -> why it's unavoidable -> what we built
because of it.

---

### "How do you know your baseline retry timing is realistic? Razorpay might already retry smarter than this."

We don't know the exact cadence, and we say so out loud — it's assumption **A1**, marked the single highest
Challenge Risk in `assumptions.md`, not buried. Razorpay's own docs confirm only "retries the next day" for
cards and a precise bank-holiday-shift rule for Emandate; nothing beyond that is published for cards or UPI.
So we did two things instead of guessing: we biased the baseline toward the *most retry-friendly plausible*
interval — meaning if we're wrong, the error makes the comparison harder on our own adaptive policy, not
easier — and we built the entire evaluation as a sensitivity sweep. The headline claim isn't "adaptive beats
baseline by X%" at one guessed number. It's "adaptive beats baseline across the plausible range of cadences
we could construct from public evidence." If you have better information about the real cadence, that
tightens our range — it doesn't break the methodology.

### "Where did the numbers for `bank_technical_decline` come from?"

Nowhere, and `assumptions.md` (A18) says so directly — it's the one failure class in the taxonomy with zero
public evidence behind it. We kept the category because transient bank-side declines are a well-established
reality in payments; we don't pretend to know their frequency or recovery curve. It carries the widest swept
range of any failure class in the sensitivity analysis, specifically because it's the one we're least sure
about.

### "How much does the NPCI congestion window actually hurt success rates?"

Nobody publishes that number, us included. NPCI's 2026 Traffic Management framework confirms the
deprioritization window exists (10am-1pm) but never states a magnitude (A8). We modeled degradation as a
swept parameter rather than asserting a point value, and kept the policy's actual response to it simple:
avoid retrying in the documented bad window. That's the right-sized engineering response to a qualitative
signal with no quantitative backing — react to what you know, don't manufacture precision on what you don't.

### "Where do the rupee amounts in 'money recovered' come from?"

We drafted the bands ourselves — no published distribution exists for OTT/SIP/EMI mandate amounts in India
(A22). This is the most honest place in the project to be direct: the ₹-recovered figure demonstrates the
*measurement methodology* the rubric asks for, not a validated revenue forecast. Swap in real distribution
data and the same pipeline produces a real number — that swap is a config change, not a rebuild.

### "I've seen a stat that ~74% of these fail at the bank level — did you use that?"

We saw it too, traced it to a single report whose denominator and methodology weren't clear, and made a
deliberate call to leave it out entirely — not in the simulator, not in the README, not in the pitch. We
don't cite a number we can't verify, even when it would make a good headline.

---

## Adjacent questions worth having ready (not from this list, but likely)

- **"Why not just use Razorpay's own Intelligent Retry Engine instead of building this?"** — Because it's a
  configurable black box with no published methodology, no benchmarked lift, and no audit trail. This project
  is the credibility layer that engine doesn't expose publicly, not a competing retry algorithm. See
  `docs/positioning.md`. Be ready for the honest follow-up too: we haven't benchmarked *against* it, because
  it has no callable interface (A26) — say that plainly if asked, don't imply otherwise.
- **"Why isn't the LLM making the retry decisions?"** — Non-deterministic decisions on payment collection are
  an audit and compliance liability. The policy engine decides; the LLM only narrates after the fact, reading
  the decision log and never writing back to it. That boundary is the direct answer to "the right tool in the
  right place, and where you chose not to use one."
- **"Is any of this real, or is it all simulated?"** — Both, and we label which is which everywhere. The
  simulator produces the batch-level recovery-rate and lift claims. The ~15-20 case Razorpay test-mode
  integration is a qualitative proof the system calls real APIs correctly — not statistically powered, and
  never presented as if it validates the recovery-rate number.

Still open, not yet answerable with confidence: **A4** (does an undelivered notification legally auto-block
the debit?) still needs a primary-source recheck against the actual RBI circular text, not press summaries —
see the note in `assumptions.md`. Don't claim certainty on this one until that check happens.
