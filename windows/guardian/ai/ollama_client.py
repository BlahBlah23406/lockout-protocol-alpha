"""Port of `AI/OllamaClient.swift`.

Sends a screenshot to an Ollama (Cloud) vision model and asks for a strict JSON verdict, using the
`/api/chat` endpoint with a base64 JPEG attached to the user message. The classifier prompt, the
retry/fail-over policy and the HTTP code classification are carried over unchanged from the Mac
app; only the platform nouns in case (C) are the Windows equivalents of the macOS ones.
"""

import base64
import io
import json
import urllib.error
import urllib.request

# Transient-failure retry policy (fixes the "503 closes my apps" bug).
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 0.8
REQUEST_TIMEOUT = 90


class Verdict:
    """A strict content-safety verdict from the vision model.

    `undetermined` = the model could not be reached or its answer couldn't be parsed. Callers treat
    that as "couldn't verify" and handle it safely (alert, never a hard block).
    `transient` = a temporary server/network failure (HTTP 503/429/5xx, timeout) — the AI backend
    being busy, NOT the user hiding anything. Callers log + skip it and never quit/hide an app.
    """

    __slots__ = ("violation", "reason", "raw", "undetermined", "transient")

    def __init__(self, violation=False, reason="", raw="", undetermined=False, transient=False):
        self.violation = violation
        self.reason = reason
        self.raw = raw
        self.undetermined = undetermined
        self.transient = transient

    def __repr__(self):
        return (f"Verdict(violation={self.violation!r}, reason={self.reason!r}, "
                f"undetermined={self.undetermined}, transient={self.transient})")


class Config:
    """Snapshot of the bits of Prefs we need, so the network call can run off the UI thread."""

    __slots__ = ("base_url", "api_keys", "model", "guidelines")

    def __init__(self, base_url, api_keys, model, guidelines):
        self.base_url = base_url
        self.api_keys = api_keys
        self.model = model
        self.guidelines = guidelines


# The classifier prompt. Deliberately strict: it flags when in doubt. Case (C) makes the monitoring
# self-defending — a visible attempt to disable it is itself a violation.
STRICT_SYSTEM = """You are a STRICT content-safety classifier for a personal accountability app on the user's
Windows PC. Its ONE purpose is to keep this user away from sexual and sexually-suggestive imagery,
and to catch any attempt to go looking for it. When in doubt, you FLAG — err on the side of
flagging, not permitting. You are given ONE computer screenshot and a list of GUIDELINES.

Report a violation (true) when ANY of the following is true:
  (A) VISIBLE IMAGERY that is sexual or sexually suggestive. This is intentionally broad:
      pornography or explicit sexual acts; real nudity OR partial nudity; a woman or man in
      underwear, lingerie, a bikini, or swimwear; exposed or emphasised cleavage, breasts,
      midriff, buttocks, crotch, or bare thighs; see-through, wet, or tight clothing that
      sexualises the body; sexualised or provocative poses; close-ups of intimate body
      areas. If a reasonable person could find the image sexually arousing or masturbate to
      it, FLAG IT.
  (B) INTENT shown in visible TEXT — a search query, typed input, URL, video/page title, or
      an app/site being opened — that shows the user is trying to FIND or VIEW such content.
      This explicitly INCLUDES typing a search into Google, Google Images, an image site,
      YouTube, TikTok, Instagram, Reddit, or Pinterest where the query seeks sexual, nude,
      "hot", "sexy", bikini, lingerie, or otherwise provocative images or video of people;
      opening a site/app whose name denotes pornography; or navigating an image/video search
      clearly aimed at ogling people. Judge the INTENT behind the text, not only whether an
      explicit word is present.
  (C) TAMPERING — visible text or UI showing a concrete attempt to DISABLE or EVADE Ollama
      (the AI service that powers this monitoring) or Guardian itself. Flag only an actual
      action that would break the monitoring, such as: a command to stop, kill, or uninstall
      the "ollama" process/service or Guardian (`taskkill /f /im ollama.exe`, `taskkill /f /im
      pythonw.exe`, `Stop-Process -Name Guardian`, `sc stop`, ending Guardian in Task Manager,
      deleting its Run/startup entry or scheduled task); revoking, deleting, or replacing the
      Ollama API key, or repointing the server URL at a dead or fake endpoint; turning off
      Guardian's screen-capture or screenshot permission in Windows privacy settings; or
      editing the hosts file, a firewall rule, DNS, proxy, or VPN to block ollama.com.
      Flag these even when no sexual content is present.

      Merely READING or WORKING WITH Ollama or Guardian is NOT tampering: the ollama.com
      website, docs, or model listings; an Ollama app window; the source code of either
      project (including this classifier prompt itself); a settings screen merely being
      viewed; or a terminal that mentions "ollama" without a disabling command.
      If you cannot point to a specific command or action that would actually break the
      monitoring, do NOT flag case (C) — this narrowing applies to case (C) only and does
      not soften cases (A) or (B) in any way.

Respond false ONLY for genuinely innocent, non-sexual screens: the desktop, taskbar, app
windows, news, education, this app's own screens, ordinary chats/AI apps, code, maps,
settings, email, shopping for non-sexual items, or a word appearing incidentally with no
sexual intent — UNLESS the screen shows an actual attempt to disable Ollama or Guardian per
case (C). But when imagery is even borderline sexual, FLAG IT — do NOT give the benefit of
the doubt.

When you flag based on text/intent (case B or C), the reason MUST quote the specific visible
text. Never invent a reason.

Respond with ONLY a compact JSON object, no markdown, no prose. Either:
{"violation": false}
or
{"violation": true, "reason": "<specific visible content or quoted text>"}"""


def is_transient_code(code: int) -> bool:
    """HTTP codes we treat as temporary backend hiccups worth retrying (never a "can't see")."""
    return code in (408, 429, 500, 502, 503, 504)


def is_key_exhausted_code(code: int) -> bool:
    """Codes meaning THIS KEY can't be used right now — quota/credit exhausted (402/429) or the key
    being rejected outright (401/403). These trigger fail-over to the other key. Still never a
    block on their own: if every key is out, the verdict stays transient."""
    return code in (401, 402, 403, 429)


def jpeg_base64(image, quality: float = 0.8) -> str:
    """Encode a PIL image to base64 JPEG (no line wrapping), matching the Mac/Android format."""
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=int(quality * 100))
    return base64.b64encode(buf.getvalue()).decode("ascii")


def parse_verdict(body) -> Verdict:
    """Pure parse of an Ollama /api/chat response body into a Verdict. Pure function for tests."""
    if isinstance(body, bytes):
        try:
            body = body.decode("utf-8", "replace")
        except Exception:
            body = ""
    try:
        root = json.loads(body)
        content = root["message"]["content"]
        if not isinstance(content, str):
            raise ValueError("content not a string")
    except Exception:
        return Verdict(reason="parse-failed", raw=body or "", undetermined=True)

    try:
        obj = json.loads(content.strip())
        if not isinstance(obj, dict):
            raise ValueError("not an object")
    except Exception:
        return Verdict(reason="parse-failed", raw=content, undetermined=True)

    violation = obj.get("violation")
    violation = bool(violation) if isinstance(violation, bool) else False
    reason = obj.get("reason") or ""
    return Verdict(violation=violation, reason=str(reason), raw=content)


def _trimmed_slash(s: str) -> str:
    return s.rstrip("/")


class _Attempt:
    """One HTTP call with one key. `key_rejected` means "this key is out/invalid, try another"."""

    __slots__ = ("verdict", "key_rejected")

    def __init__(self, verdict, key_rejected=False):
        self.verdict = verdict
        self.key_rejected = key_rejected


def _request(url: str, body: bytes, key: str) -> _Attempt:
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return _Attempt(parse_verdict(resp.read()))
    except urllib.error.HTTPError as e:
        try:
            text = e.read().decode("utf-8", "replace")
        except Exception:
            text = ""
        code = e.code
        if is_key_exhausted_code(code):
            return _Attempt(
                Verdict(reason=f"key rejected (HTTP {code})", raw=text,
                        undetermined=True, transient=True),
                key_rejected=True)
        if is_transient_code(code):
            return _Attempt(Verdict(reason=f"AI busy (HTTP {code})", raw=text,
                                    undetermined=True, transient=True))
        return _Attempt(Verdict(reason=f"API error {code}", raw=text, undetermined=True))
    except Exception as e:
        # Network drops / timeouts are transient too — keep retrying, never hide/quit on these.
        return _Attempt(Verdict(reason=f"AI unreachable: {e}", undetermined=True, transient=True))


class OllamaClient:

    def __init__(self, prefs):
        self.prefs = prefs

    def config(self) -> Config:
        p = self.prefs
        return Config(p.ollama_base_url, p.api_keys, p.ollama_model, p.guidelines)

    def evaluate(self, image, cfg: Config, sleep=None) -> Verdict:
        import time as _time
        sleep = sleep or _time.sleep

        try:
            b64 = jpeg_base64(image, 0.8)
        except Exception:
            return Verdict(reason="encode-failed", undetermined=True)

        user = (
            "GUIDELINES (prohibited content):\n"
            f"{cfg.guidelines}\n\n"
            "Classify the attached screenshot. Flag it if prohibited content is visible, if the "
            "visible text shows the user is trying to access prohibited content, OR if the screen "
            "shows an attempt to disable or evade Ollama or Guardian (case C). Ignore innocent/"
            "incidental mentions, ordinary development work on Guardian or Ollama, and unselected "
            "suggestions."
        )

        payload = {
            "model": cfg.model,
            "stream": False,
            "format": "json",
            # Keep the model warm between checks — avoids cold-start reloads.
            "keep_alive": "20m",
            "messages": [
                {"role": "system", "content": STRICT_SYSTEM},
                {"role": "user", "content": user, "images": [b64]},
            ],
            # num_predict caps output so the model can't ramble; we only need a tiny JSON verdict.
            "options": {"temperature": 0, "num_predict": 80},
        }

        url = _trimmed_slash(cfg.base_url) + "/api/chat"
        try:
            body = json.dumps(payload).encode("utf-8")
        except Exception:
            return Verdict(reason="bad-request", undetermined=True)

        # Keys to try, the one that last worked first. When a key is out of quota we retry the same
        # request with the other one and remember the switch, so the two alternate as each runs out.
        keys = cfg.api_keys or [""]

        last_transient = Verdict(reason="no attempt", undetermined=True, transient=True)
        for attempt in range(MAX_ATTEMPTS):
            if attempt > 0:
                sleep(BACKOFF_SECONDS * attempt)
            exhausted = 0
            for i, key in enumerate(keys):
                result = _request(url, body, key)
                if result.key_rejected:
                    exhausted += 1
                    continue                    # this key is out — try the other one right away
                if result.verdict.transient:
                    last_transient = result.verdict
                    break                       # back off, then start over at the active key
                # Success (or a definite error) on this key: start with it next time.
                if i > 0:
                    self.prefs.promote_api_key(key)
                return result.verdict
            if exhausted == len(keys):
                # Every key is out of quota right now. Transient, never a block: next tick retries.
                last_transient = Verdict(
                    reason=f"AI quota exhausted on all {len(keys)} key(s)",
                    undetermined=True, transient=True)
        return last_transient
