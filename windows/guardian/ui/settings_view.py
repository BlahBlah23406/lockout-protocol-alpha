"""Port of `UI/SettingsView.swift` — AI + alerts + blocking + tamper + passcode."""

import threading
import tkinter as tk

from . import theme as T
from .passcode_editor import PasscodeEditor
from ..models.prefs import Prefs
from ..push import pusher
from ..service import persistence


class SettingsWindow(tk.Toplevel):

    def __init__(self, master):
        super().__init__(master)
        self.prefs = Prefs.shared()
        self.title("Guardian — Settings")
        self.configure(bg=T.SPACE)
        self.geometry("620x720")
        self.attributes("-topmost", True)

        T.LcarsHeader(self, "Settings", "AI · alerts · blocking").pack(
            fill="x", padx=16, pady=(14, 10))

        body = self._scrollable()
        self._ai_section(body)
        self._alerts_section(body)
        self._blocking_section(body)
        self._tamper_section(body)
        self._passcode_section(body)

        footer = tk.Frame(self, bg=T.SPACE)
        footer.pack(fill="x", padx=16, pady=10)
        T.LcarsButton(footer, "Send test alert", self._send_test,
                      color=T.LILAC).pack(side="left", padx=(0, 8))
        T.LcarsButton(footer, "Done", self._done, color=T.ORANGE).pack(side="left")
        self.test_result = tk.Label(self, text="", bg=T.SPACE, fg=T.READOUT, font=("Segoe UI", 8))
        self.test_result.pack(anchor="w", padx=16, pady=(0, 10))

    # ---- scaffolding -------------------------------------------------------------------

    def _scrollable(self):
        wrap = tk.Frame(self, bg=T.SPACE)
        wrap.pack(fill="both", expand=True, padx=16)
        canvas = tk.Canvas(wrap, bg=T.SPACE, highlightthickness=0)
        bar = tk.Scrollbar(wrap, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=T.SPACE)
        inner.bind("<Configure>",
                   lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw", width=560)
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        canvas.bind_all("<MouseWheel>",
                        lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))
        return inner

    def _section(self, parent, title):
        tk.Label(parent, text=title.upper(), bg=T.SPACE, fg=T.GOLD,
                 font=("Segoe UI Black", 10)).pack(anchor="w", pady=(14, 4))
        box = tk.Frame(parent, bg=T.PANEL, padx=12, pady=12)
        box.pack(fill="x")
        return box

    def _labeled_entry(self, parent, label, getter, setter, width=52):
        tk.Label(parent, text=label, bg=T.PANEL, fg=T.BLUE,
                 font=("Segoe UI", 8)).pack(anchor="w", pady=(4, 1))
        e = T.entry(parent, width=width)
        e.insert(0, getter() or "")
        e.pack(anchor="w", ipady=3)
        e.bind("<FocusOut>", lambda _ev: setter(e.get()))
        return e

    def _toggle(self, parent, text, getter, setter, on_change=None):
        var = tk.BooleanVar(value=getter())

        def apply():
            setter(var.get())
            if on_change:
                on_change()
        T.checkbox(parent, text, var, apply).pack(anchor="w", pady=2)
        return var

    # ---- sections ----------------------------------------------------------------------

    def _ai_section(self, parent):
        box = self._section(parent, "AI (Ollama Cloud)")
        self._labeled_entry(box, "Base URL",
                            lambda: self.prefs.ollama_base_url,
                            lambda v: setattr(self.prefs, "ollama_base_url", v))
        self._labeled_entry(box, "Model",
                            lambda: self.prefs.ollama_model,
                            lambda v: setattr(self.prefs, "ollama_model", v))
        tk.Label(box, text="API key", bg=T.PANEL, fg=T.BLUE,
                 font=("Segoe UI", 8)).pack(anchor="w", pady=(6, 1))
        self.key1 = T.entry(box, show="•", width=52)
        self.key1.insert(0, self.prefs.ollama_api_key)
        self.key1.pack(anchor="w", ipady=3)
        tk.Label(box, text="API key 2 (backup)", bg=T.PANEL, fg=T.BLUE,
                 font=("Segoe UI", 8)).pack(anchor="w", pady=(6, 1))
        self.key2 = T.entry(box, show="•", width=52)
        self.key2.insert(0, self.prefs.ollama_api_key2)
        self.key2.pack(anchor="w", ipady=3)
        T.caption(box, "Get a key at ollama.com. Stored encrypted with your Windows account "
                       "(DPAPI). When one key runs out of quota Guardian switches to the other — "
                       "and back again when that one runs out.",
                  bg=T.PANEL).pack(anchor="w", pady=(6, 0))

    def _alerts_section(self, parent):
        box = self._section(parent, "Alerts (ntfy push)")
        self._toggle(box, "Push alerts enabled",
                     lambda: self.prefs.push_enabled,
                     lambda v: setattr(self.prefs, "push_enabled", v))
        self._labeled_entry(box, "ntfy server",
                            lambda: self.prefs.ntfy_server,
                            lambda v: setattr(self.prefs, "ntfy_server", v))
        tk.Label(box, text="Your private alert code (subscribe to this in the ntfy app):",
                 bg=T.PANEL, fg=T.BLUE, font=("Segoe UI", 8)).pack(anchor="w", pady=(8, 2))
        row = tk.Frame(box, bg=T.PANEL)
        row.pack(anchor="w")
        topic = self.prefs.ntfy_topic
        tk.Label(row, text=topic, bg=T.PANEL, fg=T.GOLD,
                 font=T.FONT_MONO).pack(side="left", padx=(0, 8))
        tk.Button(row, text="Copy", command=lambda: self._copy(topic), bg=T.PANEL, fg=T.BLUE,
                  relief="flat", bd=0, font=("Segoe UI", 8),
                  activebackground=T.PANEL, cursor="hand2").pack(side="left")

    def _blocking_section(self, parent):
        box = self._section(parent, "Blocking behaviour")
        T.caption(box, "On a violation Guardian raises a full-screen block over every monitor; "
                       "keep using the app with your passcode, or dismiss it (no passcode) and the "
                       "app is closed.", bg=T.PANEL).pack(anchor="w", pady=(0, 6))
        self._toggle(box, "TEST MODE (log only, never block)",
                     lambda: self.prefs.dry_run,
                     lambda v: setattr(self.prefs, "dry_run", v))
        self._toggle(box, "Alert when a screen can't be verified",
                     lambda: self.prefs.alert_on_unverifiable,
                     lambda v: setattr(self.prefs, "alert_on_unverifiable", v))
        self._toggle(box, "Also minimise app when it can't be verified",
                     lambda: self.prefs.close_unverifiable,
                     lambda v: setattr(self.prefs, "close_unverifiable", v))

    def _tamper_section(self, parent):
        box = self._section(parent, "Tamper resistance")
        T.caption(box, "Guardian can't stop an administrator from ending a process on Windows, but "
                       "it makes doing so loud and self-healing: it alerts your contact and "
                       "relaunches itself.", bg=T.PANEL).pack(anchor="w", pady=(0, 6))
        self._toggle(box, "Show the pledge screen when Windows Settings opens",
                     lambda: self.prefs.pledge_on_settings,
                     lambda v: setattr(self.prefs, "pledge_on_settings", v))
        self._toggle(box, "Relaunch Guardian at sign-in (persistence)",
                     lambda: self.prefs.relaunch_at_login,
                     lambda v: setattr(self.prefs, "relaunch_at_login", v),
                     on_change=persistence.apply)
        self._toggle(box, "Keep alive — relaunch within ~10s if quit or killed",
                     lambda: self.prefs.keep_alive,
                     lambda v: setattr(self.prefs, "keep_alive", v),
                     on_change=persistence.apply)
        T.caption(box, "Keep-alive is the strongest: quitting Guardian won't stick. Turn it off "
                       "here (behind your passcode) before quitting for a legitimate reason. "
                       "Guardian also alerts your contact if screen capture stops working or it "
                       "is quit.", bg=T.PANEL).pack(anchor="w", pady=(6, 0))

    def _passcode_section(self, parent):
        box = self._section(parent, "Passcode")
        T.caption(box, "Protects opening Guardian, changing these settings, keeping a blocked app "
                       "open, and stopping or quitting from the tray. Leave blank for none.",
                  bg=T.PANEL).pack(anchor="w", pady=(0, 6))
        PasscodeEditor(box).pack(anchor="w", fill="x")

    # ---- actions -----------------------------------------------------------------------

    def _copy(self, text):
        self.clipboard_clear()
        self.clipboard_append(text)

    def _save_keys(self):
        """Commit both key fields. Editing a key resets the fail-over to start at the first one."""
        k1, k2 = self.key1.get().strip(), self.key2.get().strip()
        changed = k1 != self.prefs.ollama_api_key or k2 != self.prefs.ollama_api_key2
        self.prefs.ollama_api_key = k1
        self.prefs.ollama_api_key2 = k2
        if changed:
            self.prefs.active_api_key_slot = 0

    def _send_test(self):
        self._save_keys()
        cfg = pusher.Config(self.prefs.push_enabled, self.prefs.ntfy_server, self.prefs.ntfy_topic)
        topic = self.prefs.ntfy_topic

        def work():
            err = pusher.send(cfg, "Guardian test", "Test alert from Guardian (Windows).")
            msg = f"Failed: {err}" if err else f"Test alert sent to {topic}."
            self.after(0, lambda: self.test_result.configure(text=msg))

        self.test_result.configure(text="Sending…")
        threading.Thread(target=work, name="guardian-test-push", daemon=True).start()

    def _done(self):
        self._save_keys()
        self.destroy()
