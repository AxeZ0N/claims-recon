"""reconcile <filtered> <unfiltered> <a> <b> -> split check.

Sheet-split shape only: unfiltered carries the combined
rows under both titles, so A+B must equal each of them.
"""

import json
import sys

from normalization import stdio


def load(path):
    try:
        with open(path) as handle:
            return json.load(handle)
    except OSError:
        sys.exit(f"cannot read {path}")
    except json.JSONDecodeError:
        sys.exit(f"{path} is not valid JSON")


def buckets(data):
    found = {}
    for row in data["data"]:
        found[(row["title"], row["month"])] = row["rows"]
    return found


def main():
    stdio()
    if len(sys.argv) != 5:
        print(
            "usage: reconcile <filtered> <unfiltered> "
            "<title-a> <title-b>",
            file=sys.stderr,
        )
        sys.exit(2)
    filt = buckets(load(sys.argv[1]))
    full = buckets(load(sys.argv[2]))
    first, second = sys.argv[3], sys.argv[4]
    keys = set(filt) | set(full)
    months = sorted({month for _, month in keys})

    bad = 0
    totals = [0, 0, 0]
    for month in months:
        part = (
            filt.get((first, month), 0),
            filt.get((second, month), 0),
        )
        want = full.get((first, month), 0)
        want_b = full.get((second, month), 0)
        good = part[0] + part[1] == want == want_b
        bad += not good
        totals[0] += part[0]
        totals[1] += part[1]
        totals[2] += want
        mark = "ok" if good else "MISMATCH"
        print(
            f"{month}: {part[0]}+{part[1]}="
            f"{part[0] + part[1]} vs {want} {mark}"
        )
    good = (
        totals[0] + totals[1] == totals[2] and bad == 0
    )
    mark = "ok" if good else "MISMATCH"
    print(
        f"totals: {totals[0]}+{totals[1]}="
        f"{totals[0] + totals[1]} vs {totals[2]} {mark}"
    )
    if not good:
        print(f"MISMATCH: {bad} months", file=sys.stderr)
        sys.exit(1)
    print("RECONCILED")


if __name__ == "__main__":
    main()
