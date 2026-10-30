"""Bucket files by month, count data rows."""

import json
import os
import re
import sys

from python_calamine import CalamineWorkbook

from normalization import deparen, fold_alnum, fold_ws, resolve_month

LOGIC = 2
# Bump when count_file semantics change; old cache
# records miss on version and recompute.
# 2: --sheets filters rows post-load.

# Single digit block with whitespace-or-edge either side;
# optional -digits suffix (claim-sequence style IDs).
ANCHOR = re.compile(r"(?<!\S)\d{9}(?:-\d+)?(?!\S)")


# ---- Readers: bytes in, (count, flag, sheets) out ----
# Raises on unreadable; empties report themselves as flags.


def has_value(value):
    return value is not None and (
        not isinstance(value, str) or value.strip()
    )


def count_pdf(path):
    # Lazy so Excel-only runs never need the dep.
    from pypdf import PdfReader
    reader = PdfReader(path)
    text = "\n".join(
        (page.extract_text() or "") for page in reader.pages
    )
    return len(ANCHOR.findall(text))


def count_file(path):
    # Month already resolved by the caller, so dateless
    # never pays for an open. Returns count, flag,
    # per-sheet rows; raises on unreadable.
    if path.lower().endswith(".pdf"):
        total = count_pdf(path)
        if total == 0:
            return 0, "empty pdf", []
        return total, None, [{"sheet": None, "rows": total}]

    book = CalamineWorkbook.from_path(path)
    counts = []
    for name in book.sheet_names:
        sheet = book.get_sheet_by_name(name)
        nrows = sum(
            1 for row in sheet.iter_rows()
            if any(has_value(value) for value in row)
        )
        if nrows:
            # Header is first; rest hold data.
            counts.append({"sheet": name, "rows": nrows - 1})

    if not counts:
        return 0, "empty workbook", []
    if len(counts) == 1:
        return counts[0]["rows"], None, counts
    return (
        sum(entry["rows"] for entry in counts),
        f"{len(counts)} sheets",
        counts,
    )


# ---- Dupe flags: same names go manual, both still count ----
# First sorted path is canonical; sharpest match wins.


def flag_dupes(paths, errors):
    # Same or similar names go manual; both still count.
    # First sorted path is canonical; sharpest match wins.
    exact = {}
    near = {}
    similar = {}
    for path in sorted(paths):
        base = os.path.basename(path)
        low = base.lower()
        ws = fold_ws(base)
        al = fold_alnum(deparen(base))

        if low in exact:
            errors[path] = f"same name as {exact[low]}"
        elif ws in near:
            errors[path] = f"near-dupe of {near[ws]}"
        elif al in similar:
            other = os.path.basename(similar[al])
            if deparen(base) != base or deparen(other) != other:
                errors[path] = f"paren variant of {similar[al]}"
            else:
                errors[path] = f"possible dupe of {similar[al]}"
        else:
            exact[low] = path
            near[ws] = path
            similar[al] = path


# ---- Cache: warm runs skip opens, never stats ----
# JSONL log, later lines win, corrupt tails discarded.
# Stays inline: version, payload, and skip policy are
# count business (decision logged in TODO Landed).


def read_cache(path):
    # Corrupt lines never parse: skipped, never fatal.
    # Later lines win, so recomputes supersede.
    found = {}
    try:
        handle = open(path)
    except OSError:
        return found
    with handle:
        for line in handle:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict) and "title" in entry:
                if "path" in entry:
                    found[(entry["title"], entry["path"])] = entry
    return found


def stamp_of(path, use):
    if not use:
        return None
    try:
        info = os.stat(path)
    except OSError:
        return None
    return (int(info.st_mtime), info.st_size)


def cached_hit(cached, title, path, stamp):
    # Hit skips the open; missing, moved, or logic-bumped
    # recomputes from scratch. Pure: caller counts reuse.
    if stamp is None:
        return None
    entry = cached.get((title, path))
    if entry is None or entry.get("v") != LOGIC:
        return None
    if (entry.get("mtime"), entry.get("size")) != stamp:
        return None
    return (
        entry["month"], entry["rows"], entry["flag"],
        entry["sheets"], entry["error"],
    )


def open_log(cache):
    if not cache:
        return None
    try:
        return open(cache, "a")
    except OSError as exc:
        print(f"cannot write {cache}: {exc}", file=sys.stderr)
        return None


def log(handle, title, path, stamp, month, count, flag,
        file_sheets, error):
    # Append plus flush per file: completed work survives
    # a kill. Dateless files cost no open, so there is
    # nothing worth saving.
    if handle is None or stamp is None:
        return
    if month is None and error is None:
        return
    handle.write(json.dumps({
        "title": title, "path": path, "month": month,
        "rows": count, "flag": flag, "sheets": file_sheets,
        "error": error, "mtime": stamp[0],
        "size": stamp[1], "v": LOGIC,
    }) + "\n")
    handle.flush()


# ---- Orchestration: flat loop, gate, load, accumulate ----
# One bucket per title-month; dupe pass needs the full
# per-title set, so it runs after, never during.


def apply_filter(path, got, listed, errors):
    # Filtered titles sum listed sheets only. Multi-sheet
    # flags recompute on the kept subset; absent names
    # merge loud into errors, never silent. Returns the
    # kept (count, rows), or None when nothing kept.
    kept = [entry for entry in got if entry["sheet"] in listed]
    present = {entry["sheet"] for entry in got}
    missing = [name for name in listed if name not in present]
    reasons = []
    if len(kept) > 1:
        reasons.append(f"{len(kept)} sheets")
    if len(missing) == 1:
        reasons.append(f"missing sheet {missing[0]}")
    elif missing:
        reasons.append("missing sheets " + ", ".join(missing))
    # Replaces any file flag: merged on the kept subset.
    if reasons:
        errors[path] = "; ".join(reasons)
    if not kept:
        return None
    return sum(entry["rows"] for entry in kept), kept


def add(data, title, month, count, path, got):
    # One bucket per title-month; sheet rows carry their
    # source so the sheet pivot need not rejoin. Zero-row
    # buckets stay: empties list at 0 rows, never vanish.
    current = data.get((title, month))
    tagged = [dict(entry, source=path) for entry in got]
    if current is None:
        data[(title, month)] = {
            "title": title,
            "month": month,
            "rows": count,
            "sources": [path],
            "sheets": tagged,
        }
    else:
        current["rows"] += count
        current["sources"].append(path)
        current["sheets"].extend(tagged)


def load(title, path, stamp, month, cached, handle, stats,
        errors):
    # Cached hit skips the open; miss reads and logs.
    # Errors record themselves; None means continue.
    # Fresh month wins: a rename keeps the stamp but not
    # the bucket. Counts and sheets ride the cache.
    hit = cached_hit(cached, title, path, stamp)
    if hit is not None:
        stats["reused"] += 1
        _, count, flag, got, error = hit
        if error is not None:
            errors[path] = error
            return None
        return month, count, flag, got
    try:
        count, flag, got = count_file(path)
    except Exception as exc:
        # One bad file never kills run.
        errors[path] = str(exc)
        log(
            handle, title, path, stamp,
            None, 0, None, [], str(exc),
        )
        stats["opened"] += 1
        return None
    log(
        handle, title, path, stamp,
        month, count, flag, got, None,
    )
    stats["opened"] += 1
    return month, count, flag, got


def count_rows(sheets, progress=None, cache=None, wanted=None):
    data = {}
    errors = {}
    stats = {"opened": 0, "reused": 0}
    cached = read_cache(cache) if cache else {}
    handle = open_log(cache)
    flat = [
        (title, path)
        for title, groups in sheets.items()
        for paths in groups.values()
        for path in paths
    ]
    done = 0
    try:
        titles = {}
        for title, path in flat:
            # Heartbeat proves liveness on slow drives.
            done += 1
            if progress:
                progress(done, len(flat), path)

            # Strings first: dateless skips stat and open.
            month, reason = resolve_month(
                os.path.basename(path)
            )
            if month is None:
                errors[path] = reason or "no month"
                continue

            # Hit skips the open; miss reads and logs.
            stamp = stamp_of(path, cache)
            found = load(
                title, path, stamp, month, cached,
                handle, stats, errors,
            )
            if found is None:
                continue
            month, count, flag, got = found

            # Sheet filter sums listed sheets only; absent
            # titles ride the exact old path. Missing names
            # error inside apply_filter, never silent.
            listed = wanted.get(title) if wanted else None
            if listed:
                hit = apply_filter(path, got, listed, errors)
                if hit is None:
                    continue
                count, got = hit
                flag = None  # merged already inside

            # Flags ride along; both still count.
            if flag:
                errors[path] = flag
            add(data, title, month, count, path, got)
            titles.setdefault(title, []).append(path)

        # Dupes need the full per-title set, so one pass
        # after the loop, never during.
        for title, paths in titles.items():
            flag_dupes(paths, errors)
    finally:
        if handle is not None:
            handle.close()
    rows = [
        data[key] for key in sorted(data)
    ]
    return {"data": rows, "errors": errors}, stats


# ---- Rendering: human stream for stderr ----


def format_count(data):
    lines = []
    for row in data["data"]:
        lines.append(
            f"{row['title']} {row['month']}: "
            f"{row['rows']} rows"
        )

    if data["errors"]:
        lines.append(f"{len(data['errors'])} errors:")
        for path, reason in data["errors"].items():
            lines.append(f"  {path}: {reason}")
    return "\n".join(lines)
