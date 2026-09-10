"""Port of `Models/Prefs.swift`.

All configuration lives in a JSON file; secrets (Ollama keys, ntfy topic, passcode hash) live in
the DPAPI store — the Windows stand-in for the macOS Keychain. Property names, defaults, storage
keys and the default guidelines are kept identical to the Mac app so the two behave the same.
"""

import hashlib
import json
import random
import string
import threading
import time

from ..paths import PREFS_FILE
from .secrets_store import SecretStore


class K:
    monitored = "monitored_apps"
    guidelines = "guidelines"
    block_mode = "block_mode"
    dry_run = "dry_run"
    alert_unver = "alert_unverifiable"
    close_unver = "close_unverifiable"
    ntfy_server = "ntfy_server"
    ntfy_topic = "ntfy_topic"            # secret store
    push_enabled = "push_enabled"
    ollama_url = "ollama_url"
    ollama_model = "ollama_model"
    ollama_key = "ollama_key"            # secret store
    ollama_key2 = "ollama_key2"          # secret store
    ollama_key_slot = "ollama_key_slot"
    pin = "pin_hash"                     # secret store
    enabled = "monitoring_enabled"
    last_vio = "last_violation_at"
    pledge = "pledge_on_settings"
    cap_granted = "screen_capture_granted"
    relaunch = "relaunch_at_login"
    keep_alive = "keep_alive_agent"
    cov_peak = "covenant_guidelines_peak_len"
    cov_armed = "covenant_ever_armed"
    # --- focus mode ---
    prov_id = "provider_id"
    prov_url = "provider_base_url"
    prov_model = "provider_model"
    focus_interval = "focus_default_interval"
    focus_acc = "focus_default_accountability"
    focus_minutes = "focus_default_minutes"
    focus_task = "focus_last_task"
    focus_notes = "focus_extra_notes"
    content_rules = "content_rules_enabled"
    learning = "learning_enabled"


# Vision-capable Gemma 4 hosted on Ollama Cloud (multimodal, 256K context).
DEFAULT_MODEL = "gemma4:31b-cloud"

DEFAULT_GUIDELINES = """Prohibited content — anything sexual or sexually suggestive:
- Pornography and sexually explicit imagery or acts.
- Real nudity OR partial nudity.
- Women or men in underwear, lingerie, bikinis, or swimwear.
- Exposed or emphasised skin in sensual areas: cleavage, breasts, midriff, buttocks, crotch,
  or bare thighs; see-through, wet, or tight clothing that sexualises the body.
- Sexualised or provocative poses, or close-ups of intimate areas.
- Any image a person could reasonably be aroused by or masturbate to.

Also flag INTENT: if a search query, typed text, URL, or title shows the user is trying to
find or view such imagery — including searching Google, Google Images, an image site, or
YouTube for sexual / nude / "hot" / "sexy" / bikini / lingerie content — flag it and quote
the text.

Ordinary clothed people, fashion, art, and educational/medical content are not violations on
their own — but when an image is borderline, it is treated as a violation rather than given
the benefit of the doubt."""


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _random_token(n: int) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(random.choice(alphabet) for _ in range(n))


class Prefs:
    """Observable settings store. `subscribe()` takes the place of SwiftUI's @Published."""

    _instance = None
    _lock = threading.RLock()

    def __init__(self):
        self._d = {}
        self._listeners = []
        self._load()

        # Remember once we've ever been armed, so the covenant can notice a later revert to TEST.
        if not self.dry_run:
            self.ever_armed = True

    @classmethod
    def shared(cls) -> "Prefs":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    # ---- persistence -------------------------------------------------------------------

    def _load(self):
        try:
            self._d = json.loads(PREFS_FILE.read_text(encoding="utf-8"))
        except Exception:
            self._d = {}

    def _save(self):
        tmp = PREFS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._d, indent=2), encoding="utf-8")
        tmp.replace(PREFS_FILE)

    def _get(self, key, default):
        return self._d.get(key, default)

    def _set(self, key, value):
        with self._lock:
            if self._d.get(key) == value:
                return
            self._d[key] = value
            self._save()
        self._notify()

    # ---- change notification -----------------------------------------------------------

    def subscribe(self, fn):
        self._listeners.append(fn)

    def _notify(self):
        for fn in list(self._listeners):
            try:
                fn()
            except Exception:
                pass

    # ---- monitored apps (set of executable identifiers, e.g. "chrome.exe") --------------

    @property
    def monitored_apps(self) -> set:
        return set(self._get(K.monitored, []))

    @monitored_apps.setter
    def monitored_apps(self, value):
        self._set(K.monitored, sorted(set(value)))

    # ---- guidelines fed to the model ---------------------------------------------------

    @property
    def guidelines(self) -> str:
        return self._get(K.guidelines, DEFAULT_GUIDELINES)

    @guidelines.setter
    def guidelines(self, value):
        self._set(K.guidelines, value)

    # ---- blocking behaviour ------------------------------------------------------------

    @property
    def block_mode(self) -> str:
        """"hide" (minimise the app — escapable) or "quit" (terminate the offending app)."""
        return self._get(K.block_mode, "hide")

    @block_mode.setter
    def block_mode(self, value):
        self._set(K.block_mode, value)

    @property
    def dry_run(self) -> bool:
        """Test/dry-run mode: evaluate + log verdicts but NEVER hide/quit anything. Default ON."""
        return bool(self._get(K.dry_run, True))

    @dry_run.setter
    def dry_run(self, value):
        self._set(K.dry_run, bool(value))
        if not value:
            self.ever_armed = True

    @property
    def alert_on_unverifiable(self) -> bool:
        return bool(self._get(K.alert_unver, True))

    @alert_on_unverifiable.setter
    def alert_on_unverifiable(self, value):
        self._set(K.alert_unver, bool(value))

    @property
    def close_unverifiable(self) -> bool:
        return bool(self._get(K.close_unver, False))

    @close_unverifiable.setter
    def close_unverifiable(self, value):
        self._set(K.close_unver, bool(value))

    # ---- push notifications (ntfy) -----------------------------------------------------

    @property
    def ntfy_server(self) -> str:
        return self._get(K.ntfy_server, "https://ntfy.sh")

    @ntfy_server.setter
    def ntfy_server(self, value):
        self._set(K.ntfy_server, value)

    @property
    def push_enabled(self) -> bool:
        return bool(self._get(K.push_enabled, True))

    @push_enabled.setter
    def push_enabled(self, value):
        self._set(K.push_enabled, bool(value))

    @property
    def ntfy_topic(self) -> str:
        """Private alert code. Auto-generated once; acts as a secret, so keep it private."""
        t = SecretStore.get(K.ntfy_topic)
        if t:
            return t
        gen = "guardian-" + _random_token(12)
        SecretStore.set(K.ntfy_topic, gen)
        return gen

    @ntfy_topic.setter
    def ntfy_topic(self, value):
        SecretStore.set(K.ntfy_topic, value)
        self._notify()

    # ---- Ollama Cloud -------------------------------------------------------------------

    @property
    def ollama_base_url(self) -> str:
        return self._get(K.ollama_url, "https://ollama.com")

    @ollama_base_url.setter
    def ollama_base_url(self, value):
        self._set(K.ollama_url, value)

    @property
    def ollama_model(self) -> str:
        return self._get(K.ollama_model, DEFAULT_MODEL)

    @ollama_model.setter
    def ollama_model(self, value):
        self._set(K.ollama_model, value)

    @property
    def ollama_api_key(self) -> str:
        """The primary API key for whichever provider is selected.

        No built-in fallback, deliberately: an earlier revision shipped a real key as a literal in
        this file, and the repo is public. An empty key produces a clear "add your API key"
        message, which is a better first run than a shared key everyone exhausts at once.
        """
        k = SecretStore.get(K.ollama_key)
        if k:
            return k
        import os
        # Convenience for developers and for scripted setup, nothing more.
        for var in ("LOCKOUT_API_KEY", "OLLAMA_CLOUD_KEY", "OLLAMA_API_KEY"):
            env_key = os.environ.get(var, "").strip()
            if env_key:
                SecretStore.set(K.ollama_key, env_key)
                return env_key
        return ""

    @ollama_api_key.setter
    def ollama_api_key(self, value):
        SecretStore.set(K.ollama_key, value)
        self._notify()

    @property
    def ollama_api_key2(self) -> str:
        """Backup key. When the active key runs out of quota the client falls over to the other."""
        return SecretStore.get(K.ollama_key2) or ""

    @ollama_api_key2.setter
    def ollama_api_key2(self, value):
        SecretStore.set(K.ollama_key2, value)
        self._notify()

    @property
    def active_api_key_slot(self) -> int:
        return min(max(int(self._get(K.ollama_key_slot, 0)), 0), 1)

    @active_api_key_slot.setter
    def active_api_key_slot(self, value):
        self._set(K.ollama_key_slot, min(max(int(value), 0), 1))

    @property
    def api_keys(self) -> list:
        """Configured keys, active one first, blanks and duplicates removed."""
        slots = [self.ollama_api_key.strip(), self.ollama_api_key2.strip()]
        ordered = list(reversed(slots)) if self.active_api_key_slot == 1 else slots
        seen, out = set(), []
        for k in ordered:
            if k and k not in seen:
                seen.add(k)
                out.append(k)
        return out

    def promote_api_key(self, key: str) -> None:
        """Remember that `key` is the one currently working, so the next request starts there."""
        key = (key or "").strip()
        if key and key == self.ollama_api_key.strip():
            slot = 0
        elif key and key == self.ollama_api_key2.strip():
            slot = 1
        else:
            return
        if self.active_api_key_slot != slot:
            self.active_api_key_slot = slot

    # ---- model provider (focus mode) ----------------------------------------------------
    #
    # A preset id plus optional overrides: the preset gives a working default in one click, the
    # overrides let someone point at a gateway we've never heard of.

    @property
    def provider_id(self) -> str:
        return self._get(K.prov_id, "ollama-cloud")

    @provider_id.setter
    def provider_id(self, value):
        from ..ai import providers
        preset = providers.PRESETS_BY_ID.get(value)
        if preset is None:
            return
        with self._lock:
            self._d[K.prov_id] = value
            # Switching provider rewrites URL + model: an Ollama model name carried over to
            # Anthropic just 404s later.
            self._d[K.prov_url] = preset["base_url"]
            self._d[K.prov_model] = preset["model"]
            self._save()
        self._notify()

    @property
    def provider_base_url(self) -> str:
        from ..ai import providers
        preset = providers.PRESETS_BY_ID.get(self.provider_id, {})
        return self._get(K.prov_url, preset.get("base_url", ""))

    @provider_base_url.setter
    def provider_base_url(self, value):
        self._set(K.prov_url, (value or "").strip())

    @property
    def provider_model(self) -> str:
        from ..ai import providers
        preset = providers.PRESETS_BY_ID.get(self.provider_id, {})
        return self._get(K.prov_model, preset.get("model", ""))

    @provider_model.setter
    def provider_model(self, value):
        self._set(K.prov_model, (value or "").strip())

    @property
    def provider_needs_key(self) -> bool:
        from ..ai import providers
        return bool(providers.PRESETS_BY_ID.get(self.provider_id, {}).get("needs_key"))

    def provider_config(self):
        """Snapshot for the monitor thread. Keys are omitted for local providers, so a cloud key
        is never sent to 127.0.0.1."""
        from ..ai import providers
        preset = providers.PRESETS_BY_ID.get(self.provider_id, providers.PRESETS[0])
        keys = self.api_keys if preset.get("needs_key") or self.provider_id == "custom" else []
        return providers.ProviderConfig(kind=preset["kind"], base_url=self.provider_base_url,
                                        model=self.provider_model, api_keys=keys,
                                        label=preset["label"])

    # ---- focus session defaults ----------------------------------------------------------

    @property
    def focus_interval(self) -> int:
        from ..focus.session import DEFAULT_INTERVAL, clamp_interval
        return clamp_interval(self._get(K.focus_interval, DEFAULT_INTERVAL))

    @focus_interval.setter
    def focus_interval(self, value):
        from ..focus.session import clamp_interval
        self._set(K.focus_interval, clamp_interval(value))

    @property
    def focus_accountability(self) -> str:
        from ..focus.session import ACC_SELF, ACCOUNTABILITY_LEVELS
        v = self._get(K.focus_acc, ACC_SELF)
        return v if v in ACCOUNTABILITY_LEVELS else ACC_SELF

    @focus_accountability.setter
    def focus_accountability(self, value):
        from ..focus.session import ACCOUNTABILITY_LEVELS
        if value in ACCOUNTABILITY_LEVELS:
            self._set(K.focus_acc, value)

    @property
    def focus_minutes(self) -> int:
        return max(int(self._get(K.focus_minutes, 60) or 0), 0)

    @focus_minutes.setter
    def focus_minutes(self, value):
        self._set(K.focus_minutes, max(int(value or 0), 0))

    @property
    def last_task(self) -> str:
        """Prefilled into the start box."""
        return self._get(K.focus_task, "")

    @last_task.setter
    def last_task(self, value):
        self._set(K.focus_task, (value or "").strip()[:400])

    @property
    def focus_notes(self) -> str:
        """Standing notes appended to every check. Hand-written; the learner writes elsewhere."""
        return self._get(K.focus_notes, "")

    @focus_notes.setter
    def focus_notes(self, value):
        self._set(K.focus_notes, (value or "").strip()[:1500])

    @property
    def content_rules_enabled(self) -> bool:
        """The original content-safety classifier, opt-in. Running both doubles the cost of a
        check, so it is off by default."""
        return bool(self._get(K.content_rules, False))

    @content_rules_enabled.setter
    def content_rules_enabled(self, value):
        self._set(K.content_rules, bool(value))

    @property
    def learning_enabled(self) -> bool:
        """Experimental. Off by default: a self-control tool that learns from you can be taught
        to stop stopping you. See learner/README.md for the anti-gaming design."""
        return bool(self._get(K.learning, False))

    @learning_enabled.setter
    def learning_enabled(self, value):
        self._set(K.learning, bool(value))

    # ---- access / override passcode (SHA-256 hash in the secret store) ------------------

    @property
    def pin_set(self) -> bool:
        return SecretStore.get(K.pin) is not None

    def set_pin(self, pin: str) -> None:
        SecretStore.set(K.pin, sha256(pin))
        self._notify()

    def clear_pin(self) -> None:
        SecretStore.delete(K.pin)
        self._notify()

    def check_pin(self, pin: str) -> bool:
        h = SecretStore.get(K.pin)
        return bool(h) and h == sha256(pin)

    # ---- tamper resistance ---------------------------------------------------------------

    @property
    def pledge_on_settings(self) -> bool:
        return bool(self._get(K.pledge, True))

    @pledge_on_settings.setter
    def pledge_on_settings(self, value):
        self._set(K.pledge, bool(value))

    @property
    def screen_capture_granted(self) -> bool:
        """Last-known screen-capture ability. The tamper guard compares against this so losing
        capture is reported rather than failing silently."""
        return bool(self._get(K.cap_granted, False))

    @screen_capture_granted.setter
    def screen_capture_granted(self, value):
        self._set(K.cap_granted, bool(value))

    @property
    def relaunch_at_login(self) -> bool:
        return bool(self._get(K.relaunch, True))

    @relaunch_at_login.setter
    def relaunch_at_login(self, value):
        self._set(K.relaunch, bool(value))

    @property
    def keep_alive(self) -> bool:
        """Stronger persistence: a watchdog that relaunches Guardian within ~10s of ANY exit."""
        return bool(self._get(K.keep_alive, True))

    @keep_alive.setter
    def keep_alive(self, value):
        self._set(K.keep_alive, bool(value))

    # ---- safety covenant -----------------------------------------------------------------

    @property
    def guidelines_peak_len(self) -> int:
        return int(self._get(K.cov_peak, 0))

    @guidelines_peak_len.setter
    def guidelines_peak_len(self, value):
        self._set(K.cov_peak, int(value))

    @property
    def ever_armed(self) -> bool:
        return bool(self._get(K.cov_armed, False))

    @ever_armed.setter
    def ever_armed(self, value):
        self._set(K.cov_armed, bool(value))

    # ---- runtime state ---------------------------------------------------------------------

    @property
    def monitoring_enabled(self) -> bool:
        return bool(self._get(K.enabled, False))

    @monitoring_enabled.setter
    def monitoring_enabled(self, value):
        self._set(K.enabled, bool(value))

    @property
    def last_violation_at(self):
        v = self._get(K.last_vio, None)
        return float(v) if v is not None else None

    @last_violation_at.setter
    def last_violation_at(self, value):
        self._set(K.last_vio, float(value) if value is not None else None)


def now() -> float:
    return time.time()
