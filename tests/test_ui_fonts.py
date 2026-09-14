#!/usr/bin/env python3
"""Font size of the GUI: Tk fonts, DynaMix fonts, table rows and chart scale."""

import os
import sys
import tkinter as tk
import unittest
from tkinter import font as tkfont
from tkinter import ttk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import matplotlib
matplotlib.use("Agg")

import charts
import ui_fonts


class TestFontSize(unittest.TestCase):
    def test_clamp_and_chart_scale(self):
        self.assertEqual(ui_fonts.clamp("12"), 12)
        self.assertEqual(ui_fonts.clamp(3), ui_fonts.MIN_SIZE)
        self.assertEqual(ui_fonts.clamp(40), ui_fonts.MAX_SIZE)
        self.assertEqual(ui_fonts.clamp("big"), ui_fonts.DEFAULT_SIZE)
        self.assertEqual(ui_fonts.clamp(None), ui_fonts.DEFAULT_SIZE)
        self.assertAlmostEqual(ui_fonts.chart_scale(18), 2.0)
        self.assertEqual(ui_fonts.row_height(15), 23)

    def test_chart_scale_sets_the_figure_resolution(self):
        try:
            charts.set_scale(1.5)
            self.assertAlmostEqual(charts._figure(9.0, 4.0).dpi, 150.0)
        finally:
            charts.set_scale(1.0)
        self.assertAlmostEqual(charts._figure(9.0, 4.0).dpi, 100.0)


class TestApplyFonts(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as e:
            self.skipTest(f"no display: {e}")
        self.root.withdraw()

    def tearDown(self):
        self.root.destroy()

    def rows(self):
        return int(ttk.Style(self.root).lookup("Treeview", "rowheight"))

    def test_apply_sets_every_font_and_the_row_height(self):
        self.assertEqual(ui_fonts.apply(self.root, 14), 14)
        for name in ("TkDefaultFont", "TkHeadingFont", "TkFixedFont", ui_fonts.MONO, ui_fonts.BOLD):
            self.assertEqual(tkfont.nametofont(name, root=self.root).cget("size"), 14, name)
        self.assertEqual(tkfont.nametofont(ui_fonts.TITLE, root=self.root).cget("size"), 15)
        self.assertEqual(tkfont.nametofont(ui_fonts.BOLD, root=self.root).cget("weight"), "bold")
        linespace = tkfont.nametofont("TkDefaultFont", root=self.root).metrics("linespace")
        self.assertEqual(self.rows(), ui_fonts.row_height(linespace))
        big_rows = self.rows()
        self.assertEqual(ui_fonts.apply(self.root, 99), ui_fonts.MAX_SIZE)
        ui_fonts.apply(self.root, 8)
        self.assertLess(self.rows(), big_rows)
        label = ttk.Label(self.root, text="x", font=ui_fonts.MONO)   # the named fonts are usable by widgets
        self.assertEqual(str(label.cget("font")), ui_fonts.MONO)


if __name__ == "__main__":
    unittest.main()
