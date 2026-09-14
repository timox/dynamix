#!/usr/bin/env python3
"""
Reports of a set project (mastering, band analysis, transition sheet, ...):
text files named '<YYYY-MM-DD HH-MM-SS> <title>.txt' in the project's
exports/reports folder, listed in the Log tab.
"""

import datetime
import os
import re
from typing import Dict, List, Optional

_STAMP = "%Y-%m-%d %H-%M-%S"
_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d{2})-(\d{2})-(\d{2}) (.+)\.txt$")


def write_report(folder: str, title: str, text: str, now: Optional[datetime.datetime] = None) -> str:
    """Write a report and return its path (' (2)', ' (3)' ... when the name is taken)."""
    os.makedirs(folder, exist_ok=True)
    safe_title = re.sub(r'[<>:"/\\|?*]', "-", title).strip() or "Report"
    base = f"{(now or datetime.datetime.now()).strftime(_STAMP)} {safe_title}"
    path, n = os.path.join(folder, base + ".txt"), 1
    while os.path.exists(path):
        n += 1
        path = os.path.join(folder, f"{base} ({n}).txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def list_reports(folder: str) -> List[Dict[str, str]]:
    """The reports of a folder, oldest first: {'title', 'time' ('YYYY-MM-DD HH:MM:SS'), 'path'}."""
    if not folder or not os.path.isdir(folder):
        return []
    found = []
    for name in os.listdir(folder):
        match = _NAME.match(name)
        if match:
            day, hh, mm, ss, title = match.groups()
            found.append({"title": title, "time": f"{day} {hh}:{mm}:{ss}", "path": os.path.join(folder, name)})
    return sorted(found, key=lambda r: (r["time"], os.path.getmtime(r["path"]), r["title"]))


def read_report(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()
