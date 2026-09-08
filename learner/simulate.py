"""Synthetic judgement streams with known ground truth, so the learner can be measured offline.

We cannot measure a false-alarm reducer on real logs we do not have, and we cannot measure it on
real logs even when we do, because a real log has no ground truth -- only the model's verdict and
the user's occasional opinion of it. So we generate a world where the truth is known by
construction and the model is wrong in the specific way the real one is wrong.

WHAT IS MODELLED, AND WHAT IS ASSUMED
-------------------------------------
Each scenario is a (task, app, title, IS-IT-REALLY-ON-TASK) tuple plus `p_flag`, the probability
that the vision model calls that screen off-task. The whole simulation rests on one empirical
claim: **the model's errors are systematic, not random.** It does not misfire uniformly; it
misfires on the same handful of legitimate-support screens over and over -- the Khan Academy
video, the r/learnmath thread, the study-group Discord. That is what the app's own users report
and it is the premise of the entire learner, because a purely random error has no signature to
learn. If that premise is wrong, mechanisms (a) and (b) cannot work and no amount of tuning will
save them.

Everything else here is scaffolding: three phrasings per task so the clusterer has to earn its
keep, sessions spread over real calendar days so the "evidence across separate days" guard is
exercised, and a `gamer` mode that presses "false alarm" on things it knows are genuine
distractions, so the anti-gaming guard is measured rather than asserted.

The output is written in the PRODUCER's format -- a judgement row plus, where feedback exists, a
separate `{"ref": ...}` row -- so `store.fold()` is exercised by the same data the app produces.
"""

import random
import time

from . import store

# The un-learned app rule the simulated monitor follows: a clean off-task verdict at or above
# this confidence blocks. Kept as a module constant because `evaluate` needs the identical
# number to compute an honest "before".
APP_BLOCK_THRESHOLD = 0.55

CHECK_INTERVAL = 120.0          # the monitor's default cadence, seconds


class Scenario:
    """One kind of screen a user lands on during a task.

    `truth_on_task` is ground truth -- what a fair human reviewer would say. `p_flag` is how often
    the vision model calls it off-task. A scenario with truth_on_task=True and a high p_flag IS a
    false-alarm generator, and those are the rows the learner exists to eliminate.
    """

    __slots__ = ("app", "app_name", "titles", "truth_on_task", "p_flag", "conf_lo", "conf_hi",
                 "weight", "reason")

    def __init__(self, app, app_name, titles, truth_on_task, p_flag,
                 conf=(0.55, 0.85), weight=1.0, reason=""):
        self.app = app
        self.app_name = app_name
        self.titles = titles
        self.truth_on_task = truth_on_task
        self.p_flag = p_flag
        self.conf_lo, self.conf_hi = conf
        self.weight = weight
        self.reason = reason


class TaskFamily:
    __slots__ = ("name", "phrasings", "scenarios")

    def __init__(self, name, phrasings, scenarios):
        self.name = name
        self.phrasings = phrasings
        self.scenarios = scenarios


# ---------------------------------------------------------------------------------------------
# The four task families.
#
# Each has: the core work (never flagged), a couple of SUPPORTING screens that the model gets
# wrong at a high and *stable* rate, some ambiguous middle ground, and genuine distractions that
# must keep being blocked no matter how much the user complains.
# ---------------------------------------------------------------------------------------------

FAMILIES = [
    TaskFamily(
        "math",
        ["working on math test prep",
         "studying for my math test",
         "math revision for the calculus exam"],
        [
            Scenario("onenote.exe", "OneNote",
                     ["Calculus notes - OneNote", "Integration practice - OneNote"],
                     True, 0.02, weight=3.0),
            Scenario("acrobat.exe", "Acrobat Reader",
                     ["past-paper-2023.pdf - Adobe Acrobat Reader",
                      "calculus-problem-set.pdf - Adobe Acrobat Reader"],
                     True, 0.05, weight=2.0),
            # The canonical false alarm: a lecture on the exact topic, hosted on YouTube.
            Scenario("chrome.exe", "Chrome",
                     ["Integration by parts - Khan Academy - YouTube",
                      "Trig substitution explained - Khan Academy - YouTube",
                      "Improper integrals - Khan Academy - YouTube"],
                     True, 0.72, conf=(0.55, 0.80), weight=2.2,
                     reason="YouTube video page visible, unrelated to math"),
            Scenario("chrome.exe", "Chrome",
                     ["r/learnmath - how do I approach this integral? - Reddit",
                      "r/learnmath - stuck on series convergence - Reddit"],
                     True, 0.63, conf=(0.50, 0.78), weight=1.4,
                     reason="Reddit social feed visible"),
            Scenario("discord.exe", "Discord",
                     ["#calculus-study-group - Discord",
                      "#exam-prep - Discord"],
                     True, 0.66, conf=(0.50, 0.75), weight=1.3,
                     reason="Chat application, not study material"),
            Scenario("chrome.exe", "Chrome",
                     ["definite integral calculator - Wolfram Alpha",
                      "graph of x^2 sin(x) - Desmos"],
                     True, 0.15, weight=1.2),
            # Genuine distractions. These must survive everything the learner does.
            Scenario("chrome.exe", "Chrome",
                     ["Minecraft 1.21 speedrun world record - YouTube",
                      "Top 10 anime openings - YouTube"],
                     False, 0.93, conf=(0.75, 0.97), weight=1.6),
            Scenario("chrome.exe", "Chrome",
                     ["For You - TikTok", "Explore - Instagram"],
                     False, 0.95, conf=(0.80, 0.98), weight=1.2),
        ],
    ),
    TaskFamily(
        "essay",
        ["writing my history essay",
         "essay on the industrial revolution",
         "writing an essay for history class"],
        [
            Scenario("winword.exe", "Word",
                     ["industrial-revolution-essay.docx - Word",
                      "essay draft 3.docx - Word"],
                     True, 0.02, weight=3.0),
            Scenario("chrome.exe", "Chrome",
                     ["Industrial Revolution - Wikipedia",
                      "Factory Acts 1833 - Wikipedia"],
                     True, 0.28, conf=(0.45, 0.70), weight=1.8,
                     reason="Encyclopedia browsing, not the essay"),
            Scenario("chrome.exe", "Chrome",
                     ["Child labour in Victorian Britain - JSTOR",
                      "Steam power and productivity - Google Scholar"],
                     True, 0.10, weight=1.3),
            Scenario("chrome.exe", "Chrome",
                     ["How to structure an argumentative essay - YouTube",
                      "Thesis statements explained - YouTube"],
                     True, 0.70, conf=(0.55, 0.82), weight=1.5,
                     reason="YouTube visible during writing time"),
            Scenario("chrome.exe", "Chrome",
                     ["Continue watching - Netflix", "Home - Netflix"],
                     False, 0.94, conf=(0.78, 0.97), weight=1.4),
            Scenario("chrome.exe", "Chrome",
                     ["Home / X", "Notifications / X"],
                     False, 0.90, conf=(0.70, 0.95), weight=1.2),
        ],
    ),
    TaskFamily(
        "coding",
        ["coding the payments service",
         "working on the payments API",
         "fixing bugs in the payments service"],
        [
            Scenario("code.exe", "VS Code",
                     ["payments.py - api - Visual Studio Code",
                      "test_payments.py - api - Visual Studio Code"],
                     True, 0.02, weight=3.5),
            Scenario("windowsterminal.exe", "Terminal",
                     ["pytest - Windows Terminal", "git status - Windows Terminal"],
                     True, 0.06, weight=2.0),
            Scenario("chrome.exe", "Chrome",
                     ["python - how to retry a stripe webhook - Stack Overflow",
                      "idempotency keys - Stack Overflow"],
                     True, 0.22, conf=(0.45, 0.68), weight=1.6,
                     reason="Web browsing during coding session"),
            Scenario("chrome.exe", "Chrome",
                     ["stripe/stripe-python - GitHub", "Pull requests - api - GitHub"],
                     True, 0.14, weight=1.5),
            Scenario("chrome.exe", "Chrome",
                     ["Stripe webhooks tutorial - YouTube",
                      "Async Python explained - YouTube"],
                     True, 0.68, conf=(0.52, 0.80), weight=1.2,
                     reason="Video streaming site open"),
            Scenario("chrome.exe", "Chrome",
                     ["Hacker News", "Show HN: I built a thing - Hacker News"],
                     False, 0.55, conf=(0.45, 0.70), weight=1.1),
            Scenario("chrome.exe", "Chrome",
                     ["Counter-Strike 2 - Twitch", "Home - Twitch"],
                     False, 0.94, conf=(0.78, 0.97), weight=1.2),
        ],
    ),
    TaskFamily(
        "jobs",
        ["applying for jobs",
         "job applications this afternoon",
         "sending out job applications"],
        [
            Scenario("winword.exe", "Word",
                     ["cover-letter.docx - Word", "CV-2026.docx - Word"],
                     True, 0.03, weight=2.5),
            # LinkedIn is a social feed AND the tool for the job. The model cannot tell.
            Scenario("chrome.exe", "Chrome",
                     ["(3) Jobs - LinkedIn", "Backend Engineer at Acme - LinkedIn"],
                     True, 0.58, conf=(0.48, 0.75), weight=2.2,
                     reason="LinkedIn social feed visible"),
            Scenario("chrome.exe", "Chrome",
                     ["backend engineer jobs in Leeds - Indeed",
                      "Software Engineer - Glassdoor"],
                     True, 0.12, weight=1.8),
            Scenario("chrome.exe", "Chrome",
                     ["Inbox (12) - Gmail", "Application received - Gmail"],
                     True, 0.30, conf=(0.45, 0.68), weight=1.5,
                     reason="Email client open, not an application form"),
            Scenario("chrome.exe", "Chrome",
                     ["Best gaming laptops 2026 - Amazon", "Your Orders - Amazon"],
                     False, 0.88, conf=(0.70, 0.95), weight=1.2),
            Scenario("chrome.exe", "Chrome",
                     ["r/gaming - Reddit", "Popular - Reddit"],
                     False, 0.86, conf=(0.68, 0.93), weight=1.2),
        ],
    ),
]


class SimConfig:
    """Knobs for the generator. Defaults produce roughly a month of realistic use."""

    __slots__ = ("days", "sessions_per_day", "checks_per_session", "seed", "gamer",
                 "p_press_false_alarm", "p_press_correct", "p_press_missed",
                 "p_gamer_press", "start_ts")

    def __init__(self, **kw):
        self.days = 24
        self.sessions_per_day = 2
        self.checks_per_session = 26
        self.seed = 20260908
        self.gamer = False
        # How often a real, honest user actually presses the button. People under-report: most
        # false alarms are absorbed silently, which is precisely why the learner needs so few
        # confirmations to act.
        self.p_press_false_alarm = 0.72
        self.p_press_correct = 0.22
        self.p_press_missed = 0.12
        self.p_gamer_press = 0.85
        self.start_ts = None            # defaults to `days` ago from now
        for k, v in kw.items():
            if k not in self.__slots__:
                raise TypeError("unknown SimConfig option: %r" % (k,))
            setattr(self, k, v)


def _weighted_choice(rng, scenarios):
    total = sum(s.weight for s in scenarios)
    r = rng.random() * total
    upto = 0.0
    for s in scenarios:
        upto += s.weight
        if r <= upto:
            return s
    return scenarios[-1]


def generate(config=None):
    """Produce (rows, truth) where `rows` is the raw JSONL row stream in producer format.

    Ground truth rides on each judgement row as `truth_on_task`. That is an extra key the real
    monitor never writes; `store.normalise` preserves unknown keys, so the evaluator can read it
    back while the learner itself never looks at it -- which is the only way the offline score
    means anything.
    """
    config = config or SimConfig()
    rng = random.Random(config.seed)
    start = config.start_ts
    if start is None:
        start = time.time() - config.days * 86400.0

    rows = []
    counter = 0
    for day in range(config.days):
        day_base = start + day * 86400.0
        for session_no in range(config.sessions_per_day):
            family = FAMILIES[(day * config.sessions_per_day + session_no) % len(FAMILIES)]
            task = family.phrasings[rng.randrange(len(family.phrasings))]
            session_id = "fs_%02d%02d" % (day, session_no)
            # 09:00 and 15:00 local-ish, jittered.
            hour = 9 if session_no == 0 else 15
            t = day_base - (day_base % 86400.0) + hour * 3600.0 + rng.uniform(0, 1800)

            for _ in range(config.checks_per_session):
                counter += 1
                t += CHECK_INTERVAL * rng.uniform(0.85, 1.15)
                scen = _weighted_choice(rng, family.scenarios)
                title = scen.titles[rng.randrange(len(scen.titles))]

                flagged = rng.random() < scen.p_flag
                if flagged:
                    verdict = "off_task"
                    confidence = round(rng.uniform(scen.conf_lo, scen.conf_hi), 3)
                    reason = scen.reason or "screen does not match the declared task"
                    action = "blocked" if confidence >= APP_BLOCK_THRESHOLD else "logged"
                else:
                    verdict = "on_task"
                    confidence = round(rng.uniform(0.60, 0.95), 3)
                    reason = ""
                    action = "allowed"

                jid = "j_%d" % (int(t * 1000) + counter)
                rows.append({
                    "id": jid,
                    "ts": t,
                    "session_id": session_id,
                    "task": task,
                    "app": scen.app,
                    "app_name": scen.app_name,
                    "window_title": title,
                    "verdict": verdict,
                    "reason": reason,
                    "confidence": confidence,
                    "action": action,
                    "provider": "ollama:qwen3-vl:8b",
                    "feedback": None,
                    "feedback_at": None,
                    "feedback_note": None,
                    # --- label, not part of the real contract ---
                    "truth_on_task": scen.truth_on_task,
                })

                fb = _feedback_for(rng, config, scen, verdict, action)
                if fb is not None:
                    kind, delay, note = fb
                    rows.append({
                        "id": "%s#fb" % jid,
                        "ts": t + delay,
                        "ref": jid,
                        "feedback": kind,
                        "feedback_at": t + delay,
                        "feedback_note": note,
                    })
    return rows


def _feedback_for(rng, config, scen, verdict, action):
    """Decide whether the simulated human presses a button, which one, and how fast."""
    if action == "blocked":
        if scen.truth_on_task:
            if rng.random() < config.p_press_false_alarm:
                # A considered press: read the screen, recognise the mistake, tap the button.
                return ("false_alarm", rng.uniform(6.0, 45.0), "this is part of the work")
            return None
        # Correctly blocked. An honest user sometimes confirms it.
        if config.gamer and rng.random() < config.p_gamer_press:
            # The gaming behaviour we are defending against: instant, reflexive, and aimed at
            # exactly the screens the tool exists to stop.
            return ("false_alarm", rng.uniform(0.4, 2.4), "i was just taking a break")
        if rng.random() < config.p_press_correct:
            return ("correct", rng.uniform(5.0, 30.0), "")
        return None

    # Not blocked. The only feedback available is "you should have stopped me".
    if not scen.truth_on_task and rng.random() < config.p_press_missed:
        return ("missed", rng.uniform(30.0, 180.0), "shouldn't have been here")
    return None


def write(path, config=None):
    """Generate and write a judgements log. Returns (path, rows_written)."""
    rows = generate(config)
    store.write_rows(path, rows)
    return str(path), len(rows)


def summarise(rows):
    """Counts for the CLI, computed from the raw row stream."""
    judgements = [r for r in rows if not r.get("ref")]
    feedback = [r for r in rows if r.get("ref")]
    kinds = {}
    for r in feedback:
        kinds[r["feedback"]] = kinds.get(r["feedback"], 0) + 1
    blocked = [r for r in judgements if r["action"] == "blocked"]
    return {
        "judgements": len(judgements),
        "feedback_rows": len(feedback),
        "blocked": len(blocked),
        "blocked_but_on_task": sum(1 for r in blocked if r.get("truth_on_task")),
        "truly_off_task": sum(1 for r in judgements if not r.get("truth_on_task")),
        "false_alarm": kinds.get("false_alarm", 0),
        "correct": kinds.get("correct", 0),
        "missed": kinds.get("missed", 0),
        "tasks": sorted({r["task"] for r in judgements}),
    }
