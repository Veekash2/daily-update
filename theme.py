"""Dark cyberpunk theme for the ttk/tk widgets used in app.py."""
import tkinter as tk
from tkinter import ttk

BG = "#0a0e14"
PANEL = "#0f1720"
FG = "#e6faff"
ACCENT = "#00ffe1"
ACCENT2 = "#ff00c8"
MUTED = "#7a8a99"
BORDER = "#1f3b3f"
PROGRESS_TROUGH = "#f2f7fa"
PROGRESS_BAR = "#2f81f7"
FONT = ("Consolas", 10)
FONT_BOLD = ("Consolas", 10, "bold")


def apply(root):
    root.configure(bg=BG)

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure(".", background=BG, foreground=FG, font=FONT, fieldbackground=PANEL)
    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=BG, foreground=ACCENT, font=FONT)
    style.configure("TCheckbutton", background=BG, foreground=FG, font=FONT)
    style.map("TCheckbutton", background=[("active", BG)], foreground=[("active", ACCENT)])

    style.configure(
        "TButton",
        background=PANEL,
        foreground=ACCENT,
        bordercolor=ACCENT,
        borderwidth=1,
        focusthickness=1,
        focuscolor=ACCENT2,
        font=FONT_BOLD,
        padding=6,
    )
    style.map(
        "TButton",
        background=[("active", ACCENT), ("pressed", ACCENT2)],
        foreground=[("active", BG), ("pressed", BG)],
    )

    style.configure(
        "TNotebook",
        background=BG,
        bordercolor=BORDER,
        tabmargins=(2, 4, 2, 0),
    )
    style.configure(
        "TNotebook.Tab",
        background=PANEL,
        foreground=MUTED,
        padding=(12, 6),
        font=FONT_BOLD,
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", "#152530")],
        foreground=[("selected", ACCENT)],
        expand=[("selected", (1, 1, 1, 0))],
    )

    style.configure("TEntry", fieldbackground=PANEL, foreground=FG, insertcolor=ACCENT, bordercolor=BORDER)

    # lightcolor and darkcolor as well as background: clam draws a bevel from those two, so
    # setting background alone leaves a grey 3D edge down the length of the bar.
    style.configure(
        "Neon.Horizontal.TProgressbar",
        troughcolor=PROGRESS_TROUGH,
        background=PROGRESS_BAR,
        lightcolor=PROGRESS_BAR,
        darkcolor=PROGRESS_BAR,
        bordercolor=BORDER,
        borderwidth=1,
        thickness=18,
    )


def style_entry(widget):
    widget.configure(
        bg=PANEL, fg=FG, insertbackground=ACCENT, relief="flat",
        highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT, font=FONT,
    )


def style_text(widget):
    widget.configure(
        bg="#060a0f", fg=ACCENT, insertbackground=ACCENT, relief="flat",
        highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT2,
        font=FONT, wrap="word", padx=8, pady=8,
    )
