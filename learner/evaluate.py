"""The honest scorecard: what the learner does to a stream it has never seen.

METHOD
------
One judgement log, split CHRONOLOGICALLY -- first 60% to learn from, last 40% to score on. Never
randomly: the whole product claim is "it stops repeating yesterday's mistake tomorrow", and a
random split leaks tomorrow into yesterday and turns a weak result into a flattering one.

"Before" is the action the simulated app actually took (`action` in the log), which is exactly
`block if verdict == off_task and confidence >= 0.55`. "After" replays the same verdicts and the
same confidences through `policy.apply`, changing only what the policy says. So the model is held
constant and the only variable is the learner -- which is the only comparison that isolates it.

WHAT CAN AND CANNOT BE MEASURED HERE
------------------------------------
Mechanisms (b) allowances and (c) calibration are decision rules applied to a fixed verdict
stream, so they can be replayed exactly and the numbers below are real.

Mechanism (a) exemplars CANNOT be measured this way, and we refuse to pretend otherwise. It works
by changing what the model answers, and replaying a log cannot re-ask the model. Inventing an
"assumed 30% improvement from few-shot" would make the scorecard fiction. What we report instead
is COVERAGE: of the false alarms in the test set, how many would have arrived at the model with a
relevant exemplar line already in the prompt. That is an upper bound on the mechanism's reach and
nothing more, and it is labelled as such. Measuring it properly needs an online A/B against a
live model; that is the honest next experiment, not something to be simulated away.
"""

from . import features as F
from . import learn as L
from . import policy as P
from . import simulate as S


class Outcome:
    """Confusion counts for one replay of a test set."""

    __slots__ = ("checks", "blocks", "blocks_wrong", "blocks_right", "truly_off", "truly_on",
                 "off_blocked", "off_missed", "model_calls", "label")

    def __init__(self, label=""):
        self.label = label
        self.checks = 0
        self.blocks = 0
        self.blocks_wrong = 0     # blocked a screen that was genuinely part of the work
        self.blocks_right = 0
        self.truly_off = 0
        self.truly_on = 0
        self.off_blocked = 0
        self.off_missed = 0
        self.model_calls = 0

    # --- the four numbers a user would actually care about ---------------------------------

    @property
    def false_alarm_rate(self):
        """Of everything it stopped you for, how much was wrong. The trust-destroying number."""
        return self.blocks_wrong / float(self.blocks) if self.blocks else 0.0

    @property
    def false_alarms_per_100_checks(self):
        """The same failure per unit of TIME rather than per block -- which is how it is actually
        experienced. A policy that blocks half as often at the same error rate still halves the
        number of interruptions in an afternoon."""
        return 100.0 * self.blocks_wrong / float(self.checks) if self.checks else 0.0

    @property
    def missed_violation_rate(self):
        """Of the genuine distractions, how many got through. The number the guard protects."""
        return self.off_missed / float(self.truly_off) if self.truly_off else 0.0

    @property
    def precision(self):
        return self.blocks_right / float(self.blocks) if self.blocks else 0.0

    @property
    def recall(self):
        return self.off_blocked / float(self.truly_off) if self.truly_off else 0.0

    @property
    def f1(self):
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    def as_dict(self):
        return {
            "label": self.label,
            "checks": self.checks,
            "blocks": self.blocks,
            "blocks_wrong": self.blocks_wrong,
            "blocks_right": self.blocks_right,
            "truly_off_task": self.truly_off,
            "missed": self.off_missed,
            "model_calls": self.model_calls,
            "false_alarm_rate": round(self.false_alarm_rate, 4),
            "false_alarms_per_100_checks": round(self.false_alarms_per_100_checks, 3),
            "missed_violation_rate": round(self.missed_violation_rate, 4),
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
        }


def baseline(rows):
    """Replay of what the app actually did, straight from the log's own `action` field."""
    out = Outcome("before (no learning)")
    for r in rows:
        truth_on = bool(r.get("truth_on_task"))
        out.checks += 1
        out.model_calls += 1
        if truth_on:
            out.truly_on += 1
        else:
            out.truly_off += 1
        if r["action"] == "blocked":
            out.blocks += 1
            if truth_on:
                out.blocks_wrong += 1
            else:
                out.blocks_right += 1
                out.off_blocked += 1
        elif not truth_on:
            out.off_missed += 1
    return out


def replay(rows, pol, label="after"):
    """Replay the same verdicts through a compiled policy.

    A `pre_allow` removes the model call entirely, which is why `model_calls` is tracked: on a
    2-minute cadence the cost saving is not a rounding error, and it is the one benefit of this
    mechanism that does not depend on the model being wrong.
    """
    out = Outcome(label)
    for r in rows:
        truth_on = bool(r.get("truth_on_task"))
        out.checks += 1
        if truth_on:
            out.truly_on += 1
        else:
            out.truly_off += 1

        decision = P.apply(pol, task=r.get("task", ""), app=r.get("app", ""),
                           title=r.get("window_title", ""), ts=r["ts"])
        if decision["pre_allow"]:
            if not truth_on:
                out.off_missed += 1
            continue                                  # no call, no block

        out.model_calls += 1
        threshold = decision["block_threshold"]
        if threshold <= 0.0:
            threshold = S.APP_BLOCK_THRESHOLD         # policy has no opinion; app's rule stands

        blocked = (r["verdict"] == "off_task" and r["confidence"] >= threshold)
        if blocked:
            out.blocks += 1
            if truth_on:
                out.blocks_wrong += 1
            else:
                out.blocks_right += 1
                out.off_blocked += 1
        elif not truth_on:
            out.off_missed += 1
    return out


def split(rows, train_fraction=0.6):
    """Chronological split on judgement rows (feedback is already folded into them)."""
    ordered = sorted(rows, key=lambda r: r["ts"])
    cut = int(len(ordered) * train_fraction)
    return ordered[:cut], ordered[cut:]


def _without(pol, *keys):
    """A copy of the policy with some mechanisms removed, for the ablation table."""
    trimmed = dict(pol)
    for k in keys:
        trimmed[k] = []
    if "allowances" in keys:
        trimmed["signature_count"] = 0
    if "exemplars" in keys:
        trimmed["exemplar_count"] = 0
    return trimmed


def exemplar_coverage(test_rows, pol):
    """Upper bound on mechanism (a): how many test-set false alarms would have reached the model
    with a relevant exemplar already in the prompt.

    "Relevant" is deliberately strict -- the exemplar has to name the same app or the same domain
    as the screen being judged. A generous definition here would flatter the mechanism, and this
    number is already an upper bound rather than an effect.
    """
    total = hit = 0
    chars = []
    for r in test_rows:
        if r["action"] != "blocked" or not r.get("truth_on_task"):
            continue
        total += 1
        suffix = P.apply(pol, task=r.get("task", ""), app=r.get("app", ""),
                         title=r.get("window_title", ""), ts=r["ts"])["prompt_suffix"]
        if not suffix:
            continue
        chars.append(len(suffix))
        domain = F.extract_domain(r.get("window_title", "")) or ""
        app_name = (r.get("app_name") or "").lower()
        low = suffix.lower()
        if (domain and domain in low) or (app_name and app_name in low):
            hit += 1
    return {
        "baseline_false_alarms": total,
        "with_relevant_exemplar": hit,
        "coverage": round(hit / float(total), 4) if total else 0.0,
        "mean_suffix_chars": round(sum(chars) / float(len(chars)), 1) if chars else 0.0,
    }


def run(rows, config=None, guard=None, train_fraction=0.6):
    """Full before/after evaluation. Returns a report dict; `format_report` renders it."""
    train, test = split(rows, train_fraction)
    state = L.learn(train, config=config, guard=guard)
    pol = P.compile_policy(state)

    before = baseline(test)
    after = replay(test, pol, "after (all mechanisms)")
    allow_only = replay(test, _without(pol, "thresholds"), "allowances only")
    thresh_only = replay(test, _without(pol, "allowances"), "calibration only")

    prevented = before.blocks - after.blocks
    prevented_good = before.blocks_wrong - after.blocks_wrong
    prevented_bad = before.blocks_right - after.blocks_right

    return {
        "train_rows": len(train),
        "test_rows": len(test),
        "learned": dict(state.stats),
        "policy": {
            "clusters": len(pol["clusters"]),
            "exemplars": pol["exemplar_count"],
            "allowances": pol["signature_count"],
            "thresholds": len(pol["thresholds"]),
            "allowance_actions": _count_actions(pol),
        },
        "integrity": pol["integrity"],
        "before": before.as_dict(),
        "after": after.as_dict(),
        "ablations": [allow_only.as_dict(), thresh_only.as_dict()],
        "blocks_prevented": {
            "total": prevented,
            "were_false_alarms": prevented_good,
            "were_genuine": prevented_bad,
        },
        "model_calls_saved": before.model_calls - after.model_calls,
        "exemplar_coverage": exemplar_coverage(test, pol),
        "_policy": pol,
    }


def _count_actions(pol):
    counts = {}
    for a in pol.get("allowances") or []:
        counts[a["action"]] = counts.get(a["action"], 0) + 1
    return counts


def run_gaming_comparison(honest_rows, gamer_rows, config=None, guard=None, train_fraction=0.6):
    """Does the guard actually hold when the feedback is adversarial?

    Same test set both times (the honest one -- what matters is how the tool behaves afterwards,
    not how the gamer's own session scored). Only the TRAINING feedback differs. If the guard
    works, the gamer's policy must not be meaningfully worse at catching genuine distractions.
    """
    _, honest_test = split(honest_rows, train_fraction)
    honest_train, _ = split(honest_rows, train_fraction)
    gamer_train, _ = split(gamer_rows, train_fraction)

    honest_state = L.learn(honest_train, config=config, guard=guard)
    gamer_state = L.learn(gamer_train, config=config, guard=guard)
    honest_pol = P.compile_policy(honest_state)
    gamer_pol = P.compile_policy(gamer_state)

    return {
        "honest": replay(honest_test, honest_pol, "policy learned from honest feedback").as_dict(),
        "gamed": replay(honest_test, gamer_pol, "policy learned from spammed feedback").as_dict(),
        "honest_policy": {
            "allowances": honest_pol["signature_count"],
            "exemplars": honest_pol["exemplar_count"],
            "integrity": honest_pol["integrity"],
        },
        "gamed_policy": {
            "allowances": gamer_pol["signature_count"],
            "exemplars": gamer_pol["exemplar_count"],
            "integrity": gamer_pol["integrity"],
        },
        "guard": {
            "presses": gamer_state.stats["false_alarms"],
            "credited": gamer_state.stats["false_alarms_credited"],
            "refused": gamer_state.stats["false_alarms_rejected"],
        },
    }


# ---------------------------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------------------------

def _row(label, before, after, fmt="%.1f%%", scale=100.0, better="down"):
    b, a = before * scale, after * scale
    delta = a - b
    arrow = ""
    if abs(delta) >= 0.05:
        good = (delta < 0) if better == "down" else (delta > 0)
        arrow = "  better" if good else "  WORSE"
    return "  %-32s %10s %10s   %+7.1f%s" % (
        label, fmt % b, fmt % a, delta, arrow)


def format_report(report):
    out = []
    add = out.append
    add("=" * 78)
    add("FOCUS LEARNER -- OFFLINE EVALUATION")
    add("=" * 78)
    add("train: %d judgements   test: %d judgements   (chronological 60/40 split)"
        % (report["train_rows"], report["test_rows"]))
    learned = report["learned"]
    add("feedback in training window: %d false alarm(s) [%d credited, %d refused by the guard], "
        "%d correct, %d missed"
        % (learned["false_alarms"], learned["false_alarms_credited"],
           learned["false_alarms_rejected"], learned["correct"], learned["missed"]))
    pol = report["policy"]
    add("policy: %d cluster(s), %d exemplar(s), %d allowance(s) %s, %d calibrated threshold(s)"
        % (pol["clusters"], pol["exemplars"], pol["allowances"],
           pol["allowance_actions"] or "", pol["thresholds"]))
    add("")

    before, after = report["before"], report["after"]
    add("%-34s %10s %10s %10s" % ("", "before", "after", "delta"))
    add("-" * 78)
    add(_row("false-alarm rate (of blocks)", before["false_alarm_rate"],
             after["false_alarm_rate"]))
    add(_row("false alarms per 100 checks", before["false_alarms_per_100_checks"] / 100.0,
             after["false_alarms_per_100_checks"] / 100.0))
    add(_row("missed-violation rate", before["missed_violation_rate"],
             after["missed_violation_rate"]))
    add(_row("precision (blocks that were right)", before["precision"], after["precision"],
             better="up"))
    add(_row("recall (distractions caught)", before["recall"], after["recall"], better="up"))
    add(_row("F1", before["f1"], after["f1"], better="up"))
    add("-" * 78)
    add("  %-32s %10d %10d   %+7d" % ("blocks", before["blocks"], after["blocks"],
                                      after["blocks"] - before["blocks"]))
    add("  %-32s %10d %10d   %+7d" % ("  of which were false alarms", before["blocks_wrong"],
                                      after["blocks_wrong"],
                                      after["blocks_wrong"] - before["blocks_wrong"]))
    add("  %-32s %10d %10d   %+7d" % ("  of which were genuine", before["blocks_right"],
                                      after["blocks_right"],
                                      after["blocks_right"] - before["blocks_right"]))
    add("  %-32s %10d %10d   %+7d" % ("model calls", before["model_calls"], after["model_calls"],
                                      after["model_calls"] - before["model_calls"]))
    add("")

    bp = report["blocks_prevented"]
    add("BLOCKS PREVENTED: %d  (%d were false alarms, %d were genuine distractions the learner "
        "let through)" % (bp["total"], bp["were_false_alarms"], bp["were_genuine"]))
    add("MODEL CALLS SAVED: %d" % report["model_calls_saved"])
    add("")

    add("ABLATIONS (each mechanism alone, same test set)")
    add("  %-34s %8s %8s %8s %8s" % ("", "FA rate", "missed", "prec", "recall"))
    for row in [before] + report["ablations"] + [after]:
        add("  %-34s %7.1f%% %7.1f%% %7.1f%% %7.1f%%"
            % (row["label"][:34], 100 * row["false_alarm_rate"],
               100 * row["missed_violation_rate"], 100 * row["precision"], 100 * row["recall"]))
    add("")

    cov = report["exemplar_coverage"]
    add("EXEMPLAR MEMORY (mechanism a) -- NOT MEASURED, coverage only")
    add("  Replaying a log cannot re-ask the model, so no accuracy change can be claimed here.")
    add("  %d of %d test-set false alarms (%.1f%%) would have reached the model with a relevant"
        % (cov["with_relevant_exemplar"], cov["baseline_false_alarms"], 100 * cov["coverage"]))
    add("  exemplar already in the prompt (mean suffix %.0f chars of the 1200 budget)."
        % cov["mean_suffix_chars"])
    add("  That is an upper bound on its reach, not an effect. Needs a live A/B to measure.")
    add("")

    integrity = report["integrity"]
    add("INTEGRITY: score %.2f, notify partner: %s"
        % (integrity["score"], "YES" if integrity["notify_partner"] else "no"))
    for flag in integrity["flags"]:
        add("  - %s" % flag)
    return "\n".join(out)


def format_gaming(report):
    out = []
    add = out.append
    add("=" * 78)
    add("ANTI-GAMING GUARD -- adversarial feedback vs honest feedback")
    add("=" * 78)
    g = report["guard"]
    add("Spammed run: %d false-alarm presses, %d credited, %d refused by the guard (%.0f%%)"
        % (g["presses"], g["credited"], g["refused"],
           100.0 * g["refused"] / max(g["presses"], 1)))
    add("")
    add("  %-38s %8s %8s %8s" % ("policy trained on", "FA rate", "missed", "recall"))
    for key in ("honest", "gamed"):
        r = report[key]
        add("  %-38s %7.1f%% %7.1f%% %7.1f%%"
            % (r["label"][:38], 100 * r["false_alarm_rate"],
               100 * r["missed_violation_rate"], 100 * r["recall"]))
    add("")
    for key, title in (("honest_policy", "honest"), ("gamed_policy", "spammed")):
        p = report[key]
        integ = p["integrity"]
        add("%s policy: %d allowance(s), %d exemplar(s), integrity %.2f, notify partner: %s"
            % (title, p["allowances"], p["exemplars"], integ["score"],
               "YES" if integ["notify_partner"] else "no"))
        for flag in integ["flags"]:
            add("    - %s" % flag)
    return "\n".join(out)
