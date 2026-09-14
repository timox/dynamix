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
                if name in ("tr", "N_") and isinstance(first, ast.Constant) and isinstance(first.value, str):
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

    def test_stored_texts_are_translated_from_their_templates(self):
        with open(os.path.join(self.user, "fr.json"), "w", encoding="utf-8") as f:
            json.dump({"quieter than the rest of the set ({db:+.1f} dB)": "plus calme que le reste du set ({db:+.1f} dB)",
                       "persistent resonances: {list}": "résonances persistantes : {list}",
                       "{freq} Hz ~ {note} ({degree} of {key})": "{freq} Hz ~ {note} ({degree} de {key})",
                       "tonic": "tonique", "smooth": "fluide",
                       "{a} then {a}": "{a} puis encore {a}",
                       "{name}: {problem}": "{name} : {problem}",
                       "could not analyze: {error}": "analyse impossible : {error}"}, f)
        i18n.set_language("fr", user_dir=self.user)
        self.assertEqual(i18n.N_("quieter than the rest of the set ({db:+.1f} dB)").format(db=-3.04),
                         "quieter than the rest of the set (-3.0 dB)")                  # stored data stays English
        self.assertEqual(i18n.tr_text("quieter than the rest of the set (-3.0 dB)"), "plus calme que le reste du set (-3.0 dB)")
        self.assertEqual(i18n.tr_text("smooth"), "fluide")
        self.assertEqual(i18n.tr_text("persistent resonances: 110 Hz ~ A2 (tonic of A minor)"),
                         "résonances persistantes : 110 Hz ~ A2 (tonique de A minor)")   # nested stored text
        self.assertEqual(i18n.tr_text("x then x"), "x puis encore x")
        self.assertEqual(i18n.tr_text("x then y"), "x then y")                          # repeated field must match
        self.assertEqual(i18n.tr_text("something new (-3.0 dB)"), "something new (-3.0 dB)")
        # a template made only of fields and punctuation never recognises a text (nor its values)
        self.assertEqual(i18n.tr_text("could not analyze: Error opening 'x.wav': System error"),
                         "analyse impossible : Error opening 'x.wav': System error")
        self.assertEqual(i18n.tr_text("a.wav: cannot be read"), "a.wav: cannot be read")
        self.assertEqual(i18n.tr("{name}: {problem}", name="a.wav", problem="x"), "a.wav : x")
        i18n.set_language("en", user_dir=self.user)
        self.assertEqual(i18n.tr_text("quieter than the rest of the set (-3.0 dB)"), "quieter than the rest of the set (-3.0 dB)")

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
