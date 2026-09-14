#!/usr/bin/env python3
"""
Translations: tr(), catalogs and user corrections, and the completeness of the French catalog: every
tr("literal") of the application has a French entry with the same {placeholders}.
"""

import ast
import glob
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import i18n


def tr_calls():
    """(file, line, text) of every tr("...") call with a literal text in the application modules."""
    found = []
    for path in sorted(glob.glob(os.path.join(ROOT, "*.py"))):
        if os.path.basename(path) in ("setup.py", "i18n.py"):
            continue
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and node.args:
                name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
                first = node.args[0]
                if name == "tr" and isinstance(first, ast.Constant) and isinstance(first.value, str):
                    found.append((os.path.basename(path), node.lineno, first.value))
    return found


class TestTr(unittest.TestCase):
    def setUp(self):
        self.old_env = os.environ.pop("DYNAMIX_LANGUAGE", None)
        self.user = tempfile.mkdtemp(prefix="dynamix_i18n_")

    def tearDown(self):
        if self.old_env is not None:
            os.environ["DYNAMIX_LANGUAGE"] = self.old_env
        i18n.set_language("en")
        shutil.rmtree(self.user, ignore_errors=True)

    def test_english_is_the_reference(self):
        i18n.set_language("en", user_dir=self.user)
        self.assertEqual(i18n.tr("Plan Transitions"), "Plan Transitions")
        self.assertEqual(i18n.tr("{done}/{total} tracks", done=3, total=8), "3/8 tracks")

    def test_resolve(self):
        self.assertEqual(i18n.resolve("fr"), "fr")
        self.assertEqual(i18n.resolve("klingon"), "en")
        self.assertIn(i18n.resolve("auto"), i18n.LANGUAGES)
        os.environ["DYNAMIX_LANGUAGE"] = "en"
        self.assertEqual(i18n.resolve("fr"), "en")

    def test_user_corrections_and_broken_translations(self):
        with open(os.path.join(self.user, "fr.json"), "w", encoding="utf-8") as f:
            json.dump({"Smoke {n} tracks": "{n} morceaux fumants", "Broken {n}": "Cassé {count}", "Empty": " "}, f)
        i18n.set_language("fr", user_dir=self.user)
        self.assertEqual(i18n.language(), "fr")
        self.assertEqual(i18n.tr("Smoke {n} tracks", n=2), "2 morceaux fumants")
        self.assertEqual(i18n.tr("Broken {n}", n=2), "Broken 2")          # a wrong placeholder falls back to English
        self.assertEqual(i18n.tr("Empty"), "Empty")                       # an empty translation is ignored
        self.assertEqual(i18n.tr("Not in any catalog"), "Not in any catalog")

    def test_fields(self):
        self.assertEqual(i18n.fields("{a} of {b:.1f} {c[0]}"), {"a", "b", "c"})
        self.assertEqual(i18n.fields("no field"), set())


class TestFrenchCatalog(unittest.TestCase):
    def test_catalog_files_are_valid_json(self):
        for path in glob.glob(os.path.join(i18n.package_dir(), "*", "*.json")):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self.assertIsInstance(data, dict, path)

    def test_every_text_is_translated_with_the_same_placeholders(self):
        catalog = i18n.shipped_catalog("fr")
        missing = [f"{file}:{line}: {text!r}" for file, line, text in tr_calls() if text not in catalog]
        self.assertEqual(missing, [], "texts without a French translation:\n" + "\n".join(missing[:40]))
        wrong = [f"{text!r} -> {catalog[text]!r}" for _, _, text in tr_calls()
                 if text in catalog and i18n.fields(text) != i18n.fields(catalog[text])]
        self.assertEqual(wrong, [], "translations whose {placeholders} differ:\n" + "\n".join(wrong[:40]))


if __name__ == "__main__":
    unittest.main()
