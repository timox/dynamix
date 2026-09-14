#!/usr/bin/env python3
"""
Translations of the DynaMix interface.

English is the reference: the code writes tr("English text {value}", value=...)
and the catalog of a language maps each English text to its translation. The
catalog of French is made of the JSON files in locales/fr/ (one per part of the
application); a user can correct any entry, even in the shareable build, with
<DynaMix home>/locales/fr.json (or files in <DynaMix home>/locales/fr/), which
override the shipped ones. A missing translation shows the English text.

The language is chosen in the Configuration tab (auto = the Windows language)
and applied at the next start; DYNAMIX_LANGUAGE overrides it (tests use "en").
Never call tr() at import time: translate when the text is shown.
"""

import glob
import json
import locale
import os
import string
import sys
from typing import Dict, Optional, Set

LANGUAGES = {"en": "English", "fr": "Français"}
_catalog: Dict[str, str] = {}
_language = "en"


def system_language() -> str:
    """'fr' when the system locale is French, else 'en'."""
    names = [locale.getlocale()[0] or "", os.environ.get("LANG", ""), os.environ.get("LANGUAGE", "")]
    if sys.platform.startswith("win"):
        try:
            import ctypes
            names.append(locale.windows_locale.get(ctypes.windll.kernel32.GetUserDefaultUILanguage(), ""))
        except Exception:
            pass
    return "fr" if any(n.lower().startswith("fr") for n in names) else "en"


def resolve(setting: Optional[str]) -> str:
    """The language to use for a setting ('auto', 'en', 'fr'); DYNAMIX_LANGUAGE wins."""
    forced = (os.environ.get("DYNAMIX_LANGUAGE") or "").strip().lower()
    choice = forced or (setting or "auto").strip().lower()
    if choice == "auto":
        choice = system_language()
    return choice if choice in LANGUAGES else "en"


def package_dir() -> str:
    """Folder of the shipped catalogs (inside the build when DynaMix is frozen)."""
    return os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), "locales")


def _read(path: str) -> Dict[str, str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in data.items() if isinstance(v, str) and v.strip() and not str(k).startswith("_")}


def shipped_catalog(language: str) -> Dict[str, str]:
    catalog: Dict[str, str] = {}
    for path in sorted(glob.glob(os.path.join(package_dir(), language, "*.json"))):
        catalog.update(_read(path))
    return catalog


def load_catalog(language: str, user_dir: Optional[str] = None) -> Dict[str, str]:
    """Shipped catalog of a language, then the user's corrections."""
    if language == "en":
        return {}
    catalog = shipped_catalog(language)
    if user_dir is None:
        try:
            from analysis_store import dynamix_home
            user_dir = os.path.join(dynamix_home(), "locales")
        except Exception:
            user_dir = ""
    if user_dir:
        for path in sorted(glob.glob(os.path.join(user_dir, language, "*.json"))) + [os.path.join(user_dir, f"{language}.json")]:
            catalog.update(_read(path))
    return catalog


def set_language(setting: Optional[str], user_dir: Optional[str] = None) -> str:
    """Choose the interface language (at start-up); returns the language used."""
    global _catalog, _language
    _language = resolve(setting)
    _catalog = load_catalog(_language, user_dir)
    return _language


def language() -> str:
    return _language


def fields(text: str) -> Set[str]:
    """Names of the {placeholders} of a text."""
    try:
        return {name.split(".")[0].split("[")[0] for _, name, _, _ in string.Formatter().parse(text) if name}
    except ValueError:
        return set()


def tr(text: str, **values) -> str:
    """The text in the interface language, with its {placeholders} filled; English when not translated."""
    translated = _catalog.get(text, text)
    if not values:
        return translated
    try:
        return translated.format(**values)
    except (KeyError, IndexError, ValueError):  # a broken translation must never break the interface
        return text.format(**values)
