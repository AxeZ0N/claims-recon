"""Filename normalization: fold many ways, parse months."""

import os
import re
import sys
import time

COPYWS = re.compile(r"^copy\s+of\s+", re.IGNORECASE)
PAREN = re.compile(r"\(([^()]*)\)")

# Strict single-space literal on purpose: only canonical
# "Copy of " prunes. Loose spacing ("Copy  of Mar 26")
# must miss here and land as near-dupe in flag_dupes;
# checks.py pins that golden. Folding above stays loose.
COPY_PRUNE = re.compile(r"copy of ", re.IGNORECASE)


def slash(path):
    # Forward slashes paste clean: Explorer, shells, JSON.
    return path.replace(os.sep, "/")


def read_lines(path):
    # Titles and listings alike: stripped, blanks dropped.
    with open(path) as handle:
        return [
            line.strip() for line in handle
            if line.strip()
        ]


def heartbeat(done, total, path):
    # First proves liveness, then every 50th; elapsed
    # doubles as a rate meter. Single home for progress.
    if done != 1 and done % 50 != 0:
        return
    now = time.monotonic()
    if heartbeat.start is None:
        heartbeat.start = now
    elapsed = now - heartbeat.start
    if total is None:
        print(
            f"[{done}, {elapsed:.0f}s] {path}",
            file=sys.stderr, flush=True,
        )
    else:
        print(
            f"[{done}/{total}, {elapsed:.0f}s] {path}",
            file=sys.stderr, flush=True,
        )


heartbeat.start = None


def reset_heartbeat():
    # Stages share one process in auto: restart the clock
    # so elapsed reads per stage, never cumulative.
    heartbeat.start = None


def stdio():
    # Undecodable filenames must never kill a run:
    # escape them, keep every byte ASCII-safe.
    sys.stdout.reconfigure(errors="backslashreplace")
    sys.stderr.reconfigure(errors="backslashreplace")


def normalize(text):
    cleaned = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return " ".join(cleaned.split())


def fold_ws(base):
    no_copy = COPYWS.sub("", base, count=1)
    return re.sub(r"\s+", "", no_copy).lower()


def fold_alnum(base):
    return re.sub(r"[^a-z0-9]", "", fold_ws(base))


def deparen(base):
    # Only human annotations fold; digit markers stay.
    return PAREN.sub(
        lambda hit: ""
        if re.fullmatch(r"[A-Za-z ]+", hit.group(1))
        else hit.group(0),
        base,
    )


NAMES = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}

# Alternation backtracks, so short forms need no ordering.
MONTH = re.compile(
    "(?<![a-z])(" + "|".join(NAMES) + ")(?![a-z])",
    re.IGNORECASE,
)
ISO = re.compile(r"(?<!\d)2026[- /.](\d{1,2})(?!\d)")
MDY4 = re.compile(r"(?<!\d)(\d{1,2})[- /.](\d{1,2})[- /.]2026(?!\d)")
REV = re.compile(r"(?<!\d)(\d{1,2})[- /.]2026(?!\d)")

MDY8 = re.compile(r"(?<!\d)(\d{2})(\d{2})2026(?!\d)")
YMD8 = re.compile(r"(?<!\d)2026(\d{2})(\d{2})(?!\d)")

US = re.compile(r"(?<!\d)(\d{1,2})[- /.](\d{1,2})[- /.]26(?!\d)")
YEAR4 = re.compile(r"(?<!\d)(1\d{3}|2\d{3})(?!\d)")

# Day-in-the-middle first: REV would grab the day as
# month. Month-first after (US order, day ignored).
# Packed forms last. Every group(1) is the month.
DATES = (MDY4, ISO, REV, US, MDY8, YMD8)


def by_month(num):
    num = int(num)
    if 1 <= num <= 12:
        return f"2026-{num:02d}"
    return None


def resolve_month(name):
    found = MONTH.search(name)
    if found:
        year = YEAR4.search(name)
        if year and year.group(1) != "2026":
            return None, f"year {year.group(1)}"
        num = NAMES[found.group(1).lower()]
        return f"2026-{num:02d}", None

    for pattern in DATES:
        hit = pattern.search(name)
        if hit:
            key = by_month(hit.group(1))
            if key:
                return key, None

    return None, "no month in filename"
