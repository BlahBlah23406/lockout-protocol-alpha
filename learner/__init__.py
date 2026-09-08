"""Focus-monitor learner: turns "False alarm" presses into a portable policy file.

The monitor screenshots the foreground app every N seconds and asks a vision model whether the
screen is consistent with the task the user declared. Its dominant failure is the FALSE ALARM:
the model flags a screen that was genuinely part of the work (a Khan Academy video on YouTube
while the task is "math test prep"). Every false alarm costs the user real trust, and a tool the
user stops trusting is a tool the user uninstalls.

This package consumes the feedback the user gives on the block screen and emits ONE file --
`focus_policy.json` -- that the Windows (Python), macOS (Swift) and Android (Kotlin) clients can
all read with nothing but a JSON parser. No ML runtime, no weights, no tensors: the whole policy
is counts, thresholds and string patterns, because a policy that needs a runtime will never ship
on three platforms.

The learner is deliberately ASYMMETRIC. Loosening the rules is slow, needs repeated evidence
across separate days, expires on its own, and is capped; tightening is fast and uncapped. This is
a self-control tool, so the user pressing "False alarm" is not automatically a trustworthy signal
-- it is exactly the lever a motivated user would pull to gut the product. See `learn.py` for the
anti-gaming guard and `README.md` for the rationale.
"""

__all__ = ["store", "features", "learn", "policy", "simulate", "evaluate"]
SCHEMA_VERSION = 1
