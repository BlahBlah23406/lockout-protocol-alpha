"""Append-only record of every focus check, and the user's feedback on it.

The activity log is prose for humans; this is the same events as structured rows, read back by the
end-of-session summary and by the offline learner at `learner/`.

One JSON object per line, appended and never rewritten, so a crash mid-write costs one line rather
than the file. The schema is shared with the macOS, Android and iOS ports and with the learner —
change a field name in one place and you must change it in all four.
"""

import json
import threading
import time

from ..paths import data_dir

JUDGEMENTS_FILE = data_dir() / "judgements.jsonl"

FB_FALSE_ALARM = "false_alarm"      # it blocked me and it was wrong
FB_CORRECT = "correct"              # it blocked me and it was right
FB_MISSED = "missed"                # it let this through and it shouldn't have

_lock = threading.RLock()
MAX_LINES = 20000


def record(session, app, app_name, window_title, verdict_name, reason, confidence,
           action, provider) -> str:
    """Append one judgement and return its id, so a later feedback press can find this row."""
    jid = f"j_{int(time.time() * 1000)}"
    row = {
        "id": jid,
        "ts": time.time(),
        "session_id": getattr(session, "id", ""),
        "task": getattr(session, "task", ""),
        "app": app or "",
        "app_name": app_name or "",
        "window_title": (window_title or "")[:300],
        "verdict": verdict_name,
        "reason": (reason or "")[:500],
        "confidence": round(float(confidence or 0.0), 3),
        "action": action,
        "provider": provider or "",
        "feedback": None,
        "feedback_at": None,
        "feedback_note": None,
    }
    _append(row)
    return jid


def _append(row: dict) -> None:
    with _lock:
        try:
            with open(JUDGEMENTS_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
        except Exception:
            pass                    # telemetry must never be able to break monitoring


def add_feedback(judgement_id: str, feedback: str, note: str = "") -> bool:
    """Written as a new row rather than an edit: rewriting a line in place means rewriting the
    whole file, which is not something to do while the monitor thread is appending to it."""
    if feedback not in (FB_FALSE_ALARM, FB_CORRECT, FB_MISSED):
        return False
    _append({
        "id": f"{judgement_id}#fb",
        "ts": time.time(),
        "ref": judgement_id,
        "feedback": feedback,
        "feedback_at": time.time(),
        "feedback_note": (note or "")[:300],
    })
    return True


def read_all(limit: int = 2000) -> list:
    """The tail of the log, with feedback rows folded into the judgements they refer to."""
    try:
        lines = JUDGEMENTS_FILE.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []

    rows, by_id = [], {}
    for line in lines[-limit * 2:]:
        try:
            obj = json.loads(line)
        except Exception:
            continue                # a torn final line after a hard kill
        ref = obj.get("ref")
        if ref:
            target = by_id.get(ref)
            if target is not None:
                target["feedback"] = obj.get("feedback")
                target["feedback_at"] = obj.get("feedback_at")
                target["feedback_note"] = obj.get("feedback_note")
            continue
        rows.append(obj)
        by_id[obj.get("id")] = obj
    return rows[-limit:]


def trim() -> None:
    """Keep the file bounded. Called at startup, never on the hot path."""
    with _lock:
        try:
            lines = JUDGEMENTS_FILE.read_text(encoding="utf-8").splitlines()
        except Exception:
            return
        if len(lines) <= MAX_LINES:
            return
        try:
            tmp = JUDGEMENTS_FILE.with_suffix(".tmp")
            tmp.write_text("\n".join(lines[-MAX_LINES:]) + "\n", encoding="utf-8")
            tmp.replace(JUDGEMENTS_FILE)
        except Exception:
            pass


def session_stats(session_id: str) -> dict:
    checks = off = blocked = false_alarms = 0
    for r in read_all():
        if r.get("session_id") != session_id:
            continue
        checks += 1
        if r.get("verdict") == "off_task":
            off += 1
        if r.get("action") == "blocked":
            blocked += 1
        if r.get("feedback") == FB_FALSE_ALARM:
            false_alarms += 1
    return {"checks": checks, "off_task": off, "blocked": blocked, "false_alarms": false_alarms}
