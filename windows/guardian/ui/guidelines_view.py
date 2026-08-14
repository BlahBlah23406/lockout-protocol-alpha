"""Port of `UI/GuidelinesView.swift`.

Edit the prohibited-content guidelines fed to the model.
"""

import tkinter as tk

from . import theme as T
from ..models.prefs import DEFAULT_GUIDELINES, Prefs


class GuidelinesWindow(tk.Toplevel):

    def __init__(self, master):
        super().__init__(master)
        self.prefs = Prefs.shared()
        self.title("Guardian — Guidelines")
        self.configure(bg=T.SPACE)
        self.geometry("640x540")
        self.attributes("-topmost", True)

        T.LcarsHeader(self, "Guidelines", "What counts as a violation").pack(
            fill="x", padx=16, pady=(14, 8))
        T.caption(self, "Describe the content Guardian should flag. The AI sees each screenshot "
                        "and these rules.", wraplength=600).pack(anchor="w", padx=16)

        panel = T.ReadoutPanel(self)
        panel.pack(fill="both", expand=True, padx=16, pady=10)
        self.text = tk.Text(panel, bg=T.PANEL, fg=T.READOUT, insertbackground=T.READOUT,
                            relief="flat", font=T.FONT_MONO, wrap="word", bd=0,
                            highlightthickness=0)
        self.text.pack(fill="both", expand=True, padx=8, pady=8)
        self.text.insert("1.0", self.prefs.guidelines)

        row = tk.Frame(self, bg=T.SPACE)
        row.pack(fill="x", padx=16, pady=(0, 14))
        T.LcarsButton(row, "Reset to default", self._reset,
                      color=T.LILAC).pack(side="left", padx=(0, 8))
        T.LcarsButton(row, "Save", self._save, color=T.ORANGE).pack(side="left")

    def _reset(self):
        self.text.delete("1.0", "end")
        self.text.insert("1.0", DEFAULT_GUIDELINES)

    def _save(self):
        self.prefs.guidelines = self.text.get("1.0", "end-1c")
        self.destroy()
