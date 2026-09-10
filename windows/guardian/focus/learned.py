"""Client side of the experimental false-alarm learner.

The learner itself lives at `learner/` and is offline; this reads the one artefact it produces,
`focus_policy.json`, and turns it into three answers: extra prompt lines, a pre-allow, and a
confidence threshold below which an off-task verdict is logged rather than blocked.

Everything here fails soft. A missing, stale, corrupt, or future-schema policy must leave the app
behaving exactly as it does with no learning at all.
"""

import json
import sys
import time
from pathlib import Path

from ..paths import data_dir

POLICY_FILE = data_dir() / "focus_policy.json"

# A policy claiming a newer schema is ignored rather than half-read: the parts we'd drop might be
# the safety limits.
SUPPORTED_SCHEMA = 1

# The ceiling on how far learning may erode the monitor. It lives here, in the app, so that
# hand-editing the generated file cannot lift it.
MAX_THRESHOLD = 0.85
MAX_SUFFIX_CHARS = 1200
POLICY_MAX_AGE_DAYS = 60

_cache = {"mtime": None, "data": None}


def _repo_root() -> Path:
    """…/windows/guardian/focus/learned.py -> the repo root, where `learner/` sits."""
    return Path(__file__).resolve().parents[3]


def _load() -> dict:
    try:
        mtime = POLICY_FILE.stat().st_mtime
    except OSError:
        _cache["mtime"], _cache["data"] = None, None
        return {}
    if _cache["mtime"] == mtime and _cache["data"] is not None:
        return _cache["data"]

    try:
        data = json.loads(POLICY_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("not an object")
    except Exception:
        data = {}

    if data.get("schema") != SUPPORTED_SCHEMA:
        data = {}
    # A policy learned two months ago describes a different person's week.
    generated = data.get("generated_at")
    if isinstance(generated, (int, float)):
        if time.time() - generated > POLICY_MAX_AGE_DAYS * 86400:
            data = {}

    _cache["mtime"], _cache["data"] = mtime, data
    return data


def _via_learner(task: str, app: str, title: str):
    """Prefer the learner's own `apply()` when importable, so the matching logic lives in one
    place. Returns None when unavailable."""
    root = str(_repo_root())
    try:
        if root not in sys.path:
            sys.path.insert(0, root)
        from learner import policy as learner_policy       # noqa: PLC0415
    except Exception:
        return None
    try:
        return learner_policy.apply(_load(), task=task, app=app, title=title)
    except Exception:
        return None


def decide(task: str, app: str, title: str = "") -> dict:
    """The one call the monitor makes. Always returns a usable dict."""
    default = {"prompt_suffix": "", "pre_allow": False, "block_threshold": 0.0}
    data = _load()
    if not data:
        return default

    result = _via_learner(task, app, title)
    if not isinstance(result, dict):
        return default

    suffix = str(result.get("prompt_suffix") or "")[:MAX_SUFFIX_CHARS]
    threshold = result.get("block_threshold", 0.0)
    try:
        threshold = min(max(float(threshold), 0.0), MAX_THRESHOLD)
    except (TypeError, ValueError):
        threshold = 0.0
    return {
        "prompt_suffix": suffix,
        "pre_allow": bool(result.get("pre_allow")),
        "block_threshold": threshold,
    }


def prompt_suffix(task: str, app: str, title: str = "") -> str:
    return decide(task, app, title)["prompt_suffix"]


def status() -> str:
    """One line for the settings screen, so "learning is on" is never an unverifiable claim."""
    data = _load()
    if not data:
        return "no policy learned yet"
    n = data.get("exemplar_count", "?")
    sigs = data.get("signature_count", "?")
    when = data.get("generated_at")
    stamp = time.strftime("%Y-%m-%d", time.localtime(when)) if when else "unknown date"
    return f"{n} exemplar(s), {sigs} allowance(s), learned {stamp}"
