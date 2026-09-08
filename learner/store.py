"""Read/append the `judgements.jsonl` log that `windows/guardian/models/judgements.py` writes.

The log is append-only JSON Lines because the monitor writes it from a background thread while
the UI reads it, and a line-oriented file is the only format where a half-written record can be
skipped instead of destroying the whole store. That robustness is the point of this module: a
crash mid-write, a truncated final line, a hand-edited file or a stray BOM must never stop the
learner from running. We skip what we cannot parse and count the damage, so the caller can say
"skipped 3 malformed lines" out loud instead of silently pretending the data was clean.

TWO ROW SHAPES, ONE RECORD
--------------------------
The producer never rewrites a line. A judgement is one row:

    {"id": "j_1757300123400", "ts": ..., "task": ..., "verdict": "off_task", "action": "blocked",
     "confidence": 0.72, "feedback": null, "feedback_at": null, "feedback_note": null}

and the user pressing "False alarm" later appends a SECOND row that points back at it:

    {"id": "j_1757300123400#fb", "ts": ..., "ref": "j_1757300123400",
     "feedback": "false_alarm", "feedback_at": ..., "feedback_note": "this is my textbook's video"}

`read_judgements` folds the pair together exactly the way `judgements.read_all()` does, so the
learner sees one enriched record per check. Folding is done over the WHOLE file rather than
streaming, because a feedback row can legitimately appear thousands of lines after its target
(the user might press the button at the end of the session) and, after two logs are concatenated,
can even appear before it.

Records are normalised on read into a dict with every contract key present. Downstream code
(`features`, `learn`) can then index without a forest of `.get()` defaults, and a field the
monitor stops writing degrades to a default instead of an exception.
"""

import json
import os
import tempfile
import time

# The wire contract, exactly as the monitor writes it. Extra keys are preserved untouched: the
# simulator adds a `truth_on_task` label this way, and future monitor versions can add fields
# without needing a learner release.
VERDICTS = ("on_task", "off_task", "unreadable")
ACTIONS = ("blocked", "logged", "allowed")
FEEDBACKS = (None, "false_alarm", "correct", "missed")

FB_FALSE_ALARM = "false_alarm"
FB_CORRECT = "correct"
FB_MISSED = "missed"

_BOM = chr(0xFEFF)   # a UTF-8 BOM on the first line must not eat the first judgement

_DEFAULTS = {
    "id": "",
    "ts": 0.0,
    "session_id": "",
    "task": "",
    "app": "",
    "app_name": "",
    "window_title": "",
    "verdict": "unreadable",
    "reason": "",
    "confidence": 0.0,
    "action": "logged",
    "provider": "",
    "feedback": None,
    "feedback_at": None,
    "feedback_note": "",
}


class ReadResult:
    """Rows plus the parse damage, so callers can report skipped lines honestly."""

    __slots__ = ("rows", "skipped", "orphan_feedback", "path")

    def __init__(self, rows, skipped, orphan_feedback, path):
        self.rows = rows
        self.skipped = skipped
        # Feedback rows whose judgement is not in the file. Expected after a trim() drops old
        # lines from the front; worth surfacing because a large count means real signal is
        # being lost before the learner ever sees it.
        self.orphan_feedback = orphan_feedback
        self.path = path

    def __len__(self):
        return len(self.rows)

    def __iter__(self):
        return iter(self.rows)


def _as_float(v, default):
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _as_str(v, default=""):
    if v is None:
        return default
    if isinstance(v, str):
        return v
    return str(v)


def is_feedback_row(raw):
    """A feedback row is identified by `ref`, not by `id`, because `id` is present on both."""
    return isinstance(raw, dict) and bool(_as_str(raw.get("ref")).strip())


def normalise_feedback(raw):
    """Coerce a feedback row, or return None if it names no target or no valid verdict."""
    if not is_feedback_row(raw):
        return None
    feedback = _as_str(raw.get("feedback")).strip().lower()
    if feedback not in (FB_FALSE_ALARM, FB_CORRECT, FB_MISSED):
        return None
    return {
        "ref": _as_str(raw.get("ref")).strip(),
        "feedback": feedback,
        # Fall back to the row's own `ts`: an older writer, or a hand-edited line, may omit
        # `feedback_at`, and the press time is load-bearing for the reflex-spam guard.
        "feedback_at": _as_float(raw.get("feedback_at"), _as_float(raw.get("ts"), None)),
        "feedback_note": _as_str(raw.get("feedback_note")),
    }


def normalise(raw):
    """Coerce one decoded judgement row into the full contract shape, or None if unusable.

    "Unusable" is narrow on purpose: only a non-object, or a row with no timestamp AND no task,
    is dropped. Everything else is repaired, because throwing away a judgement because its
    `confidence` arrived as the string "0.7" would lose real feedback for a cosmetic reason.
    """
    if not isinstance(raw, dict):
        return None

    out = dict(raw)                       # keep unknown keys (labels, future fields)
    for key, default in _DEFAULTS.items():
        if key not in out or out[key] is None:
            out[key] = default

    out["ts"] = _as_float(raw.get("ts"), 0.0)
    out["confidence"] = min(max(_as_float(raw.get("confidence"), 0.0), 0.0), 1.0)
    out["feedback_at"] = (_as_float(raw.get("feedback_at"), None)
                          if raw.get("feedback_at") is not None else None)
    for key in ("id", "session_id", "task", "app", "app_name", "window_title", "reason",
                "provider", "feedback_note"):
        out[key] = _as_str(out.get(key))

    verdict = _as_str(raw.get("verdict")).strip().lower()
    out["verdict"] = verdict if verdict in VERDICTS else "unreadable"
    action = _as_str(raw.get("action")).strip().lower()
    out["action"] = action if action in ACTIONS else "logged"

    fb = raw.get("feedback")
    fb = _as_str(fb).strip().lower() if fb is not None else None
    out["feedback"] = fb if fb in (FB_FALSE_ALARM, FB_CORRECT, FB_MISSED) else None

    if out["ts"] <= 0.0 and not out["task"]:
        return None                       # no time and no task: nothing here we can learn from
    # Normalise the app id the way the rest of the codebase does: lowercase executable name.
    out["app"] = out["app"].strip().lower()
    return out


def _decode_lines(path):
    """Yield decoded JSON objects and count what we had to throw away."""
    skipped = 0
    try:
        fh = open(path, "r", encoding="utf-8", errors="replace")
    except OSError:
        return [], 0
    objects = []
    with fh:
        for line in fh:
            line = line.strip().lstrip(_BOM)
            if not line or line.startswith("#"):
                continue
            try:
                obj = json.loads(line)
            except Exception:
                skipped += 1              # a torn final line after a hard kill; skip, don't fail
                continue
            objects.append(obj)
    return objects, skipped


def fold(objects):
    """Fold a decoded row stream into judgements with their feedback attached.

    Returns (rows, skipped, orphan_feedback). Later feedback for the same judgement wins, which
    matches the UI: pressing "False alarm" and then "Actually it was right" leaves the last press
    standing. Rows come back sorted by `ts` because the learner's day-bucketing and expiry maths
    assume time order, and a log concatenated from two machines can be out of order on disk.
    """
    rows, by_id, pending, skipped, orphans = [], {}, [], 0, 0

    for obj in objects:
        if is_feedback_row(obj):
            fb = normalise_feedback(obj)
            if fb is None:
                skipped += 1
            else:
                pending.append(fb)
            continue
        rec = normalise(obj)
        if rec is None:
            skipped += 1
            continue
        rows.append(rec)
        if rec["id"]:
            by_id[rec["id"]] = rec

    for fb in pending:
        target = by_id.get(fb["ref"])
        if target is None:
            orphans += 1                  # its judgement was trimmed off the front of the log
            continue
        target["feedback"] = fb["feedback"]
        target["feedback_at"] = fb["feedback_at"]
        target["feedback_note"] = fb["feedback_note"]

    rows.sort(key=lambda r: (r["ts"], r["id"]))
    return rows, skipped, orphans


def read_judgements(path):
    """Read the whole log, folded. Never raises for a bad file, only for a bad argument."""
    objects, skipped = _decode_lines(path)
    rows, fold_skipped, orphans = fold(objects)
    return ReadResult(rows, skipped + fold_skipped, orphans, str(path))


def iter_judgements(path):
    """Streaming read for the memory-conscious. Feedback is NOT folded in — a feedback row can
    arrive arbitrarily later, so folding is impossible without buffering the file. Use
    `read_judgements` for anything that cares about feedback (which is everything in `learn.py`);
    this exists for cheap scans like "how many checks today"."""
    objects, _ = _decode_lines(path)
    for obj in objects:
        if is_feedback_row(obj):
            continue
        rec = normalise(obj)
        if rec is not None:
            yield rec


def append_judgement(path, record):
    """Append one judgement row. Flushed so a crash loses at most the current line."""
    rec = normalise(record)
    if rec is None:
        raise ValueError("record is not a usable judgement")
    _append_raw(path, rec)
    return rec


def append_feedback(path, judgement_id, feedback, note="", at=None):
    """Append a feedback row in the producer's format. Mirrors `judgements.add_feedback`."""
    if feedback not in (FB_FALSE_ALARM, FB_CORRECT, FB_MISSED):
        raise ValueError("unknown feedback value: %r" % (feedback,))
    when = time.time() if at is None else float(at)
    _append_raw(path, {
        "id": "%s#fb" % judgement_id,
        "ts": when,
        "ref": judgement_id,
        "feedback": feedback,
        "feedback_at": when,
        "feedback_note": (note or "")[:300],
    })


def _append_raw(path, row):
    _ensure_parent(path)
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        fh.flush()


def write_rows(path, rows):
    """Rewrite the whole log from raw rows (used by the simulator, which emits both row shapes).

    Atomic replace, so a reader never sees a half-written file.
    """
    _ensure_parent(path)
    directory = os.path.dirname(os.path.abspath(str(path))) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _ensure_parent(path):
    parent = os.path.dirname(os.path.abspath(str(path)))
    if parent:
        os.makedirs(parent, exist_ok=True)


def now():
    return time.time()
