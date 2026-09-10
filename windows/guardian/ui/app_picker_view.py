"""Port of `UI/AppPickerView.swift` + `UI/AppSelectList.swift`.

Pick which apps Guardian monitors. Lists every discoverable installed app, searchable. Guardian
only screenshots + checks an app while it is the foreground window. Emulated devices are tagged so
unticking one is at least a deliberate, informed act.
"""

import threading
import tkinter as tk

from . import theme as T
from ..capture import emulators, installed_apps
from ..models.prefs import Prefs


class AppPickerWindow(tk.Toplevel):

    def __init__(self, master, selection=None, on_done=None, title=None, subtitle=None,
                 note=None):
        """Two jobs, one window: with no arguments it edits the saved default watchlist; with
        `selection` and `on_done` it becomes a session-scoped picker that returns the choice
        instead of saving it."""
        super().__init__(master)
        self.prefs = Prefs.shared()
        self.on_done = on_done
        self.title(title or "Guardian — Monitored Apps")
        self.configure(bg=T.SPACE)
        self.geometry("580x680")
        self.attributes("-topmost", True)

        self.selection = set(self.prefs.monitored_apps if selection is None else selection)
        self.apps = []
        self.vars = {}

        T.LcarsHeader(self, title or "Monitored Apps",
                      subtitle or "Select what to watch").pack(fill="x", padx=16, pady=(14, 8))
        self.summary = T.caption(
            self, note or "Guardian only screenshots + checks an app while it is the foreground "
                          "window — and only during a focus session.",
            wraplength=540)
        self.summary.pack(anchor="w", padx=16)

        bar = tk.Frame(self, bg=T.SPACE)
        bar.pack(fill="x", padx=16, pady=(8, 4))
        self.count = tk.Label(bar, text="", bg=T.SPACE, fg=T.BLUE, font=T.FONT_MONO)
        self.count.pack(side="left")
        tk.Button(bar, text="None", command=self._select_none, bg=T.SPACE, fg=T.LILAC,
                  relief="flat", bd=0, font=("Segoe UI", 8), cursor="hand2",
                  activebackground=T.SPACE).pack(side="right")
        tk.Button(bar, text="All apps", command=self._select_all, bg=T.SPACE, fg=T.ORANGE,
                  relief="flat", bd=0, font=("Segoe UI", 8), cursor="hand2",
                  activebackground=T.SPACE).pack(side="right", padx=(0, 10))
        tk.Button(bar, text="Rescan", command=self._rescan, bg=T.SPACE, fg=T.BLUE,
                  relief="flat", bd=0, font=("Segoe UI", 8), cursor="hand2",
                  activebackground=T.SPACE).pack(side="right", padx=(0, 10))

        self.query = tk.StringVar()
        search = T.entry(self, width=60)
        search.configure(textvariable=self.query)
        search.pack(fill="x", padx=16, ipady=4)
        self.query.trace_add("write", lambda *_: self._render())

        panel = T.ReadoutPanel(self)
        panel.pack(fill="both", expand=True, padx=16, pady=10)
        self.canvas = tk.Canvas(panel, bg=T.PANEL, highlightthickness=0)
        bar2 = tk.Scrollbar(panel, orient="vertical", command=self.canvas.yview)
        self.list_frame = tk.Frame(self.canvas, bg=T.PANEL)
        self.list_frame.bind("<Configure>",
                             lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.list_frame, anchor="nw", width=510)
        self.canvas.configure(yscrollcommand=bar2.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        bar2.pack(side="right", fill="y")
        self.canvas.bind_all("<MouseWheel>",
                             lambda e: self.canvas.yview_scroll(int(-e.delta / 120), "units"))

        T.LcarsButton(self, "Done", self._done, color=T.ORANGE).pack(
            anchor="w", padx=16, pady=(0, 14))

        self._loading = tk.Label(self.list_frame, text="scanning installed apps…",
                                 bg=T.PANEL, fg=T.READOUT, font=T.FONT_MONO)
        self._loading.pack(anchor="w", padx=8, pady=8)
        self._load_async()

    # ---- data --------------------------------------------------------------------------

    def _load_async(self, refresh=False):
        def work():
            apps = installed_apps.all(refresh=refresh)
            self.after(0, lambda: self._loaded(apps))
        threading.Thread(target=work, name="guardian-app-scan", daemon=True).start()

    def _loaded(self, apps):
        self.apps = apps
        self._render()

    def _rescan(self):
        for w in self.list_frame.winfo_children():
            w.destroy()
        tk.Label(self.list_frame, text="rescanning…", bg=T.PANEL, fg=T.READOUT,
                 font=T.FONT_MONO).pack(anchor="w", padx=8, pady=8)
        self._load_async(refresh=True)

    # ---- rendering ---------------------------------------------------------------------

    def _filtered(self):
        q = self.query.get().strip().lower()
        if not q:
            return self.apps
        return [a for a in self.apps if q in a.name.lower() or q in a.id.lower()]

    def _render(self):
        for w in self.list_frame.winfo_children():
            w.destroy()
        self.vars = {}
        rows = self._filtered()
        if not rows:
            tk.Label(self.list_frame, text="— no matching apps —", bg=T.PANEL,
                     fg=T.READOUT, font=T.FONT_MONO).pack(anchor="w", padx=8, pady=8)
        for app in rows:
            self._row(app)
        self.count.configure(text=f"{len(self.selection)} selected")

    def _row(self, app):
        var = tk.BooleanVar(value=app.id in self.selection)
        self.vars[app.id] = var
        row = tk.Frame(self.list_frame, bg=T.PANEL)
        row.pack(fill="x", anchor="w", padx=4)

        def toggled():
            if var.get():
                self.selection.add(app.id)
            else:
                self.selection.discard(app.id)
            self.count.configure(text=f"{len(self.selection)} selected")

        tk.Checkbutton(row, variable=var, command=toggled, bg=T.PANEL, activebackground=T.PANEL,
                       selectcolor=T.SPACE, highlightthickness=0, bd=0).pack(side="left")
        box = tk.Frame(row, bg=T.PANEL)
        box.pack(side="left", anchor="w")
        line = tk.Frame(box, bg=T.PANEL)
        line.pack(anchor="w")
        tk.Label(line, text=app.name, bg=T.PANEL, fg=T.READOUT,
                 font=T.FONT_UI_BOLD).pack(side="left")
        if emulators.is_emulator(app.id):
            tk.Label(line, text=" EMULATED DEVICE ", bg=T.ORANGE, fg=T.SPACE,
                     font=("Consolas", 7, "bold")).pack(side="left", padx=6)
        tk.Label(box, text=app.id, bg=T.PANEL, fg=T.BLUE,
                 font=("Consolas", 7)).pack(anchor="w")

    # ---- actions -----------------------------------------------------------------------

    def _select_all(self):
        self.selection = {a.id for a in self.apps}
        self._render()

    def _select_none(self):
        self.selection = set()
        self._render()

    def _done(self):
        if self.on_done is not None:
            self.on_done(set(self.selection))       # session-scoped: the caller decides
        else:
            self.prefs.monitored_apps = self.selection
        self.destroy()
