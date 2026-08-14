"""Port of `Push/Pusher.swift`.

Zero-setup push alerts via ntfy (https://ntfy.sh). No account, no password — the partner just
subscribes the free ntfy app (or web) to the private topic code. We POST the alert text to
{server}/{topic}. The topic string is unguessable, so it doubles as the secret.
"""

import urllib.error
import urllib.request

TIMEOUT = 20


class PushError(Exception):
    pass


class Config:
    __slots__ = ("enabled", "server", "topic")

    def __init__(self, enabled, server, topic):
        self.enabled = enabled
        self.server = server
        self.topic = topic


def _ascii_header(s: str) -> str:
    """ntfy header values must be ASCII; strip anything else so titles never break the request."""
    out = "".join(ch for ch in s if 32 <= ord(ch) <= 126)
    return out or "Guardian"


def send(cfg: Config, title: str, message: str):
    """Returns None on success, or an error string."""
    if not cfg.enabled:
        return "push disabled"
    if not cfg.topic:
        return "no topic"

    url = cfg.server.rstrip("/") + "/" + cfg.topic
    req = urllib.request.Request(
        url, data=message.encode("utf-8"), method="POST",
        headers={
            "Title": _ascii_header(title),
            "Priority": "high",
            "Tags": "rotating_light",
        })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            if not (200 <= resp.status <= 299):
                return f"ntfy {resp.status}"
            return None
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        return f"ntfy {e.code}: {body}"
    except Exception as e:
        return str(e)
