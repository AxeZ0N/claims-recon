"""fuzz <titles> <walk> -> proposal rows on stdout."""

import sys
import time
from os.path import basename

from rapidfuzz import fuzz

from normalization import heartbeat, normalize, read_lines, stdio

# Floor for a proposal; below it, titles null-seed.
CUTOFF = 75


def dirs_of(lines):
    # Every ancestor prefix is claimable; dir entries
    # count themselves, files contribute parents.
    found = set()
    for line in lines:
        path = line.strip().split("\t")[0]
        if path.endswith("/"):
            path = path.rstrip("/")
            found.add(path)
        while "/" in path:
            path = path.rsplit("/", 1)[0]
            found.add(path)
    return sorted(found)


def propose(titles, dirs, cutoff=CUTOFF, progress=None):
    # One fuzzy pass, same contract as match: normalized
    # token_set_ratio, shallowest wins ties (strictly
    # greater displaces, depth order stands in for walk).
    ordered = sorted(dirs, key=lambda d: (d.count("/"), d))
    rows = []
    for number, title in enumerate(titles, 1):
        if progress:
            progress(number, len(titles), title)
        want = normalize(title)
        current = None
        for path in ordered:
            score = fuzz.token_set_ratio(
                normalize(basename(path)), want
            )
            if score >= cutoff and (
                current is None or score > current[1]
            ):
                current = (path, score)
        if current is None:
            rows.append((title, "-", "", "", "no match"))
        else:
            path, score = current
            rows.append((title, path, "", "", f"{score:.2f}"))
    return rows


def main():
    stdio()
    start = time.monotonic()
    flag = "--progress" in sys.argv[1:]
    args = [a for a in sys.argv[1:] if a != "--progress"]
    if len(args) < 2:
        print(
            "usage: fuzz <titles> <walk> [--progress]",
            file=sys.stderr,
        )
        sys.exit(2)
    titles = read_lines(args[0])
    with open(args[1]) as handle:
        candidates = dirs_of(handle)

    rows = propose(
        titles, candidates,
        progress=heartbeat if flag else None,
    )

    owners = {}
    for title, path, _, _, _ in rows:
        if path != "-":
            owners.setdefault(path, []).append(title)
    collisions = 0
    for path in sorted(owners):
        if len(owners[path]) > 1:
            collisions += 1
            joined = ", ".join(owners[path])
            print(
                f"COLLISION: {path} <- {joined}",
                file=sys.stderr,
            )

    # Fifth column is a trailing aside; readers take [:4],
    # so scores linger harmlessly after human confirm.
    for row in rows:
        print("\t".join(row))

    # Counts on stderr: nulls are fill-in-the-blank, not gaps.
    matched = sum(1 for row in rows if row[1] != "-")
    print(
        f"{matched}/{len(rows)} matched, "
        f"{collisions} collisions in "
        f"{time.monotonic() - start:.1f}s",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
