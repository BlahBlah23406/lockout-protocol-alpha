"""Compile learned state into `focus_policy.json`, and apply it the way a client must.

`apply()` is the reference implementation. `windows/guardian/focus/learned.py` calls straight
into it, and the macOS (Swift) and Android (Kotlin) ports are meant to be transliterations of
this one function -- which is the entire reason the policy file contains no weights, no vectors
and no float trickery beyond addition and comparison.

WHAT THE CLIENT GUARANTEES, AND WHY WE STILL DO IT HERE
-------------------------------------------------------
The shipping client independently clamps `block_threshold` to 0.85, truncates `prompt_suffix` to
1200 characters, and ignores a policy whose `schema` is not 1 or whose `generated_at` is more
than 60 days old. Those limits are duplicated here on purpose. Not defensive programming for its
own sake: the client's copy exists so that hand-editing the generated file cannot lift the limit,
and ours exists so the OFFLINE evaluation measures the same policy the app would actually run.
If only one side enforced them, the numbers in the README would be measuring a different product.

THE ONE DESIGN DECISION WORTH ARGUING ABOUT
-------------------------------------------
`block_threshold` is returned as 0.0 -- "no opinion" -- for any (task, app) the learner has no
evidence about, rather than as the learner's internal 0.55 anchor. The client's un-learned
default is 0.0 (block every clean off-task verdict), so returning 0.55 everywhere would mean
switching learning ON silently loosened the monitor across the board, before it had learned
anything at all. A learning feature whose first act is to weaken the tool is a bug, however
well-motivated the number.

The direct consequence, stated plainly because it is easy to miss: against a client default of
0.0, calibration can only ever LOOSEN. A `missed`-driven threshold of 0.40 is still above 0.0, so
it changes nothing. Calibration's tightening direction only becomes real if the app adopts a
non-zero default. See "Limitations" in the README.
"""

import json
import os
import tempfile
import time

from . import features as F
from . import learn as L

SCHEMA = 1
GENERATOR = "learner/policy.py v1"

# Mirrors of the client's limits (windows/guardian/focus/learned.py).
MAX_THRESHOLD = 0.85
MAX_SUFFIX_CHARS = 1200
POLICY_MAX_AGE_DAYS = 60

# "No opinion": the client keeps its own default blocking rule.
NO_OPINION = 0.0

_EMPTY = {"prompt_suffix": "", "pre_allow": False, "block_threshold": NO_OPINION}


# -------------------------------------------------------------------------------------------
# compile
# -------------------------------------------------------------------------------------------

def compile_policy(state, generated_at=None):
    """Turn a `learn.LearnedState` into the portable dict written to `focus_policy.json`.

    `generated_at` defaults to the learner's notion of "now" (the newest judgement), NOT to
    wall-clock time, so re-running the learner over a fixed log is byte-reproducible. The CLI
    passes wall-clock time when writing a policy for the real app, because the client's 60-day
    staleness check has to be measured against the calendar.
    """
    config, guard = state.config, state.guard
    allow = L.allowances(state)
    exes = L.exemplars(state)
    ths = L.thresholds(state)

    integrity = state.integrity
    policy = {
        "schema": SCHEMA,
        "generated_at": float(generated_at if generated_at is not None else state.now),
        "generator": GENERATOR,

        # Read by the client's status line; kept at the top level so it can be shown without
        # understanding anything else in the file.
        "exemplar_count": len(exes),
        "signature_count": len(allow),

        "defaults": {
            # 0.0 = no opinion; see the module docstring.
            "block_threshold": NO_OPINION,
            "calibration_base": config.base_threshold,
            "threshold_floor": config.threshold_floor,
            "threshold_ceiling": min(config.threshold_ceiling, MAX_THRESHOLD),
            "cluster_match_threshold": state.clusterer.threshold,
            "exemplar_budget_chars": min(config.exemplar_budget_chars, MAX_SUFFIX_CHARS),
            "exemplar_max_lines": config.exemplar_max_lines,
        },

        "clusters": state.clusterer.export(),
        "exemplars": exes,
        "allowances": allow,
        "thresholds": ths,
        # Filled in below: it is compiled FROM the four lists above, so they must exist first.
        "decisions": {},

        "integrity": {
            "score": integrity.score,
            "notify_partner": bool(integrity.notify_partner),
            "headline": integrity.headline,
            "flags": list(integrity.flags),
            "counters": dict(integrity.counters),
        },
        "stats": dict(state.stats),
    }
    policy["decisions"] = build_decisions(state, policy)
    return policy


# ---------------------------------------------------------------------------------------------
# The pre-expanded `decisions` map, for clients that cannot call `apply()`
# ---------------------------------------------------------------------------------------------

# Exactly the stopword list in `macos/Guardian/Focus/LearnedPolicy.swift`. It is NOT the learner's
# own stopword list and must not be "improved" into it: both sides of a lookup key have to agree
# character for character, and the Swift side is already shipped.
LOOKUP_STOPWORDS = frozenset(
    "the a an my for on to of and in working work doing do some this that".split())
LOOKUP_MAX_WORDS = 4
LOOKUP_MIN_WORD_LEN = 3          # Swift: `$0.count > 2`


def lookup_key(task, app):
    """Mirror of `LearnedPolicy.lookupKey` in Swift, character for character.

    Lowercase, every non-alphanumeric becomes a space, drop the Swift stopwords and any word of
    two characters or fewer, keep the first four, join with "-", append "|<app>".

    Note there is no stemming here, unlike the learner's own clustering. That is deliberate, and
    it is why the map carries one key per OBSERVED PHRASING: "math test prep" and "studying for
    my math test" are one cluster to the learner and two unrelated keys to Swift, so the compiler
    emits both, pointing at the same decision.
    """
    chars = [c if c.isalnum() else " " for c in (task or "").lower()]
    words = [w for w in "".join(chars).split()
             if w not in LOOKUP_STOPWORDS and len(w) >= LOOKUP_MIN_WORD_LEN]
    return "%s|%s" % ("-".join(words[:LOOKUP_MAX_WORDS]), (app or "").strip().lower())


def build_decisions(state, base_policy):
    """Compile the (task-phrasing, app) -> decision table the Swift/Kotlin clients read.

    THE MAP IS A LOSSY PROJECTION OF `apply()`, AND IT IS LOSSY IN ONE DIRECTION ONLY.

    It is keyed by (task, app) with no title, so it cannot express anything title-scoped. Two
    consequences, both resolved towards being STRICTER than the reference implementation, because
    a portable table that is looser than `apply()` would mean the Mac quietly monitoring less than
    the PC from the same policy file:

      * A `downgrade` allowance raises `apply()`'s threshold to the ceiling for ONE title pattern.
        The map cannot say "only for this title", so it does not raise the threshold at all and
        emits only the calibrated (task, app) value. A downgraded YouTube page still blocks on
        macOS where it would not on Windows.
      * `pre_allow` is emitted only for DOMAIN-kind allowances, never token-kind ones. A client
        matches `title_patterns` with a substring test, which ORs the two tokens of a token
        pattern where `apply()` requires both. Rather than ship a looser rule, token-kind
        allowances degrade to a normal check on those platforms.

    `test_decisions_map_is_never_looser_than_apply` asserts the invariant over a whole simulated
    log: for every screen, the map never pre-allows what `apply()` would not, and never returns a
    higher threshold than `apply()` does.

    No "*" wildcard rows are emitted. The format supports them and the clients look for them, but
    a wildcard row carrying a real pre_allow or threshold would fire on tasks the learner has
    never seen -- exactly where `apply()` deliberately returns "no learning" -- and that is the
    looser-than-apply case the invariant forbids. A wildcard needs its own evidence rule ("this
    app was excused under every task this user has ever declared"), not a default.
    """
    allow_by_pair, patterns_by_pair = {}, {}
    for a in base_policy.get("allowances") or []:
        pair = (a["cluster"], a["app"])
        if (a["action"] == "pre_allow" and a["pattern"]["kind"] == "domain"
                and a.get("title_patterns")):
            allow_by_pair[pair] = True
            patterns_by_pair.setdefault(pair, set()).update(a["title_patterns"])

    threshold_by_pair = {(t["cluster"], t["app"]): t["block_threshold"]
                         for t in base_policy.get("thresholds") or []}

    # Every app the cluster has learned anything about. An app with only exemplars still earns a
    # row: on a platform that cannot pre-allow, the prompt suffix is most of the value.
    apps_by_cluster = {}
    for pair in list(allow_by_pair) + list(threshold_by_pair):
        apps_by_cluster.setdefault(pair[0], set()).add(pair[1])
    for sig in state.signatures.values():
        if sig.credited > 0:
            apps_by_cluster.setdefault(sig.cluster, set()).add(sig.app)

    decisions = {}
    for cluster in sorted(apps_by_cluster):
        phrasings = _phrasings(state, cluster)
        for app in sorted(apps_by_cluster[cluster]):
            pair = (cluster, app)
            entry_base = {
                "pre_allow": bool(allow_by_pair.get(pair)),
                "block_threshold": min(float(threshold_by_pair.get(pair, NO_OPINION)),
                                       MAX_THRESHOLD),
                "title_patterns": sorted(patterns_by_pair.get(pair, ())),
            }
            for phrasing in phrasings:
                key = lookup_key(phrasing, app)
                if key.startswith("|"):
                    continue                    # a task of pure stopwords keys to nothing usable
                entry = dict(entry_base)
                entry["prompt_suffix"] = build_prompt_suffix(base_policy, phrasing, cluster)
                if not (entry["prompt_suffix"] or entry["pre_allow"]
                        or entry["block_threshold"]):
                    continue                    # an all-defaults row teaches a client nothing
                decisions[key] = entry
    return decisions


def _phrasings(state, cluster):
    for c in state.clusterer.clusters:
        if c["id"] == cluster:
            return sorted(set(c["members"]))
    return []


def decision_for(policy, task="", app="", title=""):
    """The Swift/Kotlin client's lookup, reimplemented here so the two can be tested against each
    other. Returns the same three keys as `apply()`."""
    result = dict(_EMPTY)
    if not isinstance(policy, dict) or policy.get("schema") != SCHEMA:
        return result
    decisions = policy.get("decisions")
    if not isinstance(decisions, dict):
        return result
    app_l = (app or "").strip().lower()
    entry = decisions.get(lookup_key(task, app_l)) or decisions.get("*|%s" % app_l)
    if not isinstance(entry, dict):
        return result

    result["prompt_suffix"] = str(entry.get("prompt_suffix") or "")[:MAX_SUFFIX_CHARS]
    result["block_threshold"] = min(max(_float(entry.get("block_threshold"), 0.0), 0.0),
                                    MAX_THRESHOLD)
    pre_allow = bool(entry.get("pre_allow"))
    if pre_allow:
        # The client refuses a pre_allow with no title evidence behind it: an app-wide skip would
        # silently un-watch a whole application.
        patterns = [p for p in (entry.get("title_patterns") or []) if isinstance(p, str) and p]
        low = (title or "").lower()
        pre_allow = bool(patterns) and any(p.lower() in low for p in patterns)
    result["pre_allow"] = pre_allow
    return result


def save_policy(path, policy):
    """Atomic write with stable key order, so a diff of two policies is readable."""
    directory = os.path.dirname(os.path.abspath(str(path))) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(policy, fh, indent=2, sort_keys=True, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_policy(path):
    """Read a policy, returning {} for anything we can't or shouldn't use.

    Same acceptance rules as the client: right schema, not stale, is an object. Returning {}
    rather than raising is the whole contract -- a broken policy file must degrade to "no
    learning", never to "no monitoring".
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return {}
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        return {}
    generated = data.get("generated_at")
    if isinstance(generated, (int, float)):
        if time.time() - generated > POLICY_MAX_AGE_DAYS * 86400:
            return {}
    return data


# -------------------------------------------------------------------------------------------
# apply -- the reference client
# -------------------------------------------------------------------------------------------

def match_cluster(policy, task):
    """Best task cluster for a freehand task string, or ("tc_none", score).

    Deliberately re-implemented over the compiled `clusters` list rather than reusing
    `TaskClusterer`, because this is the code path a Swift/Kotlin port has to reproduce and it
    must depend on nothing but the JSON: tokenise, stem, containment against each stored
    phrasing, take the best above threshold.
    """
    clusters = policy.get("clusters") or []
    threshold = _float(policy.get("defaults", {}).get("cluster_match_threshold"),
                       F.TaskClusterer.THRESHOLD)
    kw = F.task_keywords(task)
    if not kw or not clusters:
        return "tc_none", 0.0
    best_id, best_score = "tc_none", 0.0
    for c in clusters:
        # Single linkage over the stored phrasings, matching TaskClusterer._best exactly. The
        # union is the fallback for a policy written before `keyword_sets` existed.
        sets = c.get("keyword_sets") or [c.get("keywords") or []]
        score = max(F.overlap(kw, ks) for ks in sets) if sets else 0.0
        cid = str(c.get("id") or "")
        # Ties broken by id so two clusters with equal overlap resolve the same way everywhere.
        if score > best_score or (score == best_score and score > 0.0 and cid < best_id):
            best_id, best_score = cid, score
    if best_score < threshold:
        return "tc_none", best_score
    return best_id, best_score


def _float(v, default):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _active_allowance(policy, cluster, app, pattern, ts):
    """The matching, unexpired allowance for this exact signature, or None."""
    key = F.signature_key(cluster, app, pattern)
    for a in policy.get("allowances") or []:
        if a.get("key") != key:
            continue
        expires = a.get("expires_at")
        if isinstance(expires, (int, float)) and ts >= expires:
            return None                      # guard 6: expiry is enforced at APPLY time too,
                                             # so a policy that is not recompiled still decays
        return a
    return None


def _learned_threshold(policy, cluster, app):
    for t in policy.get("thresholds") or []:
        if t.get("cluster") == cluster and (t.get("app") or "") == (app or ""):
            return _float(t.get("block_threshold"), None)
    return None


def build_prompt_suffix(policy, task, cluster, budget=None, max_lines=None):
    """Pick the exemplars worth spending prompt budget on for THIS task.

    Two-stage relevance, as designed in `learn.exemplars`: the compiler ranked by evidence and
    recency, and here we re-weight by how much the exemplar's own task overlaps the task the user
    actually typed. That second stage is what stops a user with four active projects from
    spending their whole 1200 characters telling the model about the other three.
    """
    defaults = policy.get("defaults") or {}
    budget = int(budget if budget is not None
                 else min(_float(defaults.get("exemplar_budget_chars"), MAX_SUFFIX_CHARS),
                          MAX_SUFFIX_CHARS))
    max_lines = int(max_lines if max_lines is not None
                    else _float(defaults.get("exemplar_max_lines"), 8))
    if cluster == "tc_none" or budget <= 0 or max_lines <= 0:
        return ""

    task_kw = F.task_keywords(task)
    scored = []
    for i, e in enumerate(policy.get("exemplars") or []):
        if e.get("cluster") != cluster:
            continue
        text = str(e.get("text") or "").strip()
        if not text:
            continue
        overlap = F.jaccard(task_kw, e.get("keywords") or [])
        # 0.5 floor: a same-cluster exemplar is relevant by construction, so overlap re-orders
        # within the cluster rather than gating membership of it.
        score = _float(e.get("weight"), 0.0) * (0.5 + 0.5 * overlap)
        scored.append((-score, i, text))
    if not scored:
        return ""
    scored.sort()

    lines, used = [], 0
    for _score, _i, text in scored:
        if len(lines) >= max_lines:
            break
        cost = len(text) + (1 if lines else 0)
        if used + cost > budget:
            continue                          # skip, don't stop: a short later line may still fit
        lines.append(text)
        used += cost
    return "\n".join(lines)


def apply(policy, task="", app="", title="", ts=None):
    """The one function every client implements. Signature is fixed by the shipping app.

    Returns exactly:
        {"prompt_suffix": str, "pre_allow": bool, "block_threshold": float}

    Composition order, and why it is this order:
      1. Match the task to a cluster. No cluster -> no learning applies. An unrecognised task
         must never inherit another task's allowances.
      2. Allowance for this exact (cluster, app, title-pattern)? `pre_allow` skips the model call
         outright; `downgrade` keeps the check but raises the bar to the ceiling.
      3. Otherwise use the calibrated threshold for (cluster, app), if there is one.
      4. Exemplars ride along in every case -- including on a pre_allow, where they cost nothing
         because no call is made, and including when nothing else matched.
    """
    if not isinstance(policy, dict) or policy.get("schema") != SCHEMA:
        return dict(_EMPTY)
    ts = time.time() if ts is None else float(ts)

    task = task or ""
    app = (app or "").strip().lower()
    title = title or ""

    cluster, _score = match_cluster(policy, task)
    suffix = build_prompt_suffix(policy, task, cluster)

    result = {"prompt_suffix": suffix, "pre_allow": False, "block_threshold": NO_OPINION}
    if cluster == "tc_none":
        return result

    ceiling = min(_float((policy.get("defaults") or {}).get("threshold_ceiling"), MAX_THRESHOLD),
                  MAX_THRESHOLD)

    pattern = F.title_pattern(title)
    allowance = _active_allowance(policy, cluster, app, pattern, ts)
    if allowance is not None:
        if allowance.get("action") == "pre_allow":
            result["pre_allow"] = True
            result["block_threshold"] = ceiling
            return result
        # "downgrade": the check still runs and is still logged; only a very confident off-task
        # verdict blocks. This is the strongest loosening the client's clamp permits short of
        # skipping the check, which is exactly what we want for a leisure-leaning domain.
        result["block_threshold"] = ceiling
        return result

    learned = _learned_threshold(policy, cluster, app)
    if learned is not None:
        result["block_threshold"] = min(max(learned, 0.0), ceiling)
    return result


def explain(policy, task="", app="", title="", ts=None):
    """Human-readable trace of the same decision, for `python -m learner.cli explain`.

    Kept next to `apply` and deliberately re-deriving the same values rather than instrumenting
    `apply` itself: `apply` runs on every check on three platforms and must stay boring.
    """
    lines = []
    if not isinstance(policy, dict) or policy.get("schema") != SCHEMA:
        return {"decision": dict(_EMPTY),
                "trace": ["no usable policy (missing, wrong schema, or stale) -> no learning"]}
    ts = time.time() if ts is None else float(ts)

    app_l = (app or "").strip().lower()
    cluster, score = match_cluster(policy, task)
    label = ""
    for c in policy.get("clusters") or []:
        if c.get("id") == cluster:
            label = c.get("label") or ""
            break

    lines.append("task keywords: %s" % (", ".join(F.task_keywords(task)) or "(none)"))
    if cluster == "tc_none":
        lines.append("task cluster:  none (best overlap %.2f, below %.2f) -> no learning applies"
                     % (score, _float((policy.get("defaults") or {}).get(
                         "cluster_match_threshold"), F.TaskClusterer.THRESHOLD)))
    else:
        lines.append("task cluster:  %s %s(overlap %.2f)"
                     % (cluster, ("[%s] " % label) if label else "", score))

    pattern = F.title_pattern(title)
    domain = F.extract_domain(title)
    lines.append("app:           %s" % (app_l or "(none)"))
    lines.append("title pattern: %s%s" % (F.pattern_key(pattern),
                                          "  (domain %s)" % domain if domain else ""))
    lines.append("signature:     %s" % F.signature_key(cluster, app_l, pattern))

    decision = apply(policy, task=task, app=app, title=title, ts=ts)

    allowance = None
    if cluster != "tc_none":
        allowance = _active_allowance(policy, cluster, app_l, pattern, ts)
        if allowance is None:
            near = _near_miss(policy, cluster, app_l, pattern)
            lines.append("allowance:     none" + (" (%s)" % near if near else ""))
        else:
            lines.append("allowance:     %s -- %s" % (allowance.get("action"),
                                                      allowance.get("why") or ""))
            lines.append("               evidence %s over %s day(s), expires %s"
                         % (allowance.get("evidence"), allowance.get("distinct_days"),
                            _stamp(allowance.get("expires_at"))))
        learned = _learned_threshold(policy, cluster, app_l)
        if learned is None:
            lines.append("calibration:   none for this (task, app) -> app default stands")
        else:
            lines.append("calibration:   block at confidence >= %.2f" % learned)

    n_ex = len([l for l in decision["prompt_suffix"].split("\n") if l.strip()])
    lines.append("exemplars:     %d line(s), %d char(s) of the %d budget"
                 % (n_ex, len(decision["prompt_suffix"]), MAX_SUFFIX_CHARS))
    if decision["prompt_suffix"]:
        for line in decision["prompt_suffix"].split("\n"):
            lines.append("               %s" % line)

    if decision["pre_allow"]:
        lines.append("RESULT:        ALLOW without asking the model.")
    elif allowance is not None:
        lines.append("RESULT:        CHECK, but only block if the model is >= %.2f confident "
                     "-- this exact screen is a confirmed false alarm, downgraded rather than "
                     "skipped." % decision["block_threshold"])
    elif decision["block_threshold"] >= MAX_THRESHOLD:
        # Worth spelling out: this is calibration for the whole app, not an allowance for this
        # screen. Everything else in this app inherits the same raised bar, distractions included.
        lines.append("RESULT:        CHECK, but only block if the model is >= %.2f confident. "
                     "That bar comes from this app's calibration, NOT from any allowance for "
                     "this screen." % decision["block_threshold"])
    elif decision["block_threshold"] > 0.0:
        lines.append("RESULT:        CHECK, block if the model is >= %.2f confident it is "
                     "off task." % decision["block_threshold"])
    else:
        lines.append("RESULT:        CHECK, and block on any confident off-task verdict "
                     "(no learning applies).")

    integrity = policy.get("integrity") or {}
    if integrity.get("notify_partner"):
        lines.append("INTEGRITY:     %s" % (integrity.get("headline") or "learning under strain"))
    return {"decision": decision, "trace": lines}


def _near_miss(policy, cluster, app, pattern):
    """Why an allowance ALMOST matched -- the most useful thing `explain` can say."""
    key = F.signature_key(cluster, app, pattern)
    for a in policy.get("allowances") or []:
        if a.get("key") == key:
            return "expired %s" % _stamp(a.get("expires_at"))
    same_app = [a for a in policy.get("allowances") or []
                if a.get("cluster") == cluster and (a.get("app") or "") == app]
    if same_app:
        return "this app has %d allowance(s), but for a different title pattern" % len(same_app)
    return ""


def _stamp(ts):
    if not isinstance(ts, (int, float)):
        return "?"
    return time.strftime("%Y-%m-%d", time.localtime(ts))
