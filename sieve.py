"""sieve <curated> <walk> -> scrape JSON on stdout."""

import json
import sys
import time

from normalization import COPY_PRUNE, heartbeat, slash, stdio
from scrape import format_scrape, keep


def read_curated(handle):
    # Flat rows; claims carry (dir, contains, sheets).
    # Null dir is explicit absence, never fuzzer silence.
    # Sheets are comma-separated exact names; empty is
    # unfiltered. Fields strip ends-only on read, so
    # padding merges loud instead of mismatching silent.
    # Selection stays filename-level, so sheets change
    # nothing here.
    claims = {}
    nulls = []
    for line in handle:
        parts = line.rstrip("\n").split("\t")
        title = parts[0].strip()
        entry = parts[1].strip() if len(parts) > 1 else "-"
        contains = parts[2].strip() if len(parts) > 2 else ""
        raw = parts[3].strip() if len(parts) > 3 else ""
        sheets = tuple(
            name for name in (
                chunk.strip() for chunk in raw.split(",")
            ) if name
        )
        if entry == "-" or entry == "":
            nulls.append(title)
            continue
        claims.setdefault(title, []).append(
            (slash(entry.rstrip("/")), contains or None,
             sheets)
        )
    return claims, nulls


def refuse(claims):
    # One dir, one title, unless every claimant scopes by
    # filename token. Bare alongside token still counts
    # twice: refuse. Nested dirs across titles hide the
    # same double-count one level down: refuse those too.
    # Sheet-scoped claims split one dir by exact sheet
    # name instead: every claimant sheet-scoped passes,
    # shared sheet names refuse loud.
    owners = {}
    for title, items in claims.items():
        for path, contains, sheets in dict.fromkeys(items):
            owners.setdefault(path, []).append(
                (title, contains, sheets)
            )
    for path, entries in owners.items():
        titles = {title for title, _, _ in entries}
        if len(titles) > 1:
            seen = {}
            for title, _, sheets in entries:
                for name in sheets:
                    if name in seen and seen[name] != title:
                        sys.exit(
                            f"shared sheet {name}: "
                            f"{seen[name]} and {title}"
                        )
                    seen.setdefault(name, title)
            if any(
                contains is None
                for _, contains, _ in entries
            ) and not all(
                sheets for _, _, sheets in entries
            ):
                # Bare beside scoped still double-counts
                # unless every claimant is sheet-scoped.
                first = sorted(titles)[0]
                second = sorted(titles)[1]
                sys.exit(
                    f"shared dir {path}: {first} and {second}"
                )
    paths = sorted(owners)
    for i, inner in enumerate(paths):
        for outer in paths[i + 1:]:
            if inner.startswith(outer + "/"):
                sys.exit(
                    f"nested dir {inner} inside {outer}"
                )
            if outer.startswith(inner + "/"):
                sys.exit(
                    f"nested dir {outer} inside {inner}"
                )


def select(files, root, contains, progress=None):
    # keep/COPY_PRUNE predicates over walk lines instead of a
    # live walk: contains gate skips before seen, first
    # unique filename wins per directory, Copy-of prune.
    prefix = root + "/"
    found = []
    seen = set()
    examined = 0
    for path in files:
        if not path.startswith(prefix):
            continue
        examined += 1
        if progress:
            progress(examined, None, path)
        rel = path[len(prefix):]
        name = rel.rsplit("/", 1)[-1]
        reldir = rel.rsplit("/", 1)[0] if "/" in rel else ""
        key = (reldir, name.lower())
        if key not in seen and keep(name, rel):
            # Token match stays case-sensitive: A vs a
            # splits pinned in checks.
            if contains is not None and contains not in name:
                continue
            seen.add(key)
            found.append((name, path, reldir))
    originals = {}
    for name, _, reldir in found:
        if not COPY_PRUNE.match(name):
            originals.setdefault(reldir, set()).add(
                name.lower()
            )
    kept = [
        path for name, path, reldir in found
        if not COPY_PRUNE.match(name)
        or COPY_PRUNE.sub("", name, count=1).lower()
        not in originals.get(reldir, set())
    ]
    return sorted(kept), examined


def main():
    stdio()
    start = time.monotonic()
    flag = "--progress" in sys.argv[1:]
    args = [a for a in sys.argv[1:] if a != "--progress"]
    sidecar = None
    if "--sheets" in args:
        at = args.index("--sheets")
        if at + 1 >= len(args):
            print(
                "usage: sieve <curated> <walk> "
                "[--progress] [--sheets <path>]",
                file=sys.stderr,
            )
            sys.exit(2)
        sidecar = args[at + 1]
        args = args[:at] + args[at + 2:]
    if len(args) < 2:
        print(
            "usage: sieve <curated> <walk> "
            "[--progress] [--sheets <path>]",
            file=sys.stderr,
        )
        sys.exit(2)
    with open(args[0]) as handle:
        claims, nulls = read_curated(handle)
    if not claims and not nulls:
        print(
            "usage: sieve <curated> <walk> "
            "[--progress] [--sheets <path>]",
            file=sys.stderr,
        )
        sys.exit(2)
    refuse(claims)
    with open(args[1]) as handle:
        stripped = [line.strip() for line in handle]
    files = [
        line.split("\t")[0] for line in stripped
        if line and not line.endswith("/")
    ]
    scraped, seen_total, warnings = select_all(
        claims, files, progress=heartbeat if flag else None,
    )
    if sidecar is not None:
        write_sidecar(claims, sidecar)
    report(scraped, seen_total, nulls, warnings, start)
    print(json.dumps(scraped, indent=2))


def select_all(claims, files, progress=None):
    # Shared selection: sieve and auto ride one loop.
    # Warn lines collect so callers print them before
    # the timer; stderr order never moves.
    scraped = {}
    seen_total = {}
    warnings = []
    for title, items in claims.items():
        groups = {}
        seen = kept = 0
        warned = set()
        for root, contains, _ in items:
            paths, examined = select(
                files, root, contains, progress=progress,
            )
            if (
                contains is not None
                and not paths
                and (root, contains) not in warned
            ):
                warned.add((root, contains))
                warnings.append(
                    f"WARNING: {title}: token {contains} "
                    f"matched 0 of {examined} files"
                )
            seen += examined
            kept += len(paths)
            groups[root] = sorted(
                set(groups.get(root, ())) | set(paths)
            )
        scraped[title] = groups
        seen_total[title] = (seen, kept)
    return scraped, seen_total, warnings


def write_sidecar(claims, path):
    # Filtered titles only; absent means unfiltered.
    mapping = {}
    for title, items in claims.items():
        names = set()
        for _, _, sheets in items:
            names.update(sheets)
        if names:
            mapping[title] = sorted(names)
    with open(path, "w") as handle:
        json.dump(mapping, handle, indent=2, sort_keys=True)
        handle.write("\n")


def report(scraped, seen_total, nulls, warnings, start):
    for line in warnings:
        print(line, file=sys.stderr)
    total = sum(
        len(paths) for groups in scraped.values()
        for paths in groups.values()
    )
    print(f"{total} files in {time.monotonic() - start:.1f}s",
          file=sys.stderr)
    for title in nulls:
        print(
            f"WARNING: {title}: not mapped to any dir",
            file=sys.stderr,
        )
    for title, (seen, kept) in seen_total.items():
        if kept == 0:
            if seen == 0:
                print(
                    f"WARNING: {title}: no files found - "
                    "check the matched dir",
                    file=sys.stderr,
                )
            else:
                print(
                    f"WARNING: {title}: 0 of {seen} files "
                    "kept - check year tokens",
                    file=sys.stderr,
                )
    print(format_scrape(scraped), file=sys.stderr)


if __name__ == "__main__":
    main()
