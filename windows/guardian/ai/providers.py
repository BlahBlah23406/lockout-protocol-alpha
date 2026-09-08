"""Pluggable model providers for the focus classifier.

The original app spoke to exactly one backend (Ollama Cloud) because it only ever had one job.
A focus monitor is different: it runs a check every couple of minutes for hours, so *whose*
model it is and *where* it runs becomes the user's decision, not ours. Someone on a laptop with
a 3090 wants `http://127.0.0.1:11434` and zero cost; someone on a Surface wants a hosted model;
someone in a regulated workplace wants the request to never leave their VPN.

So the transport is generalised and the *policy* — retry, key fail-over, and the rule that a
backend hiccup NEVER blocks the user — is kept in one place and shared by every provider. That
policy is the part that was hard-won (see `ollama_client.py`); the request shape is the easy part.

Four kinds, covering essentially every vision endpoint a person can point us at:

    ollama    /api/chat with `images: [b64]`     — local (no key) or ollama.com (key)
    openai    /v1/chat/completions with a
              `data:image/jpeg;base64,` image_url — OpenAI, LM Studio, llama.cpp, vLLM,
                                                    OpenRouter, Groq, Together, …
    anthropic /v1/messages with an image block    — Claude
    custom    same wire format as `openai`, but the user supplies the base URL

`custom` is not a fourth code path — it is `openai` with the URL field unlocked in the UI. It
exists as a separate kind only so the picker can say "anything OpenAI-compatible" out loud.
"""

import base64
import io
import json
import urllib.error
import urllib.request

# Transient-failure retry policy, carried over unchanged from the content classifier: the AI
# being busy must never cost the user their session.
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 0.8
REQUEST_TIMEOUT = 90

OLLAMA = "ollama"
OPENAI = "openai"
ANTHROPIC = "anthropic"
CUSTOM = "custom"

# What the settings picker offers. `needs_key` drives whether the UI nags for one; a local
# Ollama or LM Studio genuinely has no key and asking for one just confuses people.
PRESETS = [
    {"id": "ollama-local", "kind": OLLAMA, "label": "Ollama (on this PC)",
     "base_url": "http://127.0.0.1:11434", "model": "qwen3-vl:8b", "needs_key": False,
     "hint": "Free and fully private — nothing leaves this machine. Needs Ollama installed "
             "and a vision model pulled (`ollama pull qwen3-vl:8b`)."},
    {"id": "ollama-cloud", "kind": OLLAMA, "label": "Ollama Cloud",
     "base_url": "https://ollama.com", "model": "gemma4:31b-cloud", "needs_key": True,
     "hint": "Hosted Ollama. Works on any machine, including a laptop that can't run a "
             "vision model itself."},
    {"id": "openai", "kind": OPENAI, "label": "OpenAI",
     "base_url": "https://api.openai.com", "model": "gpt-4.1-mini", "needs_key": True,
     "hint": "Any OpenAI vision model."},
    {"id": "anthropic", "kind": ANTHROPIC, "label": "Anthropic (Claude)",
     "base_url": "https://api.anthropic.com", "model": "claude-haiku-4-5-20251001",
     "needs_key": True,
     "hint": "Haiku is the right size here — the check is a one-line yes/no, run hundreds of "
             "times a session."},
    {"id": "lmstudio", "kind": CUSTOM, "label": "LM Studio (on this PC)",
     "base_url": "http://127.0.0.1:1234/v1", "model": "qwen2.5-vl-7b", "needs_key": False,
     "hint": "LM Studio's local server. Start it from LM Studio's Developer tab."},
    {"id": "custom", "kind": CUSTOM, "label": "Anything OpenAI-compatible",
     "base_url": "", "model": "", "needs_key": False,
     "hint": "llama.cpp, vLLM, OpenRouter, Groq, Together, a company gateway — paste the base "
             "URL that ends in /v1."},
]

PRESETS_BY_ID = {p["id"]: p for p in PRESETS}


class Verdict:
    """One focus check.

    `on_task` is the answer we act on. The two escape hatches are load-bearing and deliberately
    kept distinct, because conflating them is how a monitor ends up locking someone out of their
    own machine:

    `undetermined` — we got an answer we couldn't read, or a screen we couldn't read. Not the
        user's fault, not evidence of anything. Never a block.
    `transient`    — the backend was busy or unreachable (5xx, 429, timeout, quota). Also never
        a block; the next tick simply tries again.

    `confidence` is the model's own 0–1 self-report. We do not treat it as calibrated — it is
    used only as a threshold input (see the learner) and to word the log line honestly.
    """

    __slots__ = ("on_task", "reason", "confidence", "raw", "undetermined", "transient")

    def __init__(self, on_task=True, reason="", confidence=0.0, raw="",
                 undetermined=False, transient=False):
        self.on_task = on_task
        self.reason = reason
        self.confidence = confidence
        self.raw = raw
        self.undetermined = undetermined
        self.transient = transient

    @property
    def off_task(self) -> bool:
        """True only for a clean, readable "this is not the declared task" answer."""
        return not self.on_task and not self.undetermined and not self.transient

    def __repr__(self):
        return (f"Verdict(on_task={self.on_task!r}, reason={self.reason!r}, "
                f"confidence={self.confidence:.2f}, undetermined={self.undetermined}, "
                f"transient={self.transient})")


class ProviderConfig:
    """Immutable snapshot of provider settings, so the HTTP call can run off the UI thread."""

    __slots__ = ("kind", "base_url", "model", "api_keys", "label")

    def __init__(self, kind, base_url, model, api_keys=None, label=""):
        self.kind = kind if kind in (OLLAMA, OPENAI, ANTHROPIC, CUSTOM) else OLLAMA
        self.base_url = (base_url or "").rstrip("/")
        self.model = model or ""
        self.api_keys = [k for k in (api_keys or []) if k]
        self.label = label or f"{self.kind}:{self.model}"

    def describe(self) -> str:
        return f"{self.kind}:{self.model}"


# ---------------------------------------------------------------------------------------------
# The classifier prompt
# ---------------------------------------------------------------------------------------------

# This prompt is the product. Two things about it are deliberate and worth defending:
#
# 1. It is BIASED TOWARDS "on task" — the exact opposite of the content-safety classifier in
#    `ollama_client.py`, which flags when in doubt. That asymmetry is not an inconsistency, it
#    follows from what a mistake costs. A missed frame of off-task browsing costs ten seconds.
#    A false alarm interrupts real work, and two or three of those in an afternoon and the user
#    uninstalls the app — at which point it protects nothing at all. A focus monitor that cries
#    wolf is worse than no focus monitor.
#
# 2. It is told to count SUPPORTING work as on-task. Almost nothing real is done inside a single
#    app: "math test prep" legitimately includes a YouTube lecture, a Reddit thread, a Discord
#    study group, a bank of past papers, and the file manager you found them in. A classifier
#    that only accepts a PDF viewer is measuring app choice, not focus.
FOCUS_SYSTEM = """You decide whether ONE screenshot shows a person working on the task they declared.

You are given: the user's own description of what they sat down to do, the name of the app in
front, its window title, and one screenshot. Answer with a single JSON object.

DEFAULT TO on_task. You are the interruption in someone's working day, so you must be sure
before you say no. If a screen is plausibly part of the declared work — even indirectly — it is
on task.

Count as ON TASK:
  - The obvious: the document, editor, problem set, spreadsheet, or tool the task names.
  - SUPPORTING WORK, which is most of real work: searching the web for the topic, reading
    documentation or a tutorial, watching an instructional video, a forum or Q&A thread about
    the subject, a study-group chat, email or a message thread about the task, note-taking,
    a calculator, a file manager, a password prompt, a download, a print dialog.
  - Setup and friction: an app still loading, a login screen, a settings page, an update prompt,
    an empty new tab, a desktop or lock screen, this monitoring app's own windows.
  - Anything ambiguous, unreadable, or that you simply cannot connect either way.

Count as OFF TASK only when the screen is CLEARLY unrelated to the declared task AND is
recognisably leisure or a different job: an entertainment video or show with no connection to
the topic, a game being played, a social feed being scrolled, shopping, sports scores, memes,
unrelated news, or focused work on a plainly different project.

Judge the SCREEN, not the app. YouTube showing a lecture on the topic is on task; YouTube
showing a gaming stream is off task. A browser is neither good nor bad — read what is in it.

When you say off_task, `reason` MUST quote the specific visible text or name the specific
visible content that decided it. Never invent a reason, and never guess at what is off-screen.

`confidence` is how sure you are of the answer you gave, from 0.0 to 1.0. Be honest and use the
low end freely — a 0.4 is far more useful to us than a falsely confident 0.9.

If the screenshot is blank, encrypted, DRM-protected, or otherwise unreadable, return
{"unreadable": true} instead of guessing.

Respond with ONLY compact JSON, no markdown and no prose. One of:
{"on_task": true, "confidence": 0.9}
{"on_task": false, "reason": "<specific visible evidence>", "confidence": 0.8}
{"unreadable": true}"""


def build_user_prompt(task: str, app_name: str, window_title: str, extra_notes: str = "") -> str:
    """The per-check message. App name and title are passed as text as well as being visible in
    the image: small vision models read a supplied string far more reliably than they read a
    12px title bar, and the title is usually the single most informative signal on the screen."""
    parts = [
        "THE USER'S DECLARED TASK, in their own words:",
        f"    {task.strip() or '(none given)'}",
        "",
        f"App in front: {app_name or 'unknown'}",
        f"Window title: {window_title.strip() or '(none)'}",
    ]
    if extra_notes.strip():
        # Where the learner's accumulated "you were wrong about this before" lines land.
        parts += ["", "PREVIOUSLY CONFIRMED BY THE USER — treat these as settled:",
                  extra_notes.strip()]
    parts += ["", "Is this screen part of that task? Answer in JSON."]
    return "\n".join(parts)


# ---------------------------------------------------------------------------------------------
# Response parsing (pure — unit-tested without a network)
# ---------------------------------------------------------------------------------------------

def _coerce_confidence(value) -> float:
    try:
        c = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(max(c, 0.0), 1.0)


def parse_focus_json(content) -> Verdict:
    """Turn the model's JSON text into a Verdict.

    Small models wrap JSON in ``` fences even when told not to (Gemma does it constantly), so we
    strip fences before parsing rather than throwing away an otherwise good answer.
    """
    if isinstance(content, bytes):
        content = content.decode("utf-8", "replace")
    if not isinstance(content, str):
        return Verdict(reason="parse-failed", undetermined=True)

    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
        text = text.strip()

    try:
        obj = json.loads(text)
        if not isinstance(obj, dict):
            raise ValueError("not an object")
    except Exception:
        return Verdict(reason="parse-failed", raw=content, undetermined=True)

    if obj.get("unreadable") is True:
        return Verdict(reason="screen unreadable", raw=text, undetermined=True)

    on_task = obj.get("on_task")
    if not isinstance(on_task, bool):
        # A missing or non-boolean answer is not a "no" — it is a failure to answer, and
        # treating it as a "no" would block people over a malformed reply.
        return Verdict(reason="no on_task field", raw=text, undetermined=True)

    return Verdict(on_task=on_task,
                   reason=str(obj.get("reason") or ""),
                   confidence=_coerce_confidence(obj.get("confidence")),
                   raw=text)


def _extract_content(kind: str, body) -> str:
    """Pull the assistant's text out of a provider's envelope. Raises on an unexpected shape."""
    if isinstance(body, bytes):
        body = body.decode("utf-8", "replace")
    root = json.loads(body)
    if kind == OLLAMA:
        return root["message"]["content"]
    if kind == ANTHROPIC:
        for block in root["content"]:
            if block.get("type") == "text":
                return block["text"]
        raise ValueError("no text block")
    # openai + custom
    return root["choices"][0]["message"]["content"]


def parse_response(kind: str, body) -> Verdict:
    """Envelope -> Verdict, for any provider. Pure function; the tests drive this directly."""
    try:
        content = _extract_content(kind, body)
    except Exception:
        raw = body.decode("utf-8", "replace") if isinstance(body, bytes) else str(body)
        return Verdict(reason="parse-failed", raw=raw[:400], undetermined=True)
    return parse_focus_json(content)


# ---------------------------------------------------------------------------------------------
# Request building
# ---------------------------------------------------------------------------------------------

def jpeg_base64(image, quality: float = 0.8) -> str:
    """Encode a PIL image to base64 JPEG. Same format on all four providers."""
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=int(quality * 100))
    return base64.b64encode(buf.getvalue()).decode("ascii")


def build_request(cfg: ProviderConfig, b64: str, system: str, user: str):
    """Returns (url, payload_dict, extra_headers) for the configured provider."""
    base = cfg.base_url.rstrip("/")

    if cfg.kind == OLLAMA:
        return (base + "/api/chat", {
            "model": cfg.model,
            "stream": False,
            "format": "json",
            # Keep the model resident between checks. At a 2-minute interval a cold reload each
            # time would cost more than the inference does.
            "keep_alive": "20m",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user, "images": [b64]},
            ],
            "options": {"temperature": 0, "num_predict": 160},
        }, {})

    if cfg.kind == ANTHROPIC:
        return (base + "/v1/messages", {
            "model": cfg.model,
            "max_tokens": 200,
            "temperature": 0,
            "system": system,
            "messages": [{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64",
                                             "media_type": "image/jpeg", "data": b64}},
                {"type": "text", "text": user},
            ]}],
        }, {"anthropic-version": "2023-06-01"})

    # openai + custom. A bare host gets /v1 appended; a URL that already ends in /v1 (LM Studio,
    # OpenRouter, most gateways) is left alone, because appending a second one is the single most
    # common way people misconfigure this.
    prefix = base if base.endswith("/v1") else base + "/v1"
    return (prefix + "/chat/completions", {
        "model": cfg.model,
        "max_tokens": 200,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": [
                {"type": "text", "text": user},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            ]},
        ],
    }, {})


def auth_headers(cfg: ProviderConfig, key: str) -> dict:
    """Providers disagree about where the key goes; that is the entire difference in auth."""
    if not key:
        return {}
    if cfg.kind == ANTHROPIC:
        return {"x-api-key": key}
    return {"Authorization": f"Bearer {key}"}


# ---------------------------------------------------------------------------------------------
# Transport + the never-block-on-a-hiccup policy
# ---------------------------------------------------------------------------------------------

def is_transient_code(code: int) -> bool:
    """Temporary backend trouble, worth retrying. Never evidence about the user."""
    return code in (408, 429, 500, 502, 503, 504)


def is_key_exhausted_code(code: int) -> bool:
    """This *key* can't be used right now — out of credit (402/429) or rejected (401/403).
    Triggers fail-over to the next key. If every key is out, the verdict stays transient: being
    out of API credit is our problem, and must never cost the user a block."""
    return code in (401, 402, 403, 429)


class _Attempt:
    __slots__ = ("verdict", "key_rejected")

    def __init__(self, verdict, key_rejected=False):
        self.verdict = verdict
        self.key_rejected = key_rejected


def _request(kind: str, url: str, body: bytes, headers: dict) -> _Attempt:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return _Attempt(parse_response(kind, resp.read()))
    except urllib.error.HTTPError as e:
        try:
            text = e.read().decode("utf-8", "replace")
        except Exception:
            text = ""
        code = e.code
        if is_key_exhausted_code(code):
            return _Attempt(Verdict(reason=f"key rejected (HTTP {code})", raw=text[:400],
                                    undetermined=True, transient=True), key_rejected=True)
        if is_transient_code(code):
            return _Attempt(Verdict(reason=f"AI busy (HTTP {code})", raw=text[:400],
                                    undetermined=True, transient=True))
        return _Attempt(Verdict(reason=f"API error {code}", raw=text[:400], undetermined=True))
    except Exception as e:
        # A local Ollama that isn't running lands here. Transient is the right call: the user
        # probably just hasn't started it yet, and the status line will say so.
        return _Attempt(Verdict(reason=f"AI unreachable: {e}", undetermined=True, transient=True))


def evaluate(cfg: ProviderConfig, image, task: str, app_name: str, window_title: str,
             extra_notes: str = "", sleep=None, on_key_worked=None) -> Verdict:
    """Run one focus check. Blocking; call it from the monitor thread, never the UI thread."""
    import time as _time
    sleep = sleep or _time.sleep

    if not cfg.model:
        return Verdict(reason="no model configured", undetermined=True)

    try:
        b64 = jpeg_base64(image, 0.8)
    except Exception:
        return Verdict(reason="encode-failed", undetermined=True)

    user = build_user_prompt(task, app_name, window_title, extra_notes)
    try:
        url, payload, extra = build_request(cfg, b64, FOCUS_SYSTEM, user)
        body = json.dumps(payload).encode("utf-8")
    except Exception as e:
        return Verdict(reason=f"bad-request: {e}", undetermined=True)

    keys = cfg.api_keys or [""]
    last_transient = Verdict(reason="no attempt", undetermined=True, transient=True)

    for attempt in range(MAX_ATTEMPTS):
        if attempt > 0:
            sleep(BACKOFF_SECONDS * attempt)
        exhausted = 0
        for i, key in enumerate(keys):
            headers = {"Content-Type": "application/json"}
            headers.update(extra)
            headers.update(auth_headers(cfg, key))
            result = _request(cfg.kind, url, body, headers)
            if result.key_rejected:
                exhausted += 1
                continue                      # this key is out — try the next one immediately
            if result.verdict.transient:
                last_transient = result.verdict
                break                         # back off, then start again at the first key
            if i > 0 and on_key_worked:
                on_key_worked(key)            # remember which key is working, start there next
            return result.verdict
        if exhausted == len(keys):
            last_transient = Verdict(
                reason=f"all {len(keys)} key(s) rejected or out of quota",
                undetermined=True, transient=True)
    return last_transient


def reachability(cfg: ProviderConfig) -> str:
    """Cheap "can I talk to this at all?" probe for the settings screen, so a user finds out that
    their local Ollama isn't running *now* rather than 40 minutes into a session.

    Returns "" when things look fine, or a human-readable problem.
    """
    if not cfg.base_url:
        return "no server URL set"
    if not cfg.model:
        return "no model set"
    if cfg.kind == OLLAMA:
        url, method = cfg.base_url + "/api/tags", "GET"
    elif cfg.kind == ANTHROPIC:
        return ""                              # no free unauthenticated probe; the test call covers it
    else:
        base = cfg.base_url if cfg.base_url.endswith("/v1") else cfg.base_url + "/v1"
        url, method = base + "/models", "GET"

    headers = {}
    if cfg.api_keys:
        headers.update(auth_headers(cfg, cfg.api_keys[0]))
    req = urllib.request.Request(url, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return "server reachable, but the API key was rejected"
        return f"server returned HTTP {e.code}"
    except Exception as e:
        if cfg.kind == OLLAMA and "127.0.0.1" in cfg.base_url:
            return "Ollama doesn't seem to be running on this PC (start it, then retry)"
        return f"could not reach {cfg.base_url}: {e}"

    # Reachable — now the more useful question: is the model the user typed actually there?
    if cfg.model and cfg.model.split(":")[0] and cfg.model not in body:
        return f"server is up, but '{cfg.model}' was not in its model list"
    return ""
