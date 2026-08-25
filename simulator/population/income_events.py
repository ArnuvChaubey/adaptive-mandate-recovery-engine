"""Income event calendars per customer type.

A12 is reasonably evidenced at the population level: the Payment of Wages Act sets a legal deadline
(7th of the following month for establishments under 1,000 employees, 10th for larger), and multiple
industry payroll sources report practice clustering around month-end/1st and around the 7th.

A13 is not evidenced at all: knowing the population clusters tells you nothing about whether *this*
customer does. That gap is permanent -- no public data closes it -- so the population is generated as
a mixture over timing types rather than assuming one universal payday, and the mixture weights are
swept.
"""

import numpy as np

from simulator.mandate import IncomeTimingType

# Day-of-month targets per type. The irregular type deliberately has no target -- its income events
# are drawn uniformly, representing gig/informal/variable earners for whom no cycle applies.
_TYPE_TARGET_DAYS: dict[IncomeTimingType, tuple[int, ...]] = {
    IncomeTimingType.CLUSTERED_MONTH_END_OR_1ST: (1, 30),
    IncomeTimingType.CLUSTERED_NEAR_7TH: (7,),
}

# How tightly income lands around the target day. Payroll runs slip by a few days in practice
# (bank holidays, processing lag), so this is a spread, not an exact date. ASSUMPTION, not sourced.
_CLUSTER_SPREAD_DAYS = 2


def income_event_days(
    timing_type: IncomeTimingType,
    horizon_days: int,
    rng: np.random.Generator,
) -> set[int]:
    """Returns the day indices (0-based, from simulation start) on which income arrives."""
    if timing_type == IncomeTimingType.IRREGULAR_NO_CLEAR_CYCLE:
        # Roughly monthly in frequency but with no cycle a policy could learn to exploit.
        n_events = max(1, horizon_days // 30)
        return {int(d) for d in rng.choice(horizon_days, size=min(n_events, horizon_days), replace=False)}

    targets = _TYPE_TARGET_DAYS[timing_type]
    days: set[int] = set()
    for month_start in range(0, horizon_days, 30):
        for target in targets:
            jitter = int(rng.integers(-_CLUSTER_SPREAD_DAYS, _CLUSTER_SPREAD_DAYS + 1))
            day = month_start + target - 1 + jitter
            if 0 <= day < horizon_days:
                days.add(day)
    return days
