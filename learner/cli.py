"""`python -m learner.cli simulate | learn | evaluate | explain`.

Four verbs, one for each thing you actually want to do with a learner: make data, learn from it,
score the result, and ask it why. `explain` is the one that earns its place -- a policy you
cannot interrogate is a policy nobody will trust enough to enable, and "why did it stop me for
that" is the first question anyone asks.

Paths default into `learner/data/` so the whole thing runs out of the box with no arguments and
without touching the app's real data directory. Point `--policy` at
`%LOCALAPPDATA%/Guardian/focus_policy.json` when you want the running app to pick it up.
"""

import argparse
import json
import os
import sys
import time

from . import evaluate as E
from . import learn as L
from . import policy as P
from . import simulate as S
from . import store

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
DEFAULT_LOG = os.path.join(DATA_DIR, "judgements.jsonl")
DEFAULT_POLICY = os.path.join(DATA_DIR, "focus_policy.json")
DEFAULT_GAMER_LOG = os.path.join(DATA_DIR, "judgements_gamed.jsonl")


def cmd_simulate(args):
    config = S.SimConfig(days=args.days, seed=args.seed, gamer=args.gamer)
    rows = S.generate(config)
    store.write_rows(args.out, rows)
    info = S.summarise(rows)
    print("wrote %d rows to %s" % (len(rows), args.out))
    print("  %d judgements, %d feedback rows" % (info["judgements"], info["feedback_rows"]))
    print("  %d blocked, of which %d were genuinely on task (the false alarms)"
          % (info["blocked"], info["blocked_but_on_task"]))
    print("  %d screens were genuinely off task" % info["truly_off_task"])
    print("  feedback: %d false_alarm, %d correct, %d missed"
          % (info["false_alarm"], info["correct"], info["missed"]))
    print("  task phrasings seen: %d" % len(info["tasks"]))
    if args.gamer:
        print("  [gamer mode] the simulated user also presses 'false alarm' on genuine "
              "distractions, reflexively")
    return 0


def cmd_learn(args):
    result = store.read_judgements(args.log)
    if result.skipped:
        print("note: skipped %d malformed line(s) in %s" % (result.skipped, args.log))
    if result.orphan_feedback:
        print("note: %d feedback row(s) refer to judgements no longer in the log"
              % result.orphan_feedback)
    if not result.rows:
        print("no judgements in %s -- run `python -m learner.cli simulate` first" % args.log)
        return 1

    state = L.learn(result.rows)
    # Wall-clock stamp: the client expires a policy older than 60 days by the calendar, so a
    # policy written for the app must be dated by the calendar too.
    pol = P.compile_policy(state, generated_at=time.time())
    P.save_policy(args.out, pol)

    stats = state.stats
    print("learned from %d judgement(s) (%d in the %.0f-day window)"
          % (stats["rows"], stats["in_window"], state.config.window_days))
    print("  feedback: %d false alarm(s) -> %d credited, %d refused by the guard; "
          "%d correct, %d missed"
          % (stats["false_alarms"], stats["false_alarms_credited"],
             stats["false_alarms_rejected"], stats["correct"], stats["missed"]))
    print("  %d task cluster(s), %d signature(s) with evidence"
          % (stats["clusters"], stats["signatures"]))
    print("wrote %s" % args.out)
    print("  schema %d, %d exemplar(s), %d allowance(s), %d calibrated threshold(s)"
          % (pol["schema"], pol["exemplar_count"], pol["signature_count"],
             len(pol["thresholds"])))

    labels = {c["id"]: c["label"] for c in pol["clusters"]}
    for a in pol["allowances"]:
        print("  allow[%s] %s / %s  (task: %s)  <- %s"
              % (a["action"], a["app_name"] or a["app"],
                 a["pattern"]["value"] or a["pattern"]["kind"],
                 labels.get(a["cluster"], a["cluster"]), a["why"]))
    for t in pol["thresholds"]:
        print("  threshold %s / %s = %.2f (%d false alarm(s), %d missed)"
              % (labels.get(t["cluster"], t["cluster"]), t["app_name"] or t["app"],
                 t["block_threshold"], t["false_alarms"], t["missed"]))

    integrity = pol["integrity"]
    if integrity["notify_partner"]:
        print("")
        print("  !! INTEGRITY ALERT (score %.2f) -- the app should push this to the "
              "accountability partner:" % integrity["score"])
        print("     %s" % integrity["headline"])
    elif integrity["score"]:
        print("  integrity score %.2f (no alert)" % integrity["score"])
    return 0


def cmd_evaluate(args):
    result = store.read_judgements(args.log)
    if not result.rows:
        print("no judgements in %s -- run `python -m learner.cli simulate` first" % args.log)
        return 1
    if not any("truth_on_task" in r for r in result.rows):
        print("this log has no ground-truth labels, so nothing here can be scored honestly.")
        print("`evaluate` only works on simulated data (`learner.cli simulate`).")
        return 1

    report = E.run(result.rows, train_fraction=args.train_fraction)
    print(E.format_report(report))

    if args.gamer_log and os.path.exists(args.gamer_log):
        gamer = store.read_judgements(args.gamer_log)
        if gamer.rows:
            print("")
            print(E.format_gaming(E.run_gaming_comparison(
                result.rows, gamer.rows, train_fraction=args.train_fraction)))

    if args.json:
        report.pop("_policy", None)
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, sort_keys=True)
        print("")
        print("wrote machine-readable report to %s" % args.json)
    return 0


def cmd_explain(args):
    pol = P.load_policy(args.policy)
    if not pol:
        print("no usable policy at %s (missing, wrong schema, or older than %d days)"
              % (args.policy, P.POLICY_MAX_AGE_DAYS))
        print("the app would behave exactly as it does with learning switched off.")
        return 1
    result = P.explain(pol, task=args.task, app=args.app, title=args.title)
    print("policy:        %s  (generated %s)"
          % (args.policy, time.strftime("%Y-%m-%d %H:%M",
                                        time.localtime(pol.get("generated_at", 0)))))
    for line in result["trace"]:
        print(line)
    print("")
    print("apply() returns: %s" % json.dumps(result["decision"], sort_keys=True)[:400])
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="python -m learner.cli",
        description="Offline learner for the focus monitor's false alarms.")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("simulate", help="generate a labelled synthetic judgement log")
    p.add_argument("--out", default=DEFAULT_LOG)
    p.add_argument("--days", type=int, default=24)
    p.add_argument("--seed", type=int, default=20260908)
    p.add_argument("--gamer", action="store_true",
                   help="simulate a user spamming 'false alarm' to gut the tool")
    p.set_defaults(func=cmd_simulate)

    p = sub.add_parser("learn", help="read a judgement log and write focus_policy.json")
    p.add_argument("--log", default=DEFAULT_LOG)
    p.add_argument("--out", default=DEFAULT_POLICY)
    p.set_defaults(func=cmd_learn)

    p = sub.add_parser("evaluate", help="before/after scorecard on labelled data")
    p.add_argument("--log", default=DEFAULT_LOG)
    p.add_argument("--gamer-log", default=DEFAULT_GAMER_LOG)
    p.add_argument("--train-fraction", type=float, default=0.6)
    p.add_argument("--json", default="", help="also write the report as JSON")
    p.set_defaults(func=cmd_evaluate)

    p = sub.add_parser("explain", help="why the policy would allow or block one screen")
    p.add_argument("task")
    p.add_argument("app")
    p.add_argument("title", nargs="?", default="")
    p.add_argument("--policy", default=DEFAULT_POLICY)
    p.set_defaults(func=cmd_explain)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
