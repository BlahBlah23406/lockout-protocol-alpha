"""Model-free signals extracted from one judgement.

Everything here runs without a network call and without the screenshot, because the learner has
to be able to re-derive its features from the log alone, months later, on a machine that has no
API key. That constraint is what makes the whole thing auditable: given the same log you get the
same policy, byte for byte.

The four signals that matter, and why:

  * TASK CLUSTER -- the user types the task freehand ("math test prep", "studying for my math
    test", "math revision"). Those are the same task and must share learned state, or the user
    re-teaches the tool every morning. We cluster by keyword overlap rather than by string
    equality. No embeddings: a set-containment score over stemmed tokens is portable to Swift
    and Kotlin in an afternoon, and an embedding model is not.
  * APP -- the executable id, the one stable identifier across a session.
  * TITLE PATTERN -- the reusable part of the window title. A domain when we can find one
    ("... - YouTube" -> youtube.com), otherwise the two longest content tokens. This is what a
    signature is keyed on, so it must be stable across visits: "Integration by parts - Khan
    Academy" and "Integration by substitution - Khan Academy" must collapse to the same pattern
    or nothing ever accumulates evidence.
  * TIME-OF-DAY BUCKET -- carried for reporting and for the accountability partner's summary.
    Deliberately NOT part of the signature key: making allowances time-scoped would multiply the
    evidence needed to learn anything, and "YouTube/Khan Academy is fine for maths" does not stop
    being true at 9pm.

Determinism rules for anyone porting this: lowercase with str.lower(), split on anything that is
not [a-z0-9], sort with plain byte ordering, and never depend on dict iteration order.
"""

import hashlib
import re
import time

# Words that carry no discriminative signal in a task description or a window title. Kept small
# and explicit rather than pulled from a corpus, so a Swift/Kotlin port can paste the same list.
STOPWORDS = frozenset("""
a an and are as at be been being by do does doing for from get getting go going had has have
having how i im in into is it its just let lets me more my not of on onto or our out over
so some that the their then there these they this those to up us was we were what when where
which while who why will with you your
work working task tasks today tonight session bit stuff thing things focus time
morning afternoon evening finish finishing continue continuing keep start starting
new tab home page google search results untitled document window app application
""".split())

# Title suffixes browsers and apps append. Stripping them keeps the pattern about the CONTENT.
_TITLE_TAIL_SEPARATORS = (" - ", " | ", " :: ")

# Site name -> canonical domain. Window titles almost never contain a URL, so the only way to
# recover a domain is to recognise the brand the page puts in its title. This list is the
# pragmatic 95%: the sites that actually show up in study/work/procrastination sessions.
SITE_NAMES = (
    ("khan academy", "khanacademy.org"),
    ("stack overflow", "stackoverflow.com"),
    ("google docs", "docs.google.com"),
    ("google drive", "drive.google.com"),
    ("google scholar", "scholar.google.com"),
    ("hacker news", "news.ycombinator.com"),
    ("wolfram alpha", "wolframalpha.com"),
    ("wolframalpha", "wolframalpha.com"),
    ("desmos", "desmos.com"),
    ("overleaf", "overleaf.com"),
    ("wikipedia", "wikipedia.org"),
    ("youtube", "youtube.com"),
    ("reddit", "reddit.com"),
    ("github", "github.com"),
    ("gitlab", "gitlab.com"),
    ("discord", "discord.com"),
    ("slack", "slack.com"),
    ("linkedin", "linkedin.com"),
    ("indeed", "indeed.com"),
    ("glassdoor", "glassdoor.com"),
    ("gmail", "mail.google.com"),
    ("outlook", "outlook.office.com"),
    ("notion", "notion.so"),
    ("chatgpt", "chatgpt.com"),
    ("coursera", "coursera.org"),
    ("brilliant", "brilliant.org"),
    ("jstor", "jstor.org"),
    ("instagram", "instagram.com"),
    ("tiktok", "tiktok.com"),
    ("netflix", "netflix.com"),
    ("twitch", "twitch.tv"),
    ("twitter", "twitter.com"),
    ("amazon", "amazon.com"),
    ("pinterest", "pinterest.com"),
    ("facebook", "facebook.com"),
    ("steam", "steampowered.com"),
)

# A bare domain sitting in the title (some browsers show it, and PWAs often do).
_DOMAIN_RE = re.compile(r"\b([a-z0-9][a-z0-9-]{0,62}(?:\.[a-z0-9-]{1,63})+)\b")
_TLDS = frozenset("""
com org net edu gov io ai co uk ca de fr jp in us tv me so app dev info biz online site xyz
""".split())

_WORD_RE = re.compile(r"[a-z0-9]+")

TOD_BUCKETS = ("night", "morning", "afternoon", "evening", "late")


def normalise_text(s):
    """Lowercase and collapse whitespace. Portable and boring on purpose."""
    if not isinstance(s, str):
        s = "" if s is None else str(s)
    return " ".join(s.lower().split())


def _stem(tok):
    """A three-rule suffix stripper. Not linguistics -- just enough that "studying"/"studies"/
    "study" and "applications"/"application" land on one key. Anything cleverer would be a port
    liability for no measurable gain at this vocabulary size."""
    for suffix in ("ing", "ies", "es", "s"):
        if tok.endswith(suffix) and len(tok) - len(suffix) >= 3:
            base = tok[: -len(suffix)]
            if suffix == "ies":
                return base + "y"
            return base
    return tok


def tokenise(s, min_len=3):
    """Content tokens: lowercase alnum runs, stopwords and short/numeric tokens dropped.

    `min_len=3` drops "of"/"to" noise but keeps "api", "sql", "gre". Pure-digit tokens are dropped
    because a title's numbers ("(3) Discord", "Lecture 12") are the part that changes between
    visits -- exactly what we must not key a signature on. Stopwords are checked BEFORE and AFTER
    stemming so that "working" and "work" are both removed.
    """
    out = []
    for tok in _WORD_RE.findall(normalise_text(s)):
        if len(tok) < min_len or tok.isdigit() or tok in STOPWORDS:
            continue
        stemmed = _stem(tok)
        if stemmed in STOPWORDS or len(stemmed) < min_len:
            continue
        out.append(stemmed)
    return out


def task_keywords(task):
    """Sorted, deduplicated keyword set for a freehand task string. The clustering key."""
    return tuple(sorted(set(tokenise(task))))


def jaccard(a, b):
    """Symmetric set overlap. Used for RANKING (which exemplar is most relevant), never for
    cluster membership -- see `overlap` for why. 0.0 when either side is empty."""
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / float(len(sa | sb))


def overlap(a, b):
    """Containment: shared keywords over the SMALLER set. The cluster-membership score.

    Jaccard was the obvious choice and measurably the wrong one. Real task strings vary wildly in
    length -- "applying for jobs" against "job applications this afternoon, mostly backend roles"
    -- and Jaccard punishes that asymmetry hard enough that the same task written two ways lands
    in two clusters, which is precisely the failure the clusterer exists to prevent. On the four
    task families in `simulate.py` (three phrasings each) Jaccard at 0.34 produced NINE clusters;
    containment at 0.33 produces four, which is the right answer.

    The cost of containment is that a short set is easy to contain, so "work"-class filler words
    would merge everything into one blob. That is handled upstream: generic task verbs are
    stopwords, so a keyword set only ever contains topic words.
    """
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / float(min(len(sa), len(sb)))


def cluster_id(keywords):
    """Stable id for a keyword set. Hashed so it is short and so the policy file's KEYS do not
    leak the task text -- the policy is meant to be shareable with an accountability partner."""
    if not keywords:
        return "tc_none"
    digest = hashlib.sha1("|".join(sorted(keywords)).encode("utf-8")).hexdigest()
    return "tc_" + digest[:8]


def _last_separator(text):
    """Position of the RIGHTMOST title separator, as (start, end), or None.

    Rightmost, across all separator kinds at once. Doing this per-separator in list order, or
    keeping the longest tail, both get "Integration by parts | Khan Academy - YouTube" wrong:
    they hand back "khan academy - youtube" as the tail, which the site table then resolves to
    khanacademy.org instead of youtube.com -- silently routing a YouTube page around the
    never-pre-allow list. Found by a unit test, and worth the extra function.
    """
    best = None
    for sep in _TITLE_TAIL_SEPARATORS:
        idx = text.rfind(sep)
        if idx > 0 and (best is None or idx > best[0]):
            best = (idx, idx + len(sep))
    return best


def strip_title_tail(title):
    """Drop the trailing " - <App/Site>" chrome so tokens describe the CONTENT, not the browser."""
    text = normalise_text(title)
    found = _last_separator(text)
    return text[:found[0]].strip() if found else text


def _title_tail(title):
    """The segment after the rightmost separator -- where browsers put the SITE name."""
    text = normalise_text(title)
    found = _last_separator(text)
    return text[found[1]:].strip() if found else ""


def _site_lookup(text):
    for name, domain in SITE_NAMES:
        if name in text:
            return domain
    return None


def extract_domain(title):
    """Best-effort domain for a window title, or None.

    Three passes, in this order, and the order is the interesting part:

      1. A literal domain in the text. Unambiguous, so trust it.
      2. A brand name in the TITLE TAIL. Browsers put the site last ("Integration by parts |
         Khan Academy - YouTube"), and the site is what a signature must be keyed on. Scanning
         the whole title first would call that page khanacademy.org and quietly route it around
         the never-pre-allow list -- the exact hole a user would find by accident and then
         exploit on purpose.
      3. A brand name anywhere. The fallback for titles with no separator at all.

    We return None rather than inventing a domain: a wrong domain merges two unrelated
    signatures, and merged signatures are how an allowance leaks onto a site nobody approved.
    """
    text = normalise_text(title)
    for match in _DOMAIN_RE.finditer(text):
        candidate = match.group(1).strip(".")
        parts = candidate.split(".")
        if len(parts) >= 2 and parts[-1] in _TLDS and len(parts[0]) > 1:
            if parts[0] == "www":
                parts = parts[1:]
            return ".".join(parts)
    tail = _title_tail(text)
    if tail:
        found = _site_lookup(tail)
        if found:
            return found
    return _site_lookup(text)


def tod_bucket(ts):
    """Local-time bucket. Local, not UTC: "evening" has to mean the user's evening."""
    try:
        hour = time.localtime(float(ts)).tm_hour
    except (TypeError, ValueError, OSError, OverflowError):
        return "night"
    if hour < 6:
        return "night"
    if hour < 12:
        return "morning"
    if hour < 17:
        return "afternoon"
    if hour < 22:
        return "evening"
    return "late"


def title_pattern(title):
    """The reusable part of a window title, as a portable {kind, value} pair.

    kind="domain" is strongly preferred: it survives every title change on the site. kind="tokens"
    is the fallback for native apps (Word, VS Code, a PDF reader) -- the two longest content
    tokens, sorted, which is stable across "chapter 4" vs "chapter 5" style variation. kind="app"
    means we found nothing reusable and the pattern degenerates to the whole application, which
    the learner treats as much weaker evidence (see `learn.py`).
    """
    domain = extract_domain(title)
    if domain:
        return {"kind": "domain", "value": domain}
    tokens = tokenise(strip_title_tail(title)) or tokenise(title)
    if not tokens:
        return {"kind": "app", "value": ""}
    # Longest-first, then alphabetical, so the choice is deterministic across platforms.
    ranked = sorted(set(tokens), key=lambda t: (-len(t), t))[:2]
    return {"kind": "tokens", "value": "+".join(sorted(ranked))}


def pattern_key(pattern):
    return "%s:%s" % (pattern["kind"], pattern["value"])


def signature_key(cluster, app, pattern):
    """The (task-cluster, app, title-pattern) triple, as one string.

    One string because the clients look this up in a plain JSON object, and a nested three-level
    lookup in Swift/Kotlin is three times the code for zero benefit.
    """
    return "%s|%s|%s" % (cluster, app or "", pattern_key(pattern))


class Features:
    """Everything the learner needs from one judgement, with nothing model-shaped in it."""

    __slots__ = ("ts", "task", "keywords", "app", "app_name", "title", "title_tokens",
                 "domain", "pattern", "tod", "verdict", "action", "confidence", "feedback",
                 "feedback_at", "session_id", "raw")

    def __init__(self, rec):
        self.raw = rec
        self.ts = rec.get("ts", 0.0)
        self.task = rec.get("task", "")
        self.keywords = task_keywords(self.task)
        self.app = (rec.get("app") or "").strip().lower()
        self.app_name = rec.get("app_name", "")
        self.title = rec.get("window_title", "")
        self.title_tokens = tuple(tokenise(self.title))
        self.domain = extract_domain(self.title)
        self.pattern = title_pattern(self.title)
        self.tod = tod_bucket(self.ts)
        self.verdict = rec.get("verdict", "unreadable")
        self.action = rec.get("action", "logged")
        self.confidence = rec.get("confidence", 0.0)
        self.feedback = rec.get("feedback")
        self.feedback_at = rec.get("feedback_at")
        self.session_id = rec.get("session_id", "")

    def day(self):
        """Local calendar day as an int, used by the "evidence must span days" guard."""
        try:
            t = time.localtime(float(self.ts))
            return t.tm_year * 10000 + t.tm_mon * 100 + t.tm_mday
        except (TypeError, ValueError, OSError, OverflowError):
            return 0

    def __repr__(self):
        return ("Features(task=%r, app=%r, pattern=%r, verdict=%r, feedback=%r)"
                % (self.task, self.app, pattern_key(self.pattern), self.verdict, self.feedback))


def features_of(rec):
    return Features(rec)


class TaskClusterer:
    """Greedy keyword-overlap clustering of freehand task strings.

    Built once from the whole log, in sorted order, so the same log always produces the same
    clusters regardless of how the file was concatenated. Each cluster keeps the keyword sets it
    absorbed; `match()` scores a new task against every cluster and takes the best above
    `threshold`. Below threshold the caller gets "tc_none" and the strict defaults -- the correct
    failure mode, because an unrecognised task must never inherit another task's allowances.
    """

    THRESHOLD = 0.33            # 1 shared topic word out of 3; see README "What we measured".

    def __init__(self, threshold=None):
        self.threshold = self.THRESHOLD if threshold is None else threshold
        self.clusters = []      # [{"id", "keywords": set, "label", "members": [...], "count"}]

    @classmethod
    def from_tasks(cls, tasks, threshold=None):
        self = cls(threshold)
        for task in sorted({normalise_text(t) for t in tasks if normalise_text(t)}):
            self.add(task)
        return self

    def add(self, task):
        kw = task_keywords(task)
        if not kw:
            return "tc_none"
        best, score = self._best(kw)
        if best is not None and score >= self.threshold:
            best["keywords"].update(kw)
            best["keyword_sets"].append(tuple(kw))
            best["members"].append(normalise_text(task))
            best["count"] += 1
            return best["id"]
        cluster = {
            "id": cluster_id(kw),
            "keywords": set(kw),
            "keyword_sets": [tuple(kw)],
            "label": normalise_text(task),      # the first task that formed it, for reports
            "members": [normalise_text(task)],
            "count": 1,
        }
        self.clusters.append(cluster)
        return cluster["id"]

    def _best(self, kw):
        """Single linkage: score against the best MEMBER phrasing, not the merged union.

        Scoring against the union looked tidier and degrades badly -- every task absorbed makes
        the union bigger, so the more phrasings a cluster has learned the harder it becomes to
        join, which is exactly backwards.
        """
        best, score = None, 0.0
        for cluster in self.clusters:
            s = max(overlap(kw, member) for member in cluster["keyword_sets"])
            # Ties broken by id so the result never depends on insertion order.
            if s > score or (s == score and s > 0.0 and best is not None
                             and cluster["id"] < best["id"]):
                best, score = cluster, s
        return best, score

    def match(self, task):
        """Cluster id for a task, WITHOUT mutating the clusterer. Returns (id, score)."""
        kw = task_keywords(task)
        if not kw:
            return "tc_none", 0.0
        best, score = self._best(kw)
        if best is None or score < self.threshold:
            return "tc_none", score
        return best["id"], score

    def export(self):
        """Serialisable form for `focus_policy.json`. Keywords sorted for byte-stable output."""
        return [
            {
                "id": c["id"],
                "label": c["label"],
                "keywords": sorted(c["keywords"]),
                # Each phrasing's own keyword set, because `policy.match_cluster` has to
                # reproduce single-linkage matching from the JSON alone.
                "keyword_sets": [list(ks) for ks in sorted(set(c["keyword_sets"]))],
                "tasks_seen": c["count"],
            }
            for c in sorted(self.clusters, key=lambda c: c["id"])
        ]
