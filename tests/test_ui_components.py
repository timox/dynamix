import tkinter as tk
import unittest
from tkinter import ttk

from ui_components import FoldableSection


class TestFoldableSection(unittest.TestCase):
    def test_initially_collapsed_pane_uses_only_its_header(self):
        root = tk.Tk()
        root.geometry("500x500+0+0")
        try:
            panes = ttk.PanedWindow(root, orient=tk.VERTICAL)
            panes.pack(fill=tk.BOTH, expand=True)
            collapsed = FoldableSection(panes, "Proposals", expanded=False)
            expanded = FoldableSection(panes, "Comparison")
            ttk.Label(expanded.body, text="Content").pack(pady=100)
            panes.add(collapsed, weight=1)
            panes.add(expanded, weight=1)
            root.update()
            self.assertLess(collapsed.winfo_height(), 80)
            self.assertGreater(expanded.winfo_height(), 350)
        finally:
            root.destroy()

    def test_collapsing_a_paned_section_releases_and_restores_space(self):
        root = tk.Tk()
        root.geometry("500x500+0+0")
        try:
            panes = ttk.PanedWindow(root, orient=tk.VERTICAL)
            panes.pack(fill=tk.BOTH, expand=True)
            sections = [FoldableSection(panes, title) for title in ("Proposals", "Comparison")]
            for section in sections:
                ttk.Label(section.body, text="Content").pack(pady=100)
                panes.add(section, weight=1)
            root.update()
            first_height, second_height = (section.winfo_height() for section in sections)
            self.assertGreater(first_height, 150)
            self.assertGreater(second_height, 150)

            sections[0].toggle()
            root.update()
            self.assertLess(sections[0].winfo_height(), first_height / 2)
            self.assertGreater(sections[1].winfo_height(), second_height + 100)

            sections[0].toggle()
            root.update()
            self.assertGreater(sections[0].winfo_height(), first_height / 2)

            sections[1].toggle()
            root.update()
            self.assertLess(sections[1].winfo_height(), second_height / 2)
            self.assertGreater(sections[0].winfo_height(), first_height / 2)
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
