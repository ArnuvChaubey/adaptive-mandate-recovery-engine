"""Guards against the higher OTP ceiling being unreachable in practice.

A6 gives insurance, mutual funds, and credit-card bills a higher INR 1,00,000 no-OTP ceiling. Both the
adaptive policy and the compliance invariant implemented that -- and neither could ever trigger it,
because they compared this project's product names (`ott_subscription`, `sip_investment`, `emi`)
directly against RBI's category names. The sets are disjoint, so the branch was dead everywhere, and
12.3% of mandates were being escalated when the law allowed an auto-retry.

The existing unit test for the higher ceiling passed throughout, because it constructed a
`ProposedDecision(amount_category="mutual_funds")` by hand -- proving the invariant handles the
category correctly while proving nothing about whether anything ever supplies it. That is entry 14's
lesson restated: a rule that passes its unit test and is wired to nothing still does nothing.

These tests check reachability, which is the property that was actually missing.
"""

import pytest
import yaml
from pathlib import Path

from compliance.invariants.rules import (
    RBI_CATEGORY_BY_AMOUNT_TYPE,
    ProposedDecision,
    check_otp_ceiling,
    rbi_category_for,
)
from simulator.config_loader import load_config
from simulator.mandate import AmountType

CONFIG_PATH = Path(__file__).parent.parent / "config" / "sim_params.yaml"


def _ceiling_cfg() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text())["compliance_floors"]["otp_free_ceiling_inr"]


def test_at_least_one_amount_type_reaches_the_higher_ceiling():
    """The whole point. If no product can ever map into a higher-ceiling category, the branch is
    decoration and A6's carve-out is unimplemented."""
    categories = set(_ceiling_cfg()["higher_ceiling_categories"])
    reachable = {rbi_category_for(t.value) for t in AmountType} & categories
    assert reachable, (
        "No AmountType maps into any higher_ceiling_categories entry, so the INR 1,00,000 ceiling "
        "can never apply to anything. That was the bug in build log entry 26."
    )


def test_every_mapped_category_is_one_the_config_actually_recognises():
    """The mapping must not invent a category the regulation doesn't name -- mapping `emi` to
    something like 'loan_emi' would silently grant a legal allowance we cannot cite."""
    categories = set(_ceiling_cfg()["higher_ceiling_categories"])
    for amount_type, rbi_category in RBI_CATEGORY_BY_AMOUNT_TYPE.items():
        assert rbi_category in categories, (
            f"{amount_type!r} maps to {rbi_category!r}, which is not in higher_ceiling_categories. "
            "Either the config or the mapping is wrong; guessing an extra category into A6's "
            "carve-out claims a legal allowance with no citation behind it."
        )


def test_unmapped_products_fall_back_to_general():
    """Deliberately partial: an EMI is a loan instalment, not a credit-card bill, and an OTT
    subscription is neither. Both must keep the standard ceiling."""
    assert rbi_category_for("emi") == "general"
    assert rbi_category_for("ott_subscription") == "general"
    assert rbi_category_for("something_unheard_of") == "general"


def test_sip_above_standard_ceiling_is_permitted_end_to_end():
    """The behaviour the dead branch was costing: a mutual-fund mandate between the two ceilings must
    pass the invariant, not be blocked."""
    config = load_config()
    proposed = ProposedDecision(
        mandate_id="m1",
        amount_inr=20_000.0,
        scheduled_retry_at=__import__("datetime").datetime(2026, 9, 1, 14, 0),
        notification_sent_at=__import__("datetime").datetime(2026, 8, 30, 14, 0),
        amount_category=rbi_category_for(AmountType.SIP_INVESTMENT.value),
    )
    check = check_otp_ceiling(proposed, config)
    assert check.passed, (
        "A INR 20,000 mutual-fund mandate is inside A6's higher ceiling and must not be blocked"
    )


def test_emi_above_standard_ceiling_is_still_blocked():
    """The other direction, so the fix can't quietly widen the carve-out to everything."""
    config = load_config()
    proposed = ProposedDecision(
        mandate_id="m2",
        amount_inr=20_000.0,
        scheduled_retry_at=__import__("datetime").datetime(2026, 9, 1, 14, 0),
        notification_sent_at=__import__("datetime").datetime(2026, 8, 30, 14, 0),
        amount_category=rbi_category_for(AmountType.EMI.value),
    )
    check = check_otp_ceiling(proposed, config)
    assert not check.passed, (
        "An EMI is not one of A6's higher-ceiling categories; INR 20,000 must still require "
        "additional factor authentication"
    )
