import argparse
import json
import os
import sys
import time

from audit import summarize
from count import count_rows, format_count
from normalization import (
    heartbeat, read_lines, reset_heartbeat, stdio,
)
from pivot import format_pivot, format_sheet_pivot
from sieve import (
    read_curated, refuse, report, select_all, write_sidecar,
)
from walk import snapshot


def parse_args():
    parser = argparse.ArgumentParser(
        description="Batch titles in, counts out."
    )
    modes = parser.add_subparsers(
        dest="mode", required=True
    )

    # Stage 3: files in, row counts out.
    count = modes.add_parser(
        "count", help="files in, row counts out"
    )
    count.add_argument("--from-json", required=True)
    count.add_argument("--json", action="store_true")
    count.add_argument("--cache", default=None)
    count.add_argument("--sheets", default=None)
    count.add_argument(
        "--progress", action="store_true",
        help="heartbeat line every 50 files opened",
    )

    # Paste-over table for the hand-filled template.
    pivot = modes.add_parser(
        "pivot", help="counts in, paste-ready table out"
    )
    pivot.add_argument("--from-json", required=True)
    pivot.add_argument("--order", default=None)
    pivot.add_argument(
        "--by-sheet", action="store_true",
        help="one row per file sheet instead of per title",
    )

    # One command from curated to paste set; curation
    # itself stays manual, so a missing file refuses.
    auto = modes.add_parser(
        "auto", help="curated in, paste set out"
    )
    auto.add_argument("--root", required=True)
    auto.add_argument("--curated", required=True)
    auto.add_argument("--out-dir", default=".")
    auto.add_argument("--sheets", default=None)
    auto.add_argument("--cache", default=None)
    auto.add_argument("--order", default=None)
    auto.add_argument(
        "--by-sheet", action="store_true",
        help="one row per file sheet instead of per title",
    )
    auto.add_argument(
        "--progress", action="store_true",
        help="heartbeat line every 50 files opened",
    )

    args = parser.parse_args()
    return args


def load_json(path):
    try:
        with open(path) as handle:
            return json.load(handle)
    except OSError:
        sys.exit(f"cannot read {path}")
    except json.JSONDecodeError:
        sys.exit(
            f"{path} is not valid JSON - did the upstream "
            "step run without --json?"
        )


def run_count(scraped, wanted, cache, progress):
    # Shared count leg: rows in, data plus stats out,
    # timer on stderr. Callers own inputs and outputs.
    start = time.monotonic()
    data, stats = count_rows(
        scraped,
        progress=heartbeat if progress else None,
        cache=cache,
        wanted=wanted,
    )
    files = sum(
        len(paths) for groups in scraped.values()
        for paths in groups.values()
    )
    print(
        f"{files} files in "
        f"{time.monotonic() - start:.1f}s "
        f"({stats['opened']} opened)",
        file=sys.stderr,
    )
    return data, stats


def do_count(args):
    scraped = load_json(args.from_json)
    wanted = load_json(args.sheets) if args.sheets else None
    data, _ = run_count(
        scraped, wanted, args.cache, args.progress,
    )

    if args.json:
        print(json.dumps(data, indent=2))
        print(format_count(data), file=sys.stderr)
        return
    # Stdout stays empty without --json: machine-clean.
    print(format_count(data), file=sys.stderr)


def do_pivot(args):
    data = load_json(args.from_json)
    order = read_lines(args.order) if args.order else None
    if args.by_sheet:
        print(format_sheet_pivot(data, order))
    else:
        print(format_pivot(data, order))


def do_auto(args):
    try:
        with open(args.curated) as handle:
            curated_text = handle.read()
    except OSError:
        sys.exit(
            f"no {args.curated} - fuzz then hand-pass first"
        )
    with open(args.curated + ".bak", "w") as handle:
        handle.write(curated_text)
    os.makedirs(args.out_dir, exist_ok=True)

    start = time.monotonic()
    reset_heartbeat()
    lines = snapshot(
        args.root,
        progress=heartbeat if args.progress else None,
    )
    # Names escape the same way stdio does, never throw.
    with open(
        os.path.join(args.out_dir, "walk.txt"), "w",
        errors="backslashreplace",
    ) as h:
        for line in lines:
            print(line, file=h)
    print(
        f"{len(lines)} lines in "
        f"{time.monotonic() - start:.1f}s",
        file=sys.stderr,
    )

    with open(args.curated) as handle:
        claims, nulls = read_curated(handle)
    refuse(claims)
    stripped = [line.strip() for line in lines]
    files = [
        line.split("\t")[0] for line in stripped
        if line and not line.endswith("/")
    ]
    start = time.monotonic()
    reset_heartbeat()
    scraped, seen, warnings = select_all(
        claims, files,
        progress=heartbeat if args.progress else None,
    )
    if args.sheets is not None:
        write_sidecar(claims, args.sheets)
    report(scraped, seen, nulls, warnings, start)
    with open(
        os.path.join(args.out_dir, "scrape.json"), "w"
    ) as handle:
        handle.write(json.dumps(scraped, indent=2) + "\n")

    gate, keepable, _, _ = summarize(lines, scraped)
    print(gate, file=sys.stderr)
    if keepable:
        sys.exit(
            f"audit gate: KEEPABLE {keepable}, "
            "investigate first"
        )

    wanted = load_json(args.sheets) if args.sheets else None
    reset_heartbeat()
    data, _ = run_count(
        scraped, wanted, args.cache, args.progress,
    )
    print(format_count(data), file=sys.stderr)
    with open(
        os.path.join(args.out_dir, "count.json"), "w"
    ) as handle:
        handle.write(json.dumps(data, indent=2) + "\n")

    order = read_lines(args.order) if args.order else None
    if args.by_sheet:
        print(format_sheet_pivot(data, order))
    else:
        print(format_pivot(data, order))


def main():
    stdio()
    args = parse_args()
    if args.mode == "count":
        do_count(args)
    elif args.mode == "auto":
        do_auto(args)
    else:
        do_pivot(args)


if __name__ == "__main__":
    main()
