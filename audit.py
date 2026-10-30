"""audit <walk> <scrape> [old] -> orphans plus drift."""

import json
import sys

from normalization import (
    COPY_PRUNE, read_lines, resolve_month, stdio,
)
from scrape import gate_cause, keep


def read_text(path):
    try:
        with open(path) as handle:
            return handle.read()
    except OSError:
        sys.exit(f"cannot read {path}")


def load_scrape(path):
    try:
        return json.loads(read_text(path))
    except json.JSONDecodeError:
        sys.exit(f"{path} is not valid JSON")


def parse_dump(text):
    # Yesterday's 2> redirect: format_scrape human stream.
    # "Title:" lines at depth 0, "  root: N files"
    # headers at depth 2, "    path" lines at depth 4.
    # Dirs don't survive; titles and paths do, which is
    # all drift needs.
    found = {}
    title = None
    for line in text.splitlines():
        depth = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if not stripped:
            continue
        if depth < 4:
            if depth == 0 and stripped.endswith(":"):
                title = stripped[:-1]
            continue
        if title is None:
            continue
        found.setdefault(title, {}).setdefault(
            "(dump)", []
        ).append(stripped)
    return found


def load_old(path):
    text = read_text(path)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return parse_dump(text)
    if isinstance(data, dict):
        return data
    sys.exit(f"{path} is not a scrape mapping")


def judge(path, roots, originals):
    # One path, one verdict. Longest root governs; the
    # buckets match the report below.
    hits = sorted(
        root for root in roots
        if path.startswith(root + "/")
    )
    if not hits:
        return "outside", None
    root = hits[-1]
    name = path.rsplit("/", 1)[-1]
    rel = path[len(root) + 1:]
    month, reason = resolve_month(name)
    if not keep(name, rel):
        return "gated", gate_cause(name)
    if month is None:
        return "gated", reason
    head = rel.rpartition("/")[0]
    subbed = COPY_PRUNE.sub("", name, count=1).lower()
    if COPY_PRUNE.match(name) and subbed in originals.get(
        (root, head), set()
    ):
        # Approximation: originals ignore contains gates,
        # so a token-missed copy can read as pruned. Rare;
        # KEEPABLE lines stay exact, pruned only tallies.
        return "pruned", None
    return "keepable", (month, root, roots[root])


def title_sets(scraped):
    return {
        title: {
            path
            for groups in mapping.values()
            for path in groups
        }
        for title, mapping in scraped.items()
    }


def summarize(lines, scraped):
    # Pure orphan math for both audit and auto. Returns
    # the report text plus the keepable count the auto
    # gate refuses on.
    files = sorted(
        path for path in lines if not path.endswith("/")
    )
    kept = {
        path
        for groups in scraped.values()
        for paths in groups.values()
        for path in paths
    }
    roots = {}
    for title, groups in scraped.items():
        for root in groups:
            roots.setdefault(root, []).append(title)

    originals = {}
    for path in kept:
        base = path.rsplit("/", 1)[-1]
        if COPY_PRUNE.match(base):
            continue
        for root in roots:
            if path.startswith(root + "/"):
                rel = path[len(root) + 1:]
                head = rel.rpartition("/")[0]
                originals.setdefault(
                    (root, head), set()
                ).add(base.lower())

    orphans = sorted(set(files) - kept)
    outside = 0
    gated = {}
    pruned = 0
    keepable = []
    for path in orphans:
        kind, info = judge(path, roots, originals)
        if kind == "outside":
            outside += 1
        elif kind == "gated":
            gated[info] = gated.get(info, 0) + 1
        elif kind == "pruned":
            pruned += 1
        else:
            keepable.append((path,) + info)

    found = [
        f"walk: {len(files)} files",
        f"scrape: {len(kept)} kept across "
        f"{len(scraped)} titles, {len(roots)} dirs",
        f"orphans: {len(orphans)} "
        f"({outside} outside all claims)",
        "gated by design:",
    ]
    for cause in sorted(gated):
        found.append(f"  {cause}: {gated[cause]}")
    if pruned:
        found.append(f"  pruned copy (original kept): {pruned}")
    found.append(f"KEEPABLE: {len(keepable)}")
    for path, month, root, titles in keepable:
        joined = ", ".join(titles)
        found.append(f"*** INVESTIGATE *** {path}")
        found.append(f"    month {month}, via {joined} @ {root}")
    return "\n".join(found), len(keepable), roots, originals


def main():
    stdio()
    if len(sys.argv) != 3 and len(sys.argv) != 4:
        print(
            "usage: audit <walk> <scrape> [old-scrape]",
            file=sys.stderr,
        )
        sys.exit(2)
    try:
        lines = read_lines(sys.argv[1])
    except OSError:
        sys.exit(f"cannot read {sys.argv[1]}")
    scraped = load_scrape(sys.argv[2])

    report, _, roots, originals = summarize(lines, scraped)
    print(report)

    if len(sys.argv) == 4:
        old = load_old(sys.argv[3])
        want = title_sets(old)
        got = title_sets(scraped)
        owners = {}
        for title, paths in want.items():
            for path in paths:
                owners.setdefault(path, []).append(title)
        doubled = sorted(
            path for path, ts in owners.items()
            if len(ts) > 1
        )
        old_all = set(owners)
        new_all = set().union(*got.values()) if got else set()
        dropped = sorted(old_all - new_all)
        added = sorted(new_all - old_all)
        print(
            f"drift: old {len(old_all)} paths, "
            f"new {len(new_all)}"
        )
        print(f"doubled: {len(doubled)}")
        for path in doubled:
            print(f"  {path} <- " + ", ".join(owners[path]))
        print(f"dropped: {len(dropped)}")
        for path in dropped:
            kind, info = judge(path, roots, originals)
            if kind == "keepable":
                month, root, _ = info
                print(f"  {path} keepable ({month})")
            elif kind == "outside":
                print(f"  {path} outside today's claims")
            elif kind == "pruned":
                print(f"  {path} pruned copy")
            else:
                print(f"  {path} gated: {info}")
        print(f"added: {len(added)}")
        for path in added:
            print(f"  {path}")


if __name__ == "__main__":
    main()
