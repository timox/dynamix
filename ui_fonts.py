#!/usr/bin/env python3
"""
Font size of the DynaMix GUI (Configuration tab): one size applied to Tk's named
fonts, to DynaMix's own fonts (monospace text, bold labels, titles), to the row
height of the tables and, through charts.set_scale, to the charts.
"""

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

MIN_SIZE, MAX_SIZE, DEFAULT_SIZE = 8, 18, 9
MONO, BOLD, TITLE = "DynaMixMono", "DynaMixBold", "DynaMixTitle"
_TK_FONTS = ("TkDefaultFont", "TkTextFont", "TkHeadingFont", "TkMenuFont", "TkCaptionFont",
             "TkSmallCaptionFont", "TkIconFont", "TkTooltipFont", "TkFixedFont")
_KEEP = {}  # named fonts created here: a tkinter Font deletes its Tk font when garbage-collected


def clamp(size) -> int:
    """A usable font size (DEFAULT_SIZE when the value is not a number)."""
    try:
        return max(MIN_SIZE, min(MAX_SIZE, int(round(float(size)))))
    except (TypeError, ValueError):
        return DEFAULT_SIZE


def chart_scale(size) -> float:
    """How much bigger the charts' text must be drawn for this font size."""
    return clamp(size) / float(DEFAULT_SIZE)


def row_height(linespace: int) -> int:
    """Table row height (pixels) for a font line height."""
    return int(linespace) + 8


def _named(root, name: str, **options) -> None:
    if name in tkfont.names(root):
        tkfont.nametofont(name, root=root).configure(**options)
    else:
        _KEEP[name] = tkfont.Font(root=root, name=name, exists=False, **options)


def apply(root, size) -> int:
    """Set every GUI font to `size` points and the table rows to fit; returns the size used."""
    size = clamp(size)
    for name in _TK_FONTS:
        try:
            tkfont.nametofont(name, root=root).configure(size=size)
        except tk.TclError:
            pass
    default = tkfont.nametofont("TkDefaultFont", root=root)
    family = default.actual("family")
    mono = "Consolas" if "Consolas" in tkfont.families(root) else tkfont.nametofont("TkFixedFont", root=root).actual("family")
    _named(root, MONO, family=mono, size=size)
    _named(root, BOLD, family=family, size=size, weight="bold")
    _named(root, TITLE, family=family, size=size + 1, weight="bold")
    ttk.Style(root).configure("Treeview", rowheight=row_height(default.metrics("linespace")))
    return size
