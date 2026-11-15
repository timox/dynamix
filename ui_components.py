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
        states = config.get("fold_states", {}) if config is not None else {}
        if key and isinstance(states, dict):
            self.expanded = bool(states.get(key, expanded))
        self.header = ttk.Button(self, text="", command=self.toggle)
        self.header.pack(fill=tk.X)
        self.body = ttk.Frame(self)
        self._update_header()
        if self.expanded:
            self.body.pack(fill=tk.BOTH, expand=True)

    def _update_header(self):
        self.header.configure(text=f"{'▼' if self.expanded else '▶'} {self.title}")

    def toggle(self):
        self.expanded = not self.expanded
        if self.expanded:
            self.body.pack(fill=tk.BOTH, expand=True)
        else:
            self.body.pack_forget()
        self._update_header()
        if self.config_store is not None and self.key:
            states = dict(self.config_store.get("fold_states", {}) or {})
            states[self.key] = self.expanded
            self.config_store.set("fold_states", states)
            self.config_store.save()
