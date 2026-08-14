"""Port of `UI/Theme.swift` — the LCARS (Star Trek) palette and widget set, in Tk.

Colour values are byte-for-byte the Mac app's, which are in turn the Android app's `Lcars.kt`.
"""

import tkinter as tk
from tkinter import ttk

SPACE = "#05070D"
PANEL = "#0E121E"
ORANGE = "#FF9966"
BLUE = "#7FB0FF"
LILAC = "#CC88CC"
GOLD = "#FFCC66"
RED = "#E0533D"
READOUT = "#9AE6C9"     # mono panel text

FONT_UI = ("Segoe UI", 10)
FONT_UI_BOLD = ("Segoe UI Semibold", 10)
FONT_MONO = ("Consolas", 9)
FONT_MONO_BIG = ("Consolas", 14)
FONT_TITLE = ("Segoe UI Black", 17)
FONT_HUGE = ("Segoe UI Black", 44)


def style_root(widget) -> None:
    widget.configure(bg=SPACE)


class LcarsButton(tk.Button):
    """LCARS "pill" button — flat, condensed-bold, coloured."""

    def __init__(self, master, text, command=None, color=ORANGE, width=None, **kw):
        super().__init__(
            master, text=text.upper(), command=command,
            bg=color, fg=SPACE, activebackground=color, activeforeground=SPACE,
            font=("Segoe UI Black", 10), relief="flat", bd=0, cursor="hand2",
            padx=14, pady=7, highlightthickness=0, **kw)
        if width:
            self.configure(width=width)


class ReadoutPanel(tk.Frame):
    """Dark monospace readout panel (the LCARS status/log look)."""

    def __init__(self, master, **kw):
        super().__init__(master, bg=PANEL, highlightbackground=BLUE,
                         highlightthickness=1, bd=0, **kw)


class LcarsHeader(tk.Frame):
    """The LCARS "elbow" header sweep."""

    def __init__(self, master, title, subtitle):
        super().__init__(master, bg=SPACE)
        tk.Frame(self, bg=ORANGE, width=60, height=24).pack(side="left", padx=(0, 10))
        box = tk.Frame(self, bg=SPACE)
        box.pack(side="left", anchor="w")
        tk.Label(box, text=title.upper(), bg=SPACE, fg=GOLD,
                 font=FONT_TITLE).pack(anchor="w")
        tk.Label(box, text=subtitle.upper(), bg=SPACE, fg=LILAC,
                 font=("Segoe UI Semibold", 8)).pack(anchor="w")
        tk.Frame(self, bg=BLUE, width=120, height=12).pack(side="right", pady=6)


def entry(master, show=None, width=30):
    e = tk.Entry(master, bg=PANEL, fg=READOUT, insertbackground=READOUT,
                 relief="flat", font=FONT_MONO, width=width,
                 highlightthickness=1, highlightbackground=BLUE, highlightcolor=ORANGE)
    if show:
        e.configure(show=show)
    return e


def label(master, text, fg=READOUT, font=FONT_UI, **kw):
    return tk.Label(master, text=text, bg=kw.pop("bg", SPACE), fg=fg, font=font,
                    justify="left", anchor="w", **kw)


def caption(master, text, fg=None, bg=SPACE, wraplength=480):
    return tk.Label(master, text=text, bg=bg, fg=fg or LILAC, font=("Segoe UI", 8),
                    justify="left", anchor="w", wraplength=wraplength)


def checkbox(master, text, variable, command=None, bg=PANEL, fg=READOUT):
    return tk.Checkbutton(
        master, text=text, variable=variable, command=command,
        bg=bg, fg=fg, selectcolor=SPACE, activebackground=bg, activeforeground=fg,
        font=FONT_UI, anchor="w", highlightthickness=0, bd=0)


def apply_ttk_dark(root) -> None:
    """Make the few ttk widgets we use (scrollbars) match the palette."""
    st = ttk.Style(root)
    try:
        st.theme_use("clam")
    except tk.TclError:
        pass
    st.configure("Guardian.Vertical.TScrollbar", background=PANEL, troughcolor=SPACE,
                 bordercolor=SPACE, arrowcolor=BLUE, darkcolor=PANEL, lightcolor=PANEL)
