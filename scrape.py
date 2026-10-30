"""Selection predicates shared by the live tools.

keep decides file membership; format_scrape renders
the human stream. The walking itself lives in walk.py,
claim validation in sieve.py. Copy-prune matching lives
in normalization (COPY_PRUNE).
"""

import re
SUFFIXES = (".xlsx", ".xlsm", ".xls", ".pdf")
# Gate admits what resolve_month accepts: standalone
# 2026/26 plus packed 8-digit dates. Shorter runs
# (120268) and embedded runs stay out.
YEAR = re.compile(
    r"(?<!\d)2026(?!\d)|(?<!\d)26(?!\d)"
    r"|(?<!\d)\d{4}2026(?!\d)|(?<!\d)2026\d{4}(?!\d)"
)


def keep(name, rel):
    # Lock files, non-data, and non-2026 never enter.
    if name.startswith("~$"):
        return False
    if not name.lower().endswith(SUFFIXES):
        return False
    return bool(YEAR.search(rel))


def format_scrape(sheets):
    lines = []
    for title, groups in sheets.items():
        lines.append(f"{title}:")
        for root, paths in groups.items():
            lines.append(f"  {root}: {len(paths)} files")
            for path in paths:
                lines.append(f"    {path}")
    return "\n".join(lines)


def gate_cause(name):
    # Explains keep(): lock, suffix, then year. One home
    # for both, so they cannot drift apart; audit never
    # recruits, only explains.
    if name.startswith("~$"):
        return "lock file"
    if not name.lower().endswith(SUFFIXES):
        return "non-data suffix"
    return "no 2026 token"
