"""walk <path> [--progress] [--ignore=name] [--out=file]."""

import os
import sys
import time
from os.path import join, normpath

from normalization import heartbeat, slash, stdio

# Past this many lines the listing outgrows sorted-in
# memory comfort; warn once so the huge drive queues
# the streaming rewrite instead of surprising anyone.
TRIPWIRE = 100_000

# Checkpoint cadence for --out: a kill leaves the last
# full batch, never a torn file.
BATCH = 10_000


def atomic_write(path, lines):
    # Torn files lie: flush, fsync, rename over. Names
    # escape the same way stdio does, never throw.
    tmp = f"{path}.part"
    with open(tmp, "w", errors="backslashreplace") as handle:
        for line in lines:
            print(line, file=handle)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def snapshot(root, progress=None, ignore=(), out=None,
             batch=BATCH):
    # Pure listing: names only, zero stats. Membership
    # drift is all selection cares about; freshness lives
    # in count, which stats at open time anyway.
    # Paths stay root-prefixed so every line is directly
    # usable; normpath drops the ./ wart.
    # Ignored dir basenames never descend: the dir entry
    # itself stays as evidence, contents stay out.
    # With out, every batch checkpoints the as-found
    # prefix; the final write is the sorted listing.
    skipped = set(ignore)
    found = []
    stack = ["."]

    while stack:
        rel = stack.pop()
        with os.scandir(join(root, rel)) as it:
            # Stream live entries: sorted() would swallow
            # a huge dir before the first heartbeat. The
            # final return still sorts, so reruns match.
            for entry in it:
                relpath = join(rel, entry.name)
                path = slash(normpath(join(root, relpath)))
                if progress:
                    progress(len(found) + 1, None, path)
                if entry.is_dir(follow_symlinks=False):
                    found.append(path + "/")
                    if entry.name not in skipped:
                        stack.append(relpath)
                else:
                    found.append(path)
                if out is not None and len(found) % batch == 0:
                    atomic_write(out, found)
                if len(found) == TRIPWIRE:
                    print(
                        f"WARNING: walk past {TRIPWIRE} lines; "
                        "narrow the root or queue streaming",
                        file=sys.stderr,
                    )

    if out is not None:
        atomic_write(out, sorted(found))
    return sorted(found)


def main():
    stdio()
    flag = "--progress" in sys.argv[1:]
    ignore = tuple(
        a.split("=", 1)[1] for a in sys.argv[1:]
        if a.startswith("--ignore=")
    )
    args = [
        a for a in sys.argv[1:]
        if a != "--progress"
        and not a.startswith("--ignore=")
        and not a.startswith("--out=")
    ]
    out = next(
        (
            a.split("=", 1)[1] for a in sys.argv[1:]
            if a.startswith("--out=")
        ),
        None,
    )
    if not args:
        print(
            "usage: walk <path> [--progress] "
            "[--ignore=name] [--out=file]",
            file=sys.stderr,
        )
        sys.exit(2)
    start = time.monotonic()
    lines = snapshot(
        args[0], progress=heartbeat if flag else None,
        ignore=ignore, out=out,
    )
    if out is None:
        for line in lines:
            print(line)
    # Count on stderr: a short file after a kill reads
    # as drift, but the eye catches it first.
    print(
        f"{len(lines)} lines in "
        f"{time.monotonic() - start:.1f}s",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
