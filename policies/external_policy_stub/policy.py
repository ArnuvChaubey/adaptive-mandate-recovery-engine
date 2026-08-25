"""Deliberately unimplemented third policy slot -- an honest limitation, made visible.

This file exists to make assumption **A26** impossible to overlook.

The project claims the evaluation harness is policy-agnostic. That claim is a *design property*: any
implementation of `Policy` can be scored by the same harness with no changes. What it is emphatically
NOT is a demonstration that a real third-party engine has been benchmarked here.

Razorpay's Intelligent Retry Engine (beta, FTX 2026) and the Agent Studio Subscription Recovery Agent
expose no public callable interface. There is no API to plug in. We have not benchmarked against
them, we cannot, and the pitch must never imply otherwise.

The honest options were:
  (a) omit this file, and let "policy-agnostic" quietly imply more than we can support;
  (b) include it, unimplemented, with the limitation stated in the place a reviewer will look.

We chose (b). An architecture diagram with a labelled empty slot is more truthful than one that hides
the slot exists. If a callable external engine ever becomes available, this is where it lands, and
nothing else in the harness needs to change -- which is the actual claim being made.
"""

from policies.policy_interface.base import Decision, Policy, PolicyState


class ExternalPolicyStub(Policy):
    """Never instantiated in any evaluation run. Present as documentation-in-code."""

    name = "external_engine_stub"

    def decide(self, state: PolicyState, config: dict) -> Decision:
        raise NotImplementedError(
            "No third-party retry engine exposes a public callable interface (assumption A26). "
            "This slot demonstrates that the harness accepts any Policy implementation; it is not "
            "evidence that an external engine has been benchmarked. See docs/positioning.md."
        )
