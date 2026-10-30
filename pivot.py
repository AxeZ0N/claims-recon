"""Paste-over tables for the hand-filled template."""

import calendar
import os

MONTH_NAMES = [calendar.month_abbr[m] for m in range(1, 11)]
MONTH_KEYS = [f"2026-{m:02d}" for m in range(1, 11)]


def render(head, show_head, ordered, labels, table):
    # Shared paste-over renderer: label columns + Missing +
    # Jan..Oct + Totals. Row order is the caller's business.
    lines = ["\t".join(head)] if show_head else []
    for rid in ordered:
        got = table.get(rid, {})
        cells = [got.get(key, 0) for key in MONTH_KEYS]
        missing = sum(1 for cell in cells if cell == 0)
        line = list(labels[rid]) + [str(missing)]
        line += [str(cell) for cell in cells]
        line.append(str(sum(cells)))
        lines.append("\t".join(line))
    return "\n".join(lines)


def title_order(data, order):
    present = {row["title"] for row in data["data"]}
    if order is None:
        return sorted(present)
    return list(dict.fromkeys(order)) + sorted(
        t for t in present if t not in order
    )


def format_pivot(data, order=None):
    # Paste-over matrix: Title, Missing, Jan..Oct, Totals.
    # Rows follow order; unknown append, missing zero-fill.
    table = {}
    for row in data["data"]:
        got = table.setdefault(row["title"], {})
        got[row["month"]] = row["rows"]

    if order is not None:
        for missing in order:
            table.setdefault(missing, {})

    head = ["Title", "Missing"] + MONTH_NAMES + ["Totals"]
    titles = title_order(data, order)
    # Ordered output pastes under existing headers.
    return render(
        head, order is None, titles,
        {title: [title] for title in titles}, table,
    )


def format_sheet_pivot(data, order=None):
    # One row per file sheet: Title, File, Sheet, Missing,
    # Jan..Oct, Totals. Months inherit the file's bucket;
    # sheet rows always sum back to the file-mode cells.
    table = {}
    labels = {}
    files = {}
    for row in data["data"]:
        for entry in row.get("sheets", []):
            base = os.path.basename(entry["source"])
            sheet = entry["sheet"] or base
            rid = (row["title"], entry["source"], sheet)
            table.setdefault(rid, {})[row["month"]] = entry[
                "rows"
            ]
            labels[rid] = [row["title"], base, sheet]
            files.setdefault(row["title"], []).append(rid)

    titles = title_order(data, order)
    ordered = []
    for title in titles:
        # Files sorted; sheets keep workbook order (first
        # seen per file, stable across months).
        seen = list(dict.fromkeys(files.get(title, [])))
        ordered.extend(sorted(seen, key=lambda rid: rid[1]))

    head = ["Title", "File", "Sheet", "Missing"]
    head += MONTH_NAMES + ["Totals"]
    return render(head, True, ordered, labels, table)
