"""The learner: three composable mechanisms, and the guard that keeps them honest.

WHAT IT LEARNS FROM
-------------------
One signal, pressed by a human on a block screen: `false_alarm` ("you were wrong to stop me"),
`correct` ("you were right"), `missed` ("you should have stopped me and didn't"). Everything
below is bookkeeping over those three verbs.

THE THREE MECHANISMS
--------------------
(a) EXEMPLAR MEMORY -- the strongest confirmed false alarms become short sentences appended to
    the classifier prompt, under the "PREVIOUSLY CONFIRMED BY THE USER" heading that
    `ai/providers.build_user_prompt` already renders. This is the cheapest mechanism to build and
    the only one that can generalise: telling the model "Chrome showing khanacademy.org is part
    of this task" also helps it on a Khan Academy page it has never seen. It is capped hard
    (1200 chars) because every character is paid for on every check, hundreds of times a session.

(b) SIGNATURE ALLOWANCES -- a (task-cluster, app, title-pattern) triple that has been confirmed a
    false alarm repeatedly, across separate days, becomes a pre-model decision: skip the check
    entirely (`pre_allow`) or run it but never block on it (`downgrade`). This is the mechanism
    that actually removes interruptions, because it does not depend on a model changing its mind.
    It is also the dangerous one, which is why it needs the most evidence and expires on its own.

(c) CONFIDENCE CALIBRATION -- a per-(task-cluster, app) block threshold. Off-task verdicts below
    the threshold are logged instead of blocked. False alarms push it up, `missed` feedback
    pushes it down twice as fast. Asymmetric on purpose: the user is asking a tool to stop them,
    and a tool that loosens as fast as it tightens will ratchet itself into uselessness.

They compose in that order at apply time: an allowance short-circuits the check, otherwise the
threshold decides blocking, and the exemplars ride along on every prompt regardless.

THE ANTI-GAMING GUARD  (read this before changing any number in LearnConfig)
---------------------------------------------------------------------------
The user of a self-control tool is not a neutral labeller. They are the person the tool exists to
stop, holding a button marked "stop stopping me". Every loosening path here is therefore rate
limited, capped, evidence-gated, expiring, and observable:

  1. RATE LIMIT      -- at most `max_credited_fa_per_day` false alarms per rolling 24h are
                        credited. Later presses are still recorded (they are evidence about the
                        USER) but teach nothing.
  2. REFLEX FILTER   -- a press within `reflex_seconds` of the block is not a considered judgement;
                        it is a reflex. Recorded, not credited.
  3. PER-SIGNATURE CAP -- one signature can bank at most `max_evidence_per_signature` credits.
                        Spamming the same block a hundred times buys nothing beyond the tenth.
  4. EVIDENCE SPREAD -- an allowance needs `allow_min_evidence` credits across at least
                        `allow_min_distinct_days` separate calendar days. One angry sitting cannot
                        unlock anything.
  5. CONTRADICTION   -- `correct` presses subtract from a signature's evidence; a single `missed`
                        on the same signature revokes its allowance outright.
  6. EXPIRY          -- allowances die `allow_ttl_days` after their last credited evidence. What
                        was true during exam season stops being true afterwards, silently.
  7. HARD CEILING    -- the block threshold can never exceed `threshold_ceiling` (0.85), so a
                        confident off-task verdict blocks no matter how much the policy has been
                        taught. There is no sequence of button presses that turns blocking off.
  8. NEVER-PRE-ALLOW -- a set of domains that are overwhelmingly leisure can reach `downgrade` at
                        most, never `pre_allow`. The check still runs and is still logged, so the
                        accountability partner still sees it.
  9. VISIBILITY      -- `integrity` in the compiled policy carries a gaming score and a plain
                        sentence for the app to push over ntfy. Learning being used to erode the
                        rules is itself reportable; that is the real deterrent, since every
                        mechanical limit above can eventually be waited out.
"""

import math
import time

from . import features as F

DAY = 86400.0


class LearnConfig:
    """Every tunable in one place. Defaults chosen to be slow to loosen and quick to tighten."""

    __slots__ = ("exemplar_budget_chars", "exemplar_max_lines", "exemplar_min_evidence",
                 "exemplar_half_life_days", "allow_min_evidence", "allow_min_distinct_days",
                 "allow_ttl_days", "base_threshold", "fa_step", "miss_step", "threshold_floor",
                 "threshold_ceiling", "calib_min_evidence", "window_days")

    def __init__(self, **kw):
        # (a) exemplars
        self.exemplar_budget_chars = 1200   # matches the prompt budget in ai/providers.py
        self.exemplar_max_lines = 8
        self.exemplar_min_evidence = 2      # one press is a hint; two is a pattern
        self.exemplar_half_life_days = 21.0
        # (b) allowances
        self.allow_min_evidence = 3
        self.allow_min_distinct_days = 2
        self.allow_ttl_days = 14.0
        # (c) calibration
        self.base_threshold = 0.55          # the app's un-learned default
        self.fa_step = 0.05                 # per credited false alarm
        self.miss_step = 0.10               # per `missed` -- twice as fast, on purpose
        self.threshold_floor = 0.30
        self.threshold_ceiling = 0.85       # guard 7: the hard ceiling
        self.calib_min_evidence = 2
        # how far back evidence is considered at all
        self.window_days = 45.0
        for k, v in kw.items():
            if k not in self.__slots__:
                raise TypeError("unknown LearnConfig option: %r" % (k,))
            setattr(self, k, v)


class GuardConfig:
    """The anti-gaming numbers, deliberately separated from LearnConfig.

    Split out so it is obvious in a diff when someone weakens the guard rather than tuning the
    learner. These are the numbers a motivated user would want changed.
    """

    __slots__ = ("max_credited_fa_per_day", "max_evidence_per_signature", "reflex_seconds",
                 "gaming_alert_score", "never_pre_allow_domains", "leisure_confidence",
                 "leisure_alert_rate", "leisure_alert_min", "cap_days_alert_min",
                 "cap_days_alert_rate")

    # Sites where "it was part of my work" is occasionally true and usually not. They can be
    # downgraded (checked, logged, not blocked) but never skipped, so a session spent here is
    # always visible in the log and to the accountability partner.
    NEVER_PRE_ALLOW_DOMAINS = frozenset({
        "youtube.com", "tiktok.com", "instagram.com", "netflix.com", "twitch.tv",
        "twitter.com", "x.com", "facebook.com", "pinterest.com", "reddit.com",
        "steampowered.com", "amazon.com",
    })

    def __init__(self, **kw):
        # 12, not 8. Measured, not guessed: with a model this eager an honest user produces
        # around ten real false alarms on a heavy day. A cap of 8 fired on them daily and pushed
        # the integrity score to 0.53 before anyone had done anything wrong. A limit that
        # routinely trips on the honest case is not a guard, it is noise, and it teaches
        # everyone to ignore the alert.
        self.max_credited_fa_per_day = 12    # guard 1
        self.max_evidence_per_signature = 6  # guard 3
        self.reflex_seconds = 3.0            # guard 2
        self.gaming_alert_score = 0.60       # guard 9
        self.never_pre_allow_domains = self.NEVER_PRE_ALLOW_DOMAINS   # guard 8

        # A press on a leisure domain is only suspicious when it argues with a CONFIDENT verdict.
        # "YouTube at 0.62" is the Khan Academy lecture this product exists to stop blocking;
        # "TikTok at 0.94" is someone telling the tool to look away. Counting both as gaming
        # flagged the honest user on 46% of their presses -- the worst false positive in the
        # first version of this scorer.
        self.leisure_confidence = 0.80
        self.leisure_alert_rate = 0.25
        self.leisure_alert_min = 5
        # Hitting the daily limit once in a bad week is a bad week. Hitting it on a fifth of the
        # days you give feedback at all is a pattern.
        self.cap_days_alert_min = 3
        self.cap_days_alert_rate = 0.20
        for k, v in kw.items():
            if k not in self.__slots__:
                raise TypeError("unknown GuardConfig option: %r" % (k,))
            setattr(self, k, v)


class SignatureState:
    """Accumulated evidence for one (task-cluster, app, title-pattern) triple."""

    __slots__ = ("key", "cluster", "app", "app_name", "pattern", "credited", "rejected",
                 "correct", "missed", "days", "first_ts", "last_ts", "examples", "titles")

    def __init__(self, key, cluster, app, pattern):
        self.key = key
        self.cluster = cluster
        self.app = app
        self.app_name = ""
        self.pattern = pattern
        self.credited = 0            # false alarms that passed the guard
        self.rejected = 0            # false alarms the guard refused to credit
        self.correct = 0             # user agreed the block was right
        self.missed = 0              # user said this should have been blocked
        self.days = set()            # distinct calendar days of credited evidence
        self.first_ts = None
        self.last_ts = None
        self.examples = []           # a few window titles, for `explain` and the README
        self.titles = set()

    @property
    def net_evidence(self):
        """Credits minus contradictions. `correct` on the same signature means the user has
        agreed, at least once, that this exact screen was a real distraction -- that has to cost
        something, or a signature can be argued into an allowance while the user openly admits
        it is off task."""
        return self.credited - self.correct

    def note(self, feat, credited):
        ts = feat.ts
        if self.first_ts is None or ts < self.first_ts:
            self.first_ts = ts
        if self.last_ts is None or ts > self.last_ts:
            self.last_ts = ts
        if feat.app_name and not self.app_name:
            self.app_name = feat.app_name
        if credited:
            self.days.add(feat.day())
        if feat.title and feat.title not in self.titles and len(self.examples) < 3:
            self.titles.add(feat.title)
            self.examples.append(feat.title)


class ThresholdState:
    """Calibration counters for one (task-cluster, app) pair."""

    __slots__ = ("cluster", "app", "app_name", "credited_fa", "missed", "correct", "blocks",
                 "off_task")

    def __init__(self, cluster, app):
        self.cluster = cluster
        self.app = app
        self.app_name = ""
        self.credited_fa = 0
        self.missed = 0
        self.correct = 0
        self.blocks = 0
        self.off_task = 0


class Integrity:
    """The gaming assessment. Compiled into the policy so the client can act on it."""

    __slots__ = ("score", "flags", "notify_partner", "headline", "counters")

    def __init__(self):
        self.score = 0.0
        self.flags = []
        self.notify_partner = False
        self.headline = ""
        self.counters = {}


class LearnedState:
    """Everything the learner derived from one log. `policy.compile_policy` turns this into JSON."""

    __slots__ = ("config", "guard", "clusterer", "signatures", "thresholds", "integrity",
                 "now", "stats", "feedback_events")

    def __init__(self, config, guard):
        self.config = config
        self.guard = guard
        self.clusterer = F.TaskClusterer()
        self.signatures = {}          # key -> SignatureState
        self.thresholds = {}          # (cluster, app) -> ThresholdState
        self.integrity = Integrity()
        self.now = 0.0
        self.stats = {}
        self.feedback_events = []     # audit trail: every press and what the guard did with it


def _decay(age_days, half_life_days):
    """Exponential recency weight. Half-life rather than a cutoff, so an exemplar fades out
    instead of vanishing between two runs of the learner."""
    if half_life_days <= 0:
        return 1.0
    return math.pow(0.5, max(age_days, 0.0) / half_life_days)


def learn(rows, config=None, guard=None, now=None):
    """Derive a LearnedState from folded judgement rows.

    `now` defaults to the newest timestamp in the data rather than wall-clock time. That makes the
    whole pipeline reproducible: re-running the learner over a fixed log next week must produce
    the same policy, or the evaluation harness measures the calendar instead of the mechanism.
    """
    config = config or LearnConfig()
    guard = guard or GuardConfig()
    state = LearnedState(config, guard)

    rows = [r for r in rows if r.get("ts")]
    if not rows:
        state.now = float(now or time.time())
        state.stats = _empty_stats()
        return state

    state.now = float(now) if now is not None else max(r["ts"] for r in rows)
    horizon = state.now - config.window_days * DAY

    # Cluster over every task string in the log, in sorted order, so clusters do not depend on
    # the order the file happened to be written in.
    state.clusterer = F.TaskClusterer.from_tasks(r.get("task", "") for r in rows)

    feats = []
    for r in rows:
        if r["ts"] < horizon:
            continue
        f = F.features_of(r)
        cluster, _score = state.clusterer.match(f.task)
        feats.append((f, cluster))

    # --- pass 1: counters that need no guard decision -----------------------------------------
    for f, cluster in feats:
        th = _threshold_state(state, cluster, f.app)
        if f.app_name and not th.app_name:
            th.app_name = f.app_name
        if f.verdict == "off_task":
            th.off_task += 1
        if f.action == "blocked":
            th.blocks += 1

    # --- pass 2: the guard, applied to feedback in strict time order --------------------------
    # Time order matters: the rolling daily cap is a function of what has already been credited,
    # so processing out of order would credit a different set of presses.
    press_times = []            # credited-press timestamps, for the rolling 24h window
    per_day_capped = set()      # calendar days on which the cap actually bit
    press_days = set()          # calendar days with any false-alarm press (the cap denominator)
    denylist_presses = 0
    reflex_presses = 0
    fa_total = 0
    blocks_total = sum(1 for f, _ in feats if f.action == "blocked")

    ordered = sorted(feats, key=lambda fc: (fc[0].feedback_at or fc[0].ts, fc[0].raw.get("id", "")))
    for f, cluster in ordered:
        if not f.feedback:
            continue
        sig_key = F.signature_key(cluster, f.app, f.pattern)
        sig = state.signatures.get(sig_key)
        if sig is None:
            sig = SignatureState(sig_key, cluster, f.app, f.pattern)
            state.signatures[sig_key] = sig
        th = _threshold_state(state, cluster, f.app)

        if f.feedback == "missed":
            # The tightening signal. No guard, no rate limit, no cap: the user asking to be
            # stopped MORE is never something to be sceptical about.
            sig.missed += 1
            th.missed += 1
            sig.note(f, credited=False)
            state.feedback_events.append(_event(f, sig_key, "missed", True, ""))
            continue

        if f.feedback == "correct":
            sig.correct += 1
            th.correct += 1
            sig.note(f, credited=False)
            state.feedback_events.append(_event(f, sig_key, "correct", True, ""))
            continue

        # --- false_alarm: the only path that can loosen anything ------------------------------
        fa_total += 1
        press_days.add(_day_of(f.feedback_at if f.feedback_at is not None else f.ts))
        if (f.domain and f.domain in guard.never_pre_allow_domains
                and f.confidence >= guard.leisure_confidence):
            denylist_presses += 1

        reason = ""
        press_at = f.feedback_at if f.feedback_at is not None else f.ts
        if press_at - f.ts < guard.reflex_seconds:
            reason = "reflex"                                   # guard 2
            reflex_presses += 1
        elif sig.credited >= guard.max_evidence_per_signature:
            reason = "signature_cap"                            # guard 3
        else:
            recent = [t for t in press_times if press_at - t < DAY]
            if len(recent) >= guard.max_credited_fa_per_day:
                reason = "daily_cap"                            # guard 1
                per_day_capped.add(_day_of(press_at))
            press_times = recent

        if reason:
            sig.rejected += 1
            sig.note(f, credited=False)
            state.feedback_events.append(_event(f, sig_key, "false_alarm", False, reason))
            continue

        sig.credited += 1
        th.credited_fa += 1
        sig.note(f, credited=True)
        press_times.append(press_at)
        state.feedback_events.append(_event(f, sig_key, "false_alarm", True, ""))

    state.integrity = _assess_integrity(
        guard, fa_total=fa_total, blocks=blocks_total, reflex=reflex_presses,
        rejected=sum(s.rejected for s in state.signatures.values()),
        denylist=denylist_presses, capped_days=len(per_day_capped),
        press_days=len(press_days), allowances=sum(1 for s in state.signatures.values()
                       if _allowance_ready(s, config, guard)[0]))

    state.stats = {
        "rows": len(rows),
        "in_window": len(feats),
        "blocks": blocks_total,
        "false_alarms": fa_total,
        "false_alarms_credited": sum(s.credited for s in state.signatures.values()),
        "false_alarms_rejected": sum(s.rejected for s in state.signatures.values()),
        "correct": sum(s.correct for s in state.signatures.values()),
        "missed": sum(s.missed for s in state.signatures.values()),
        "signatures": len(state.signatures),
        "clusters": len(state.clusterer.clusters),
    }
    return state


def _empty_stats():
    return {"rows": 0, "in_window": 0, "blocks": 0, "false_alarms": 0,
            "false_alarms_credited": 0, "false_alarms_rejected": 0, "correct": 0,
            "missed": 0, "signatures": 0, "clusters": 0}


def _event(f, sig_key, kind, credited, reason):
    return {"ts": f.ts, "signature": sig_key, "feedback": kind,
            "credited": bool(credited), "reason": reason, "title": f.title[:80]}


def _day_of(ts):
    t = time.localtime(float(ts))
    return t.tm_year * 10000 + t.tm_mon * 100 + t.tm_mday


def _threshold_state(state, cluster, app):
    key = (cluster, app)
    th = state.thresholds.get(key)
    if th is None:
        th = ThresholdState(cluster, app)
        state.thresholds[key] = th
    return th


# -------------------------------------------------------------------------------------------
# (b) allowances
# -------------------------------------------------------------------------------------------

def _allowance_ready(sig, config, guard):
    """Does this signature qualify for an allowance, and at what strength?

    Returns (ok, action, why). `why` is human-readable and ends up in `explain` output, because
    "why am I still being blocked on this" is the first question a user asks of a learning tool.
    """
    if sig.missed > 0:
        return False, None, "revoked: you said this one should have been blocked"   # guard 5
    if sig.net_evidence < config.allow_min_evidence:
        return False, None, ("needs %d confirmations, has %d"
                             % (config.allow_min_evidence, max(sig.net_evidence, 0)))
    if len(sig.days) < config.allow_min_distinct_days:
        return False, None, ("needs confirmations on %d separate days, has %d"
                             % (config.allow_min_distinct_days, len(sig.days)))     # guard 4

    action = "pre_allow"
    why = "confirmed %d times across %d days" % (sig.net_evidence, len(sig.days))
    # guard 8 and the breadth rule: only a specific, non-leisure pattern earns a skipped check.
    if sig.pattern["kind"] == "app":
        action = "downgrade"
        why += "; pattern is the whole app, so the check still runs"
    elif sig.pattern["kind"] == "domain" and sig.pattern["value"] in guard.never_pre_allow_domains:
        action = "downgrade"
        why += "; %s is never skipped outright" % sig.pattern["value"]
    return True, action, why


# Reverse of features.SITE_NAMES: domain -> the brand names that appear in window titles.
_BRANDS_BY_DOMAIN = {}
for _name, _domain in F.SITE_NAMES:
    _BRANDS_BY_DOMAIN.setdefault(_domain, []).append(_name)


def title_patterns_for(sig):
    """Lowercase title substrings the non-Python clients can match with `contains`.

    The Swift and Kotlin clients cannot compute a title pattern -- they have no tokeniser and no
    site table -- so a `pre_allow` in the compiled `decisions` map has to carry literal substrings
    for them to test. Getting these wrong is not a cosmetic problem: too loose and a client skips
    a check the reference `apply()` would have run.

    So domain patterns are ANCHORED TO THE TITLE TAIL, taken from titles actually observed on
    this signature ("- khan academy", "| stack overflow"). The naive version -- emit the bare
    brand name "khan academy" -- makes a client pre-allow "Integration by parts | Khan Academy -
    YouTube", which is a YouTube page that `apply()` correctly refuses to skip. Anchoring the
    substring to the separator reproduces "the site is the last thing in the title", which is the
    entire meaning of a domain pattern.
    """
    kind, value = sig.pattern["kind"], sig.pattern["value"]
    if kind == "app":
        return []
    if kind == "tokens":
        return sorted(set(value.split("+")))

    patterns = set()
    for title in sig.examples:
        text = F.normalise_text(title)
        if value in text:
            patterns.add(value)                      # the literal domain was in the title
            continue
        found = F._last_separator(text)
        if found:
            tail = text[found[1]:].strip()
            if tail:
                patterns.add(text[found[0]:found[1]] + tail)   # e.g. " - khan academy"
    if not patterns:
        # No separator anywhere in any observed title: fall back to the brand names, which is
        # looser but is all the information there is.
        patterns.update(_BRANDS_BY_DOMAIN.get(value, [value]))
    return sorted(patterns)


def allowances(state):
    """Compiled allowance records, newest evidence first. Expired ones are simply not emitted."""
    out = []
    ttl = state.config.allow_ttl_days * DAY
    for key in sorted(state.signatures):
        sig = state.signatures[key]
        ok, action, why = _allowance_ready(sig, state.config, state.guard)
        if not ok:
            continue
        expires_at = (sig.last_ts or state.now) + ttl
        if expires_at <= state.now:
            continue                                            # guard 6
        out.append({
            "key": sig.key,
            "cluster": sig.cluster,
            "app": sig.app,
            "app_name": sig.app_name,
            "pattern": dict(sig.pattern),
            "action": action,
            "title_patterns": title_patterns_for(sig),
            "evidence": sig.net_evidence,
            "distinct_days": len(sig.days),
            "rejected_presses": sig.rejected,
            "last_evidence_at": sig.last_ts,
            "expires_at": expires_at,
            "why": why,
        })
    out.sort(key=lambda a: (-(a["last_evidence_at"] or 0.0), a["key"]))
    return out


# -------------------------------------------------------------------------------------------
# (c) calibration
# -------------------------------------------------------------------------------------------

def threshold_for(th, config):
    """The calibration maths, isolated so the unit tests can drive it directly.

    threshold = base + fa_step*credited_false_alarms - miss_step*missed,  clamped.

    Linear rather than Bayesian on purpose. A Beta-posterior would be defensible and would be a
    nightmare to port and to explain to the person it is blocking; "each false alarm you confirm
    moves the bar 5 points, each miss moves it back 10" is a sentence a user can hold in their
    head, and being explainable is worth more here than being optimal.

    The credited-false-alarm term is capped so that the ceiling is reachable but never exceeded
    even before clamping -- that keeps the arithmetic honest in the tests as well as in effect.
    """
    span = config.threshold_ceiling - config.base_threshold
    max_fa_steps = int(math.ceil(span / config.fa_step)) if config.fa_step > 0 else 0
    fa = min(th.credited_fa, max_fa_steps)
    raw = config.base_threshold + config.fa_step * fa - config.miss_step * th.missed
    return round(min(max(raw, config.threshold_floor), config.threshold_ceiling), 4)


def thresholds(state):
    """Compiled per-(cluster, app) thresholds. Pairs with no feedback are left out so the client
    falls back to the default -- shipping a table of identical defaults would just bloat the file."""
    out = []
    config = state.config
    for (cluster, app) in sorted(state.thresholds):
        th = state.thresholds[(cluster, app)]
        if th.credited_fa + th.missed < config.calib_min_evidence:
            continue
        value = threshold_for(th, config)
        if abs(value - config.base_threshold) < 1e-9:
            continue
        out.append({
            "cluster": cluster,
            "app": app,
            "app_name": th.app_name,
            "block_threshold": value,
            "false_alarms": th.credited_fa,
            "missed": th.missed,
            "blocks_seen": th.blocks,
        })
    return out


# -------------------------------------------------------------------------------------------
# (a) exemplars
# -------------------------------------------------------------------------------------------

def _pattern_phrase(sig):
    kind = sig.pattern["kind"]
    if kind == "domain":
        return sig.pattern["value"]
    if kind == "tokens":
        return '"%s" in the window title' % sig.pattern["value"].replace("+", " ")
    return "any window"


def exemplar_line(sig):
    """One sentence for the prompt's "PREVIOUSLY CONFIRMED BY THE USER" block.

    Phrased as a settled fact about THIS user, not as an instruction, because the surrounding
    prompt already says "treat these as settled" and a second imperative just gives a small model
    something to argue with. The confirmation count is included deliberately: it gives the model
    a reason to trust the line, and it gives a human reading the prompt an audit trail.
    """
    app = sig.app_name or sig.app or "this app"
    times = "once" if sig.net_evidence == 1 else "%d times" % sig.net_evidence
    return "- %s showing %s is part of this task (you confirmed %s)." % (
        app, _pattern_phrase(sig), times)


def exemplars(state):
    """Ranked exemplar candidates per cluster.

    Ranking is evidence x recency, computed here; the CLIENT re-ranks by keyword overlap with the
    task the user actually typed and then fills the character budget (see `policy.apply`). Two
    stages because relevance to the *current* task can only be judged at apply time -- one policy
    file serves every task the user ever declares.
    """
    out = []
    config = state.config
    for key in sorted(state.signatures):
        sig = state.signatures[key]
        if sig.missed > 0:
            continue                       # contradicted; never put it in the prompt
        if sig.net_evidence < config.exemplar_min_evidence:
            continue
        age_days = max(state.now - (sig.last_ts or state.now), 0.0) / DAY
        weight = sig.net_evidence * _decay(age_days, config.exemplar_half_life_days)
        line = exemplar_line(sig)
        if len(line) > 200:
            continue                       # a pathological title; not worth the prompt budget
        cluster = state.clusterer
        label = ""
        for c in cluster.clusters:
            if c["id"] == sig.cluster:
                label = c["label"]
                break
        out.append({
            "cluster": sig.cluster,
            "keywords": F.task_keywords(label),
            "text": line,
            "weight": round(weight, 4),
            "evidence": sig.net_evidence,
            "last_evidence_at": sig.last_ts,
            "signature": sig.key,
        })
    out.sort(key=lambda e: (e["cluster"], -e["weight"], e["signature"]))
    # Keep a generous multiple of the per-check line cap: the client picks the relevant subset,
    # so the file should hold more than any single check will use.
    per_cluster, kept = {}, []
    for e in out:
        n = per_cluster.get(e["cluster"], 0)
        if n >= config.exemplar_max_lines * 3:
            continue
        per_cluster[e["cluster"]] = n + 1
        kept.append(dict(e, keywords=list(e["keywords"])))
    return kept


# -------------------------------------------------------------------------------------------
# guard 9: is learning being used to erode the rules?
# -------------------------------------------------------------------------------------------

def _assess_integrity(guard, fa_total, blocks, reflex, rejected, denylist, capped_days,
                      press_days, allowances):
    """Score 0..1 for "this feedback stream looks like someone dismantling the tool".

    Every component is a RATE, not a count, so a heavy user is not accused of gaming merely for
    using the app a lot. The weights are a judgement call and are documented as such in the
    README; what matters more than their exact values is that the score is computed from the
    same log the policy is, so it cannot be hidden by turning learning off afterwards.
    """
    integrity = Integrity()
    if fa_total <= 0:
        integrity.counters = {"false_alarms": 0, "blocks": blocks}
        return integrity

    reject_rate = fa_total / float(max(blocks, 1))       # pressing "wrong" on most blocks
    reflex_rate = reflex / float(fa_total)               # not reading the block screen
    capped_rate = rejected / float(fa_total)             # constantly hitting the limits
    denylist_rate = denylist / float(fa_total)           # arguing for leisure sites

    components = (
        (min(reject_rate / 0.70, 1.0), 0.30,
         "%.0f%% of blocks are being marked a false alarm" % (100 * min(reject_rate, 1.0))),
        (min(reflex_rate / 0.40, 1.0), 0.25,
         "%.0f%% of presses came in under %.0fs" % (100 * reflex_rate, guard.reflex_seconds)),
        (min(capped_rate / 0.40, 1.0), 0.25,
         "%.0f%% of presses hit a rate limit or cap" % (100 * capped_rate)),
        (min(denylist_rate / 0.30, 1.0), 0.20,
         "%.0f%% of presses argue with a confident verdict on a leisure site"
         % (100 * denylist_rate)),
    )
    score = sum(v * w for v, w, _ in components)
    integrity.score = round(min(max(score, 0.0), 1.0), 3)
    integrity.flags = [text for v, _, text in components if v >= 0.5]
    integrity.counters = {
        "false_alarms": fa_total,
        "blocks": blocks,
        "reflex_presses": reflex,
        "rejected_presses": rejected,
        "confident_leisure_presses": denylist,
        "days_rate_limited": capped_days,
        "days_with_feedback": press_days,
        "active_allowances": allowances,
    }

    # Hard trips: conditions alarming regardless of the weighted score. Both are stated as a
    # count AND a rate, so a long-running honest user cannot accumulate their way into an
    # accusation simply by using the app for months.
    if (capped_days >= guard.cap_days_alert_min
            and capped_days >= guard.cap_days_alert_rate * max(press_days, 1)):
        integrity.flags.append("daily feedback limit reached on %d of %d days with feedback"
                               % (capped_days, press_days))
        integrity.notify_partner = True
    if denylist >= guard.leisure_alert_min and denylist_rate >= guard.leisure_alert_rate:
        integrity.flags.append(
            "%d presses (%.0f%%) arguing with a confident off-task verdict on a leisure site"
            % (denylist, 100 * denylist_rate))
        integrity.notify_partner = True
    if integrity.score >= guard.gaming_alert_score:
        integrity.notify_partner = True

    if integrity.notify_partner:
        integrity.headline = (
            "Focus learning is being pushed hard: " + "; ".join(integrity.flags[:3]) + ".")
    return integrity
