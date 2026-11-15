"""Small reusable Tk widgets for user-controlled panel folding."""

import tkinter as tk
from tkinter import ttk


class FoldableSection(ttk.Frame):
    """A section with a persistent, keyboard-accessible expand/collapse button."""

    def __init__(self, parent, title, config=None, key=None, expanded=True, **kwargs):
        super().__init__(parent, **kwargs)
        self.title = title
        self.config_store = config
        self.key = key
        self.expanded = expanded
        self._expanded_pane_size = None
        self._needs_initial_pane_fit = False
        states = config.get("fold_states", {}) if config is not None else {}
        if key and isinstance(states, dict):
            self.expanded = bool(states.get(key, expanded))
        self.header = ttk.Button(self, text="", command=self.toggle)
        self.header.pack(fill=tk.X)
        self.body = ttk.Frame(self)
        self._update_header()
        if self.expanded:
            self.body.pack(fill=tk.BOTH, expand=True)
        elif hasattr(self.master, "panes") and hasattr(self.master, "sashpos"):
            self._needs_initial_pane_fit = True
            self.bind("<Map>", self._fit_initial_pane, add="+")

    def _update_header(self):
        self.header.configure(text=f"{'▼' if self.expanded else '▶'} {self.title}")

    def toggle(self):
        if self.expanded:
            self._expanded_pane_size = self._pane_size()
        self.expanded = not self.expanded
        if self.expanded:
            self.body.pack(fill=tk.BOTH, expand=True)
        else:
            self.body.pack_forget()
        self._update_header()
        if hasattr(self.master, "panes") and hasattr(self.master, "sashpos"):
            self.after_idle(self._fit_pane)
        if self.config_store is not None and self.key:
            states = dict(self.config_store.get("fold_states", {}) or {})
            states[self.key] = self.expanded
            self.config_store.set("fold_states", states)
            self.config_store.save()

    def _pane_size(self):
        orient = self.master.cget("orient")
        return self.winfo_height() if orient == tk.VERTICAL else self.winfo_width()

    def _fit_initial_pane(self, _event=None):
        if self._needs_initial_pane_fit:
            self._needs_initial_pane_fit = False
            self.after_idle(self._fit_pane)

    def _fit_pane(self):
        pane = self.master
        try:
            panes = pane.panes()
            index = panes.index(str(self))
            if len(panes) < 2:
                return
            orient = pane.cget("orient")
            total = pane.winfo_height() if orient == tk.VERTICAL else pane.winfo_width()
            if total < 2:
                return
            desired = self._pane_size() if self.expanded else (
                self.header.winfo_reqheight() if orient == tk.VERTICAL else self.header.winfo_reqwidth())
            if self.expanded and self._expanded_pane_size:
                desired = self._expanded_pane_size
            sash_width = 4  # shortcut: ttk exposes no sash thickness, revisit if the pane API changes
            if index < len(panes) - 1:
                start = 0 if index == 0 else pane.sashpos(index - 1) + sash_width
                sash, position = index, start + desired
            else:
                sash, position = index - 1, total - desired - sash_width
            pane.sashpos(sash, max(1, min(total - sash_width - 1, position)))
        except (tk.TclError, ValueError, TypeError):
            return
