"""Model providers for the focus classifier.

Four kinds cover essentially every vision endpoint:

    ollama    /api/chat with `images: [b64]`      — local (no key) or ollama.com (key)
    openai    /v1/chat/completions with a
              `data:image/jpeg;base64,` image_url — OpenAI, LM Studio, llama.cpp, vLLM, …
    anthropic /v1/messages with an image block
    custom    the `openai` wire format with a user-supplied base URL

The request shape differs per provider; the retry and key fail-over policy is shared, because the
rule it enforces — a backend problem must never look like the user being off task — applies
equally to all of them.
"""

import base64
import io
import json
import urllib.error
import urllib.request

MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 0.8
REQUEST_TIMEOUT = 90

OLLAMA = "ollama"
OPENAI = "openai"
ANTHROPIC = "anthropic"
CUSTOM = "custom"

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

    `undetermined` (unreadable answer or unreadable screen) and `transient` (backend busy,
    unreachable, or out of quota) are kept distinct from `on_task=False`, and neither ever blocks.
    `confidence` is the model's own self-report and is not treated as calibrated.
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
        """True only for a clean, readable "not the declared task" answer."""
        return not self.on_task and not self.undetermined and not self.transient

    def __repr__(self):
        return (f"Verdict(on_task={self.on_task!r}, reason={self.reason!r}, "
                f"confidence={self.confidence:.2f}, undetermined={self.undetermined}, "
                f"transient={self.transient})")


class ProviderConfig:
    """Immutable snapshot, so the HTTP call can run off the UI thread."""

    __slots__ = ("kind", "base_url", "model", "api_keys", "label")

    def __init__(self, kind, base_url, model, api_keys=None, label=""):
        self.kind = kind if kind in (OLLAMA, OPENAI, ANTHROPIC, CUSTOM) else OLLAMA
        self.base_url = (base_url or "").rstrip("/")
        self.model = model or ""
        self.api_keys = [k for k in (api_keys or []) if k]
        self.label = label or f"{self.kind}:{self.model}"

    def describe(self) -> str:
        return f"{self.kind}:{self.model}"


# Biased towards "on task", which is the opposite of the content-safety classifier in
# `ollama_client.py`. The asymmetry follows from what a mistake costs: a missed frame of off-task
# browsing costs seconds, a false alarm interrupts real work and gets the app uninstalled. It also
# counts supporting work as on-task, because almost nothing real happens inside a single app.
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
    """App name and title are supplied as text as well as being visible in the image: small vision
    models read a given string far more reliably than a 12px title bar."""
    parts = [
        "THE USER'S DECLARED TASK, in their own words:",
        f"    {task.strip() or '(none given)'}",
        "",
        f"App in front: {app_name or 'unknown'}",
        f"Window title: {window_title.strip() or '(none)'}",
    ]
    if extra_notes.strip():
        parts += ["", "PREVIOUSLY CONFIRMED BY THE USER — treat these as settled:",
                  extra_notes.strip()]
    parts += ["", "Is this screen part of that task? Answer in JSON."]
    return "\n".join(parts)


def _coerce_confidence(value) -> float:
    try:
        c = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(max(c, 0.0), 1.0)


def parse_focus_json(content) -> Verdict:
    if isinstance(content, bytes):
        content = content.decode("utf-8", "replace")
    if not isinstance(content, str):
        return Verdict(reason="parse-failed", undetermined=True)

    text = content.strip()
    # Small models fence their JSON even when told not to; stripping is cheaper than discarding
    # an otherwise good answer.
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
        # A missing answer is a failure to answer, not a "no". Treating it as "no" would block
        # people over a malformed reply.
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
    return root["choices"][0]["message"]["content"]


def parse_response(kind: str, body) -> Verdict:
    try:
        content = _extract_content(kind, body)
    except Exception:
        raw = body.decode("utf-8", "replace") if isinstance(body, bytes) else str(body)
        return Verdict(reason="parse-failed", raw=raw[:400], undetermined=True)
    return parse_focus_json(content)


def jpeg_base64(image, quality: float = 0.8) -> str:
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=int(quality * 100))
    return base64.b64encode(buf.getvalue()).decode("ascii")


def build_request(cfg: ProviderConfig, b64: str, system: str, user: str):
    """Returns (url, payload_dict, extra_headers)."""
    base = cfg.base_url.rstrip("/")

    if cfg.kind == OLLAMA:
        return (base + "/api/chat", {
            "model": cfg.model,
            "stream": False,
            "format": "json",
            # At a 2-minute interval a cold model reload each time costs more than the inference.
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

    # A URL that already ends in /v1 is left alone. Appending a second one is the most common way
    # people misconfigure this.
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
    if not key:
        return {}
    if cfg.kind == ANTHROPIC:
        return {"x-api-key": key}
    return {"Authorization": f"Bearer {key}"}


def is_transient_code(code: int) -> bool:
    """Temporary backend trouble, worth retrying. Never evidence about the user."""
    return code in (408, 429, 500, 502, 503, 504)


def is_key_exhausted_code(code: int) -> bool:
    """This key is out of credit or rejected — fail over to the next one. If every key is out the
    verdict stays transient: being out of API credit must never cost the user a block."""
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
        # A local Ollama that isn't running lands here; the user probably just hasn't started it.
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
                continue
            if result.verdict.transient:
                last_transient = result.verdict
                break                         # back off, then start again at the first key
            if i > 0 and on_key_worked:
                on_key_worked(key)            # remember which key works, start there next time
            return result.verdict
        if exhausted == len(keys):
            last_transient = Verdict(
                reason=f"all {len(keys)} key(s) rejected or out of quota",
                undetermined=True, transient=True)
    return last_transient


def reachability(cfg: ProviderConfig) -> str:
    """"Can I talk to this at all?" probe for the settings screen. Returns "" when fine, or a
    human-readable problem."""
    if not cfg.base_url:
        return "no server URL set"
    if not cfg.model:
        return "no model set"
    if cfg.kind == OLLAMA:
        url, method = cfg.base_url + "/api/tags", "GET"
    elif cfg.kind == ANTHROPIC:
        return ""                              # no free unauthenticated probe
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

    if cfg.model and cfg.model.split(":")[0] and cfg.model not in body:
        return f"server is up, but '{cfg.model}' was not in its model list"
    return ""
