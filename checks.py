"""Smoke checks for the pipeline. Run from the repo root."""

import io
import json
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager, redirect_stderr
from unittest import mock

from count import LOGIC
from normalization import slash
from scrape import format_scrape
from walk import snapshot

ROOT = "testdata"


def P(*parts):
    # Expected paths in artifact form: forward slashes.
    return slash(os.path.join(*parts))
TITLES = P(ROOT, "titles.txt")
ACME = P(ROOT, "Acme Corp Claim Files", "2026")
HARBOR = P(ROOT, "Harbor View Medical")
MISC = P(HARBOR, "misc")
DEEP = P(MISC, "deep")
PORT = P(ROOT, "Portside Dentail LLC", "2026")

# Must match gen_testdata.py row counts.
COUNTS = [
    ("Acme Corp Claim", "2026-01", 11), # +jan-report pair
    ("Acme Corp Claim", "2026-02", 6),
    ("Acme Corp Claim", "2026-04", 8), # +4.1.26.pdf anchors
    ("Acme Corp Claim", "2026-06", 4), # stacked overcount
    ("Acme Corp Claim", "2026-08", 5), # MDY4 8.12.2026
    ("Acme Corp Claim", "2026-09", 3), # MDY8 09152026
    ("Acme Corp Claim", "2026-10", 4), # YMD8 20261015
    ("Harbor View Medical", "2026-03", 8), # whitespace twin kept
    ("Harbor View Medical", "2026-04", 5), # paren pair
    ("Harbor View Medical", "2026-05", 2), # ISO 2026-05
    ("Harbor View Medical", "2026-06", 4), # 6.11 decoys out
    ("Harbor View Medical", "2026-07", 3), # stray-note overcount
    ("Portside Dental", "2026-03", 7),
    ("Portside Dental", "2026-04", 3), # REV 4-2026
    ("Portside Dental", "2026-05", 4),
]

FLAGGED = {
    P(ACME, "Copy of lost.xlsx"),
    P(ACME, "Apr 26.xlsx"),
    P(ACME, "reissue", "Jan 26.xlsx"),
    P(ACME, "jan-report 26.xlsx"),
    P(ACME, "Mar 2025.xlsx"),
    P(ACME, "Bogus Jun 26.xlsx"),
    P(HARBOR, "stray 2026 notes.xlsx"),
    P(MISC, "summary 26.xlsx"),
    P(MISC, "Mar 26.xlsx"),
    P(MISC, "Report Apr 26.xlsx"),
    P(MISC, "lost 26.pdf"),
    P(MISC, "Empty-note Jul 26.xlsx"),
    P(MISC, "Stray-empty Jul 26.pdf"),
    P(DEEP, "count 26 pcs.xlsx"),
}


def run(*args, script="main.py", env=None):
    environ = dict(os.environ)
    if env:
        environ.update(env)
    proc = subprocess.run(
        [sys.executable, script, *args],
        capture_output=True, text=True, env=environ,
    )
    return proc.returncode, proc.stdout, proc.stderr


@contextmanager
def as_txt(text, suffix=".txt"):
    # Subprocesses open by path, so delete=False then
    # unlink after; Windows stays happy.
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=suffix, delete=False
    )
    handle.write(text)
    handle.close()
    try:
        yield handle.name
    finally:
        os.unlink(handle.name)


@contextmanager
def as_json(mapping):
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False
    )
    json.dump(mapping, handle)
    handle.close()
    try:
        yield handle.name
    finally:
        os.unlink(handle.name)


def check(name, cond, state):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        FAILED.append(name)
    else:
        PASSED.append(name)
    return state and cond


FAILED = []
PASSED = []


class FlushCount(io.StringIO):
    # Counts explicit flushes: print(flush=True)
    # flushes once, buffered prints never do.
    def __init__(self):
        super().__init__()
        self.flushes = 0

    def flush(self):
        self.flushes += 1
        return super().flush()


def walk_text():
    code, out, _ = run(ROOT, script="walk.py")
    assert code == 0
    return out


def check_usage(ok):
    code, _, _ = run(script="walk.py")
    ok = check("walk needs a path", code == 2, ok)

    code, _, _ = run(script="fuzz.py")
    ok = check("fuzz needs titles and walk", code == 2, ok)

    code, _, _ = run(script="sieve.py")
    ok = check("sieve needs curated and walk", code == 2, ok)
    return ok


def check_clean(ok):
    code, walk_out, _ = run(ROOT, script="walk.py")
    with as_txt(walk_out) as walk_file:
        code, props, _ = run(TITLES, walk_file, script="fuzz.py")
        ok = check(
            "tools stdout stays machine-clean",
            code == 0 and "lines in" not in walk_out
            and "COLLISION" not in props
            and all(
                len(row.split("\t")) == 5
                for row in props.splitlines()
            ), ok,
        )
    return ok


def check_progress(ok):
    code, _, prog_err = run(ROOT, "--progress", script="walk.py")
    ok = check(
        "walk progress heartbeat",
        code == 0 and "[1," in prog_err, ok,
    )

    with as_txt(walk_text()) as walk_file:
        code, props, _ = run(TITLES, walk_file, script="fuzz.py")
        with as_txt(props) as props_file:
            code, _, prog_err = run(
                props_file, walk_file, "--progress",
                script="sieve.py",
            )
            ok = check(
                "sieve progress heartbeat",
                code == 0 and "[1," in prog_err, ok,
            )
    return ok


def check_auto_walk(ok):
    code, _, _ = run("auto", "--root", ROOT)
    ok = check("auto needs root and curated", code == 2, ok)
    with as_txt("Title\tDir\t\t\n") as cur:
        code, _, err = run(
            "auto", "--root", ROOT,
            "--curated", cur + ".missing",
        )
        ok = check(
            "auto refuses without curated",
            code == 1 and "hand-pass first" in err, ok,
        )
    with as_txt("Title\tDir\t\t\n") as cur:
        with tempfile.TemporaryDirectory() as tmp:
            code, _, err = run(
                "auto", "--root", ROOT, "--curated", cur,
                "--out-dir", tmp,
            )
            with open(os.path.join(tmp, "walk.txt")) as handle:
                listed = handle.read()
            _, fresh, _ = run(ROOT, script="walk.py")
            ok = check(
                "auto walk matches walk.py",
                code == 0 and listed == fresh
                and "lines in" in err, ok,
            )
        with open(cur + ".bak") as handle:
            backup = handle.read()
        ok = check(
            "auto snapshots curated backup",
            backup == "Title\tDir\t\t\n", ok,
        )
        os.unlink(cur + ".bak")
    return ok


def check_auto_sieve(ok):
    sheet_dir = P(ROOT, "Sheet Co")
    with as_txt(walk_text()) as walk_file:
        _, props, _ = run(TITLES, walk_file, script="fuzz.py")
        with as_txt(props) as cur:
            code, out, _ = run(cur, walk_file, script="sieve.py")
            with tempfile.TemporaryDirectory() as tmp:
                _, _, _ = run(
                    "auto", "--root", ROOT, "--curated", cur,
                    "--out-dir", tmp,
                )
                with open(
                    os.path.join(tmp, "scrape.json")
                ) as handle:
                    ok = check(
                        "auto scrape matches sieve",
                        handle.read() == out, ok,
                    )
            os.unlink(cur + ".bak")
        rows = (
            f"Sheet A\t{sheet_dir}\t\tAlpha\t\n"
            f"Sheet B\t{sheet_dir}\t\tBeta\t\n"
        )
        with as_txt(rows) as cur:
            code, out, _ = run(cur, walk_file, script="sieve.py")
            with tempfile.TemporaryDirectory() as tmp:
                side = os.path.join(tmp, "sheets.json")
                _, _, _ = run(
                    "auto", "--root", ROOT, "--curated", cur,
                    "--out-dir", tmp, "--sheets", side,
                )
                with open(
                    os.path.join(tmp, "scrape.json")
                ) as handle:
                    ok = check(
                        "auto sheet scrape matches",
                        handle.read() == out, ok,
                    )
                with open(side) as handle:
                    ok = check(
                        "auto sidecar matches sieve",
                        json.load(handle) == {
                            "Sheet A": ["Alpha"],
                            "Sheet B": ["Beta"],
                        }, ok,
                    )
            os.unlink(cur + ".bak")
    return ok


def check_auto_gate(ok):
    with as_txt(walk_text()) as walk_file:
        _, props, _ = run(TITLES, walk_file, script="fuzz.py")
        with tempfile.TemporaryDirectory() as tmp:
            open(
                os.path.join(tmp, "Extra Jan 26.xlsx"), "w"
            ).close()
            with as_txt(f"T\t{tmp}\tZZZ\t\n") as cur:
                with tempfile.TemporaryDirectory() as out:
                    code, _, err = run(
                        "auto", "--root", tmp, "--curated",
                        cur, "--out-dir", out,
                    )
                    ok = check(
                        "auto gate refuses keepable",
                        code == 1 and "KEEPABLE" in err
                        and not os.path.exists(
                            os.path.join(out, "count.json")
                        ), ok,
                    )
                os.unlink(cur + ".bak")
        with as_txt(props) as cur:
            with tempfile.TemporaryDirectory() as tmp:
                code, _, err = run(
                    "auto", "--root", ROOT, "--curated", cur,
                    "--out-dir", tmp,
                )
                with open(
                    os.path.join(tmp, "count.json")
                ) as handle:
                    data = json.load(handle)
                got = [
                    (row["title"], row["month"], row["rows"])
                    for row in data["data"]
                ]
                ok = check(
                    "auto count matches pipeline",
                    code == 0 and got == COUNTS
                    and "KEEPABLE: 0" in err, ok,
                )
            os.unlink(cur + ".bak")
    return ok


def check_auto_pivot(ok):
    sheet_dir = P(ROOT, "Sheet Co")
    rows = (
        f"Sheet A\t{sheet_dir}\t\tAlpha\t\n"
        f"Sheet B\t{sheet_dir}\t\tBeta\t\n"
    )
    with as_txt(walk_text()) as walk_file:
        with as_txt(rows) as cur:
            with tempfile.TemporaryDirectory() as tmp:
                side = os.path.join(tmp, "sheets.json")
                code, table, _ = run(
                    "auto", "--root", ROOT, "--curated", cur,
                    "--out-dir", tmp, "--sheets", side,
                )
                with open(
                    os.path.join(tmp, "count.json")
                ) as handle:
                    claims = json.load(handle)
                split = {
                    (row["title"], row["month"]): row["rows"]
                    for row in claims["data"]
                }
                ok = check(
                    "auto end-to-end splits sheets",
                    code == 0 and split == {
                        ("Sheet A", "2026-01"): 2,
                        ("Sheet A", "2026-02"): 2,
                        ("Sheet B", "2026-01"): 3,
                        ("Sheet B", "2026-02"): 3,
                    }, ok,
                )
                with as_json(claims) as count_file:
                    _, want, _ = run(
                        "pivot", "--from-json", count_file,
                    )
                    ok = check(
                        "auto pivot matches pivot",
                        code == 0 and table == want, ok,
                    )
                    _, want, _ = run(
                        "pivot", "--from-json", count_file,
                        "--by-sheet",
                    )
                    code, got, _ = run(
                        "auto", "--root", ROOT,
                        "--curated", cur,
                        "--out-dir", tmp, "--sheets", side,
                        "--by-sheet",
                    )
                    ok = check(
                        "auto sheet pivot matches",
                        code == 0 and got == want, ok,
                    )
            os.unlink(cur + ".bak")
    return ok


def check_split(ok, walk_out):
    split_dir = P(ROOT, "Split Co")
    with as_txt(walk_out) as walk_file:
        with as_txt(
            f"Split A\t{split_dir}\tA\t\n"
            f"Split B\t{split_dir}\tB\t\n"
        ) as split_cur:
            code, out, _ = run(
                split_cur, walk_file, script="sieve.py"
            )
            ok = check("token split exits clean", code == 0, ok)
            with as_json(json.loads(out)) as split_scrape:
                code, out, _ = run(
                    "count", "--from-json", split_scrape, "--json",
                )
                rows = {
                    row["title"]: (row["month"], row["rows"])
                    for row in json.loads(out)["data"]
                }
                ok = check(
                    "token split partitions",
                    rows == {
                        "Split A": ("2026-01", 2),
                        "Split B": ("2026-01", 3),
                    }, ok,
                )

            with as_txt(f"Split\t{split_dir}\t\t\n") as whole:
                code, out, _ = run(
                    whole, walk_file, script="sieve.py"
                )
                with as_json(json.loads(out)) as whole_scrape:
                    code, out, _ = run(
                        "count", "--from-json", whole_scrape,
                        "--json",
                    )
                    data = json.loads(out)["data"]
                    ok = check(
                        "split sums to combined",
                        len(data) == 1 and data[0]["rows"] == 5,
                        ok,
                    )

            cases = [
                (
                    f"Split A\t{split_dir}\t\t\n"
                    f"Split B\t{split_dir}\t\t\n",
                    "bare double-claim still refused",
                ),
                (
                    f"Split A\t{split_dir}\t\t\n"
                    f"Split B\t{split_dir}\tB\t\n",
                    "bare plus token still refused",
                ),
            ]
            for text, name in cases:
                with as_txt(text) as cur:
                    code, _, err = run(
                        cur, walk_file, script="sieve.py"
                    )
                    ok = check(
                        name, code != 0 and "shared dir" in err, ok,
                    )

            pins = [
                (
                    f"Upper\t{split_dir}\tA\t\n",
                    [P(split_dir, "Item A Jan 26.xlsx")],
                ),
                (
                    f"Lower\t{split_dir}\ta\t\n",
                    [
                        P(split_dir, "Item A Jan 26.xlsx"),
                        P(split_dir, "Item B Jan 26.xlsx"),
                    ],
                ),
            ]
            for text, want in pins:
                with as_txt(text) as cur:
                    code, out, _ = run(
                        cur, walk_file, script="sieve.py"
                    )
                    got = json.loads(out) if code == 0 else {}
                    title = text.split("\t")[0]
                    ok = check(
                        f"token gate stays sensitive {title}",
                        code == 0
                        and got.get(title, {}).get(split_dir)
                        == want, ok,
                    )

            with as_txt(
                f"Ghost\t{split_dir}\tZZZ\t\n"
            ) as cur:
                code, out, err = run(
                    cur, walk_file, script="sieve.py"
                )
                ok = check(
                    "token zero-match warns loud",
                    code == 0 and "matched 0 of" in err
                    and json.loads(out) == {
                        "Ghost": {split_dir: []},
                    }, ok,
                )
    return ok


def check_sheet_split(ok, walk_out):
    sheet_dir = P(ROOT, "Sheet Co")
    rows = (
        f"Sheet A\t{sheet_dir}\t\tAlpha\t\n"
        f"Sheet B\t{sheet_dir}\t\tBeta\t\n"
    )
    with as_txt(walk_out) as walk_file:
        with as_txt(rows) as cur:
            code, out, _ = run(
                cur, walk_file, script="sieve.py"
            )
            ok = check("sheet split exits clean", code == 0, ok)
            got = json.loads(out) if code == 0 else {}
            ok = check(
                "sheet split shares the dir",
                code == 0 and set(got) == {"Sheet A", "Sheet B"}
                and got["Sheet A"][sheet_dir]
                == got["Sheet B"][sheet_dir]
                and got["Sheet A"][sheet_dir] != [], ok,
            )
        with as_txt(
            f"Sheet A\t{sheet_dir}\t\tAlpha\t\n"
            f"Sheet B\t{sheet_dir}\t\tAlpha\t\n"
        ) as cur:
            code, _, err = run(
                cur, walk_file, script="sieve.py"
            )
            ok = check(
                "sheet overlap refused",
                code != 0 and "shared sheet" in err, ok,
            )
        with as_txt(
            f"Sheet A\t{sheet_dir}\t\t\n"
            f"Sheet B\t{sheet_dir}\t\tBeta\t\n"
        ) as cur:
            code, _, err = run(
                cur, walk_file, script="sieve.py"
            )
            ok = check(
                "bare plus sheet still refused",
                code != 0 and "shared dir" in err, ok,
            )
        with as_txt(rows) as cur:
            with as_txt("", suffix=".json") as sidecar:
                code, out, _ = run(
                    cur, walk_file, "--sheets", sidecar,
                    script="sieve.py",
                )
                with open(sidecar) as handle:
                    mapping = json.load(handle)
                ok = check(
                    "sidecar content exact",
                    code == 0 and mapping == {
                        "Sheet A": ["Alpha"],
                        "Sheet B": ["Beta"],
                    }, ok,
                )
                code, plain, _ = run(
                    cur, walk_file, script="sieve.py"
                )
                ok = check(
                    "sidecar leaves stdout identical",
                    code == 0 and out == plain, ok,
                )
        with as_txt(
            f"Sheet A\t{sheet_dir}\t\tAlpha, Beta\t\n"
            f"Sheet B\t{sheet_dir}\t\tGamma\t\n"
        ) as cur:
            code, out, _ = run(
                cur, walk_file, script="sieve.py"
            )
            with as_txt("", suffix=".json") as sidecar:
                code, _, _ = run(
                    cur, walk_file, "--sheets", sidecar,
                    script="sieve.py",
                )
                with open(sidecar) as handle:
                    mapping = json.load(handle)
                ok = check(
                    "comma sheets parse plus strip",
                    code == 0 and mapping == {
                        "Sheet A": ["Alpha", "Beta"],
                        "Sheet B": ["Gamma"],
                    }, ok,
                )
        with as_txt(
            f"A\t{sheet_dir}\t\tAlpha\t\n"
            f"A\t{sheet_dir}\t\tBeta\t\n"
        ) as cur:
            code, out, _ = run(
                cur, walk_file, script="sieve.py"
            )
            with as_txt("", suffix=".json") as sidecar:
                code, _, _ = run(
                    cur, walk_file, "--sheets", sidecar,
                    script="sieve.py",
                )
                with open(sidecar) as handle:
                    mapping = json.load(handle)
                ok = check(
                    "multi-row sheets union",
                    code == 0 and mapping == {
                        "A": ["Alpha", "Beta"],
                    }, ok,
                )
    return ok


def check_sheet_count(ok, walk_out):
    sheet_dir = P(ROOT, "Sheet Co")
    rows = (
        f"Sheet A\t{sheet_dir}\t\tAlpha\t\n"
        f"Sheet B\t{sheet_dir}\t\tBeta\t\n"
    )
    ok = check(
        "count logic bumped for sheets", LOGIC == 2, ok,
    )
    with as_txt(walk_out) as walk_file:
        with as_txt(rows) as cur:
            code, out, _ = run(
                cur, walk_file, script="sieve.py"
            )
            with as_json(json.loads(out)) as scrape:
                code, out, _ = run(
                    "count", "--from-json", scrape, "--json",
                )
                combined = {}
                for row in json.loads(out)["data"]:
                    key = (row["title"], row["month"])
                    combined[key] = row["rows"]
                with as_txt(
                    '{"Sheet A": ["Alpha"], '
                    '"Sheet B": ["Beta"]}'
                ) as wanted:
                    code, out, _ = run(
                        "count", "--from-json", scrape,
                        "--json", "--sheets", wanted,
                    )
                    split = {}
                    for row in json.loads(out)["data"]:
                        key = (row["title"], row["month"])
                        split[key] = row["rows"]
                    ok = check(
                        "sheet filter splits months",
                        code == 0 and split == {
                            ("Sheet A", "2026-01"): 2,
                            ("Sheet A", "2026-02"): 2,
                            ("Sheet B", "2026-01"): 3,
                            ("Sheet B", "2026-02"): 3,
                        }, ok,
                    )
                    months = ("2026-01", "2026-02")
                    need = {
                        (title, month)
                        for title in ("Sheet A", "Sheet B")
                        for month in months
                    }
                    ok = check(
                        "sheet A+B==combined",
                        code == 0 and need <= set(split)
                        and need <= set(combined)
                        and all(
                            split[("Sheet A", month)]
                            + split[("Sheet B", month)]
                            == combined[("Sheet A", month)]
                            == combined[("Sheet B", month)]
                            for month in months
                        ), ok,
                    )
                with as_txt(
                    '{"Sheet A": ["Alpha"]}'
                ) as wanted:
                    code, out, _ = run(
                        "count", "--from-json", scrape,
                        "--json", "--sheets", wanted,
                    )
                    bee = {
                        row["month"]: row["rows"]
                        for row in json.loads(out)["data"]
                        if row["title"] == "Sheet B"
                    }
                    ok = check(
                        "unfiltered title untouched",
                        code == 0 and bee == {
                            "2026-01": combined.get(
                                ("Sheet B", "2026-01")),
                            "2026-02": combined.get(
                                ("Sheet B", "2026-02")),
                        }, ok,
                    )
        with as_txt(
            f"Sheet A\t{sheet_dir}\t\tGamma\t\n"
        ) as cur:
            code, out, _ = run(
                cur, walk_file, script="sieve.py"
            )
            with as_json(json.loads(out)) as scrape:
                with as_txt(
                    '{"Sheet A": ["Gamma"]}'
                ) as wanted:
                    code, out, _ = run(
                        "count", "--from-json", scrape,
                        "--json", "--sheets", wanted,
                    )
                    claims = json.loads(out)
                    got = claims["errors"].values()
                    ok = check(
                        "missing sheet errors loud",
                        code == 0 and claims["data"] == []
                        and len(claims["errors"]) == 2
                        and all("Gamma" in v for v in got),
                        ok,
                    )
        with as_txt(rows) as cur:
            code, out, _ = run(
                cur, walk_file, script="sieve.py"
            )
            with as_json(json.loads(out)) as scrape:
                with as_txt(
                    '{"Sheet A": ["Alpha", "Beta", "Gamma"], '
                    '"Sheet B": ["Beta"]}'
                ) as wanted:
                    code, out, _ = run(
                        "count", "--from-json", scrape,
                        "--json", "--sheets", wanted,
                    )
                    claims = json.loads(out)
                    got = set(claims["errors"].values())
                    split = {
                        (row["title"], row["month"]): row["rows"]
                        for row in claims["data"]
                    }
                    ok = check(
                        "partial absent merges loud",
                        code == 0
                        and got == {
                            "2 sheets; missing sheet Gamma",
                        }
                        and split == {
                            ("Sheet A", "2026-01"): 5,
                            ("Sheet A", "2026-02"): 5,
                            ("Sheet B", "2026-01"): 3,
                            ("Sheet B", "2026-02"): 3,
                        }, ok,
                    )
        with as_txt(
            f"Sheet A\t{sheet_dir}\t\tGamma\t\n"
        ) as cur:
            code, out, _ = run(
                cur, walk_file, script="sieve.py"
            )
            with as_json(json.loads(out)) as scrape:
                cases = [
                    (
                        '{"Sheet A": ["Gamma", "Delta"]}',
                        "missing sheets Gamma, Delta",
                        "plural absent names loud",
                    ),
                    (
                        '{"Sheet A": ["alpha"]}',
                        "missing sheet alpha",
                        "sheet match stays exact",
                    ),
                ]
                for sidecar, want, name in cases:
                    with as_txt(sidecar) as wanted:
                        code, out, _ = run(
                            "count", "--from-json", scrape,
                            "--json", "--sheets", wanted,
                        )
                        claims = json.loads(out)
                        got = claims["errors"].values()
                        ok = check(
                            name,
                            code == 0
                            and claims["data"] == []
                            and len(claims["errors"]) == 2
                            and all(v == want for v in got),
                            ok,
                        )
    return ok


def check_strip(ok, walk_out):
    split_dir = P(ROOT, "Split Co")
    sheet_dir = P(ROOT, "Sheet Co")
    with as_txt(walk_out) as walk_file:
        with as_txt(
            f"A\t {split_dir} \t\t\n"
            f"B\t{split_dir}\t\t\n"
        ) as cur:
            code, _, err = run(
                cur, walk_file, script="sieve.py"
            )
            ok = check(
                "padded dir merges loud",
                code != 0 and "shared dir" in err, ok,
            )
        with as_txt(
            f"Split A\t{split_dir}\t A \t\n"
            f"Split B\t{split_dir}\t B \t\n"
        ) as cur:
            code, out, _ = run(
                cur, walk_file, script="sieve.py"
            )
            with as_json(json.loads(out)) as scrape:
                code, out, _ = run(
                    "count", "--from-json", scrape, "--json",
                )
                rows = {
                    row["title"]: (row["month"], row["rows"])
                    for row in json.loads(out)["data"]
                }
                ok = check(
                    "padded token still splits",
                    code == 0 and rows == {
                        "Split A": ("2026-01", 2),
                        "Split B": ("2026-01", 3),
                    }, ok,
                )
        with as_txt(
            f"Sheet A\t{sheet_dir}\t\t Alpha \t\n"
            f"Sheet B\t{sheet_dir}\t\t Beta \t\n"
        ) as cur:
            code, out, _ = run(
                cur, walk_file, script="sieve.py"
            )
            ok = check(
                "padded sheets still scope",
                code == 0 and json.loads(out), ok,
            )
            with as_txt("", suffix=".json") as sidecar:
                code, _, _ = run(
                    cur, walk_file, "--sheets", sidecar,
                    script="sieve.py",
                )
                with open(sidecar) as handle:
                    mapping = json.load(handle)
                ok = check(
                    "padded sheets sidecar exact",
                    code == 0 and mapping == {
                        "Sheet A": ["Alpha"],
                        "Sheet B": ["Beta"],
                    }, ok,
                )
        with as_txt("Ghost\t - \t\t\n") as cur:
            code, out, err = run(
                cur, walk_file, script="sieve.py"
            )
            ok = check(
                "padded null still nulls",
                code == 0 and "not mapped" in err
                and json.loads(out) == {}, ok,
            )
    return ok


def check_reconcile(ok, walk_out):
    sheet_dir = P(ROOT, "Sheet Co")
    rows = (
        f"Sheet A\t{sheet_dir}\t\tAlpha\t\n"
        f"Sheet B\t{sheet_dir}\t\tBeta\t\n"
    )
    with as_txt(walk_out) as walk_file:
        with as_txt(rows) as cur:
            code, out, _ = run(
                cur, walk_file, script="sieve.py"
            )
            with as_json(json.loads(out)) as scrape:
                code, full_out, _ = run(
                    "count", "--from-json", scrape, "--json",
                )
                with as_json(json.loads(full_out)) as full:
                    with as_txt(
                        '{"Sheet A": ["Alpha"], '
                        '"Sheet B": ["Beta"]}'
                    ) as wanted:
                        code, filt_out, _ = run(
                            "count", "--from-json", scrape,
                            "--json", "--sheets", wanted,
                        )
                        with as_json(
                            json.loads(filt_out)
                        ) as filt:
                            code, out, _ = run(
                                filt, full, "Sheet A",
                                "Sheet B",
                                script="reconcile.py",
                            )
                            lines = out.splitlines()
                            ok = check(
                                "reconcile exits clean",
                                code == 0
                                and lines[-1] == "RECONCILED",
                                ok,
                            )
                            ok = check(
                                "reconcile prints months",
                                "2026-01: 2+3=5 vs 5 ok"
                                in lines
                                and "2026-02: 2+3=5 vs 5 ok"
                                in lines, ok,
                            )
                        data = json.loads(filt_out)
                        data["data"] = [
                            row for row in data["data"]
                            if row["title"] != "Sheet B"
                        ]
                        with as_json(data) as tampered:
                            code, out, _ = run(
                                tampered, full, "Sheet A",
                                "Sheet B",
                                script="reconcile.py",
                            )
                            ok = check(
                                "reconcile refuses mismatch",
                                code != 0
                                and "MISMATCH" in out, ok,
                            )
        code, _, _ = run(script="reconcile.py")
        ok = check("reconcile needs args", code == 2, ok)
    return ok


def check_filters(ok, scrape_file):
    code, walk_out_now, walk_err = run(ROOT, script="walk.py")
    ok = check(
        "walk quiet by default",
        code == 0 and "[" not in walk_err, ok,
    )
    with as_txt(walk_out_now) as walk_file:
        code, props, fuzz_err = run(
            TITLES, walk_file, script="fuzz.py"
        )
        ok = check(
            "fuzz quiet by default",
            code == 0 and "[" not in fuzz_err, ok,
        )
        with as_txt(props) as props_file:
            code, sieve_out, sieve_err = run(
                props_file, walk_file, script="sieve.py"
            )
            ok = check(
                "sieve timer on stderr",
                code == 0 and "files in" in sieve_err, ok,
            )
            ok = check(
                "sieve quiet by default", "[" not in sieve_err, ok,
            )
            ok = check(
                "stale title warns",
                "WARNING: Stale Prior Title: "
                "0 of 1 files kept" in sieve_err, ok,
            )
            ok = check(
                "sieve human output",
                code == 0 and "files" in sieve_err
                and "Jan 26.xlsx" in sieve_err, ok,
            )
            ok = check(
                "sieve stdout stays machine JSON",
                code == 0 and bool(json.loads(sieve_out)), ok,
            )

            code, out, err = run(
                "count", "--from-json", scrape_file, "--json",
            )
            ok = check("timer on stderr", "files in" in err, ok)
            ok = check("count quiet by default", "[" not in err, ok)

            code, _, prog_err = run(
                "count", "--from-json", scrape_file, "--progress",
            )
            ok = check(
                "count progress heartbeat",
                code == 0 and "[1/" in prog_err and "s]" in prog_err,
                ok,
            )

            code, plain_stdout, plain_count = run(
                "count", "--from-json", scrape_file
            )
            ok = check(
                "count human output",
                code == 0 and "rows" in plain_count, ok,
            )
            ok = check(
                "count stdout stays machine-clean",
                plain_stdout == "", ok,
            )
    return ok


def check_cache(ok, scrape_file, fresh_out):
    with as_txt("", suffix=".jsonl") as cache:
        code, cold_out, _ = run(
            "count", "--from-json", scrape_file,
            "--json", "--cache", cache,
        )
        ok = check(
            "cache cold run matches fresh",
            code == 0 and cold_out == fresh_out, ok,
        )
        code, warm_out, warm_err = run(
            "count", "--from-json", scrape_file,
            "--json", "--cache", cache,
        )
        ok = check(
            "cache warm run matches fresh",
            code == 0 and warm_out == fresh_out, ok,
        )
        ok = check(
            "cache warm run opens nothing",
            "(0 opened)" in warm_err, ok,
        )
        with open(cache, "a") as handle:
            handle.write("not json\n")
        code, trunc_out, _ = run(
            "count", "--from-json", scrape_file,
            "--json", "--cache", cache,
        )
        ok = check(
            "cache corrupt tail discarded",
            code == 0 and trunc_out == fresh_out, ok,
        )
        with open(cache) as handle:
            cache_lines = handle.read().splitlines()
        entry = json.loads(cache_lines[0])
        entry["mtime"] = 0
        cache_lines[0] = json.dumps(entry)
        entry = json.loads(cache_lines[1])
        entry["v"] = 999
        cache_lines[1] = json.dumps(entry)
        with open(cache, "w") as handle:
            handle.write("\n".join(cache_lines) + "\n")
        code, stale_out, stale_err = run(
            "count", "--from-json", scrape_file,
            "--json", "--cache", cache,
        )
        ok = check(
            "cache stale records reopen",
            code == 0 and stale_out == fresh_out
            and "(0 opened)" not in stale_err, ok,
        )
    return ok


def check_counts(ok, claims):
    got = [
        (row["title"], row["month"], row["rows"])
        for row in claims["data"]
    ]
    ok = check("exact month counts", got == COUNTS, ok)
    ok = check(
        "stale title absent from counts",
        "Stale Prior Title" not in {
            row["title"] for row in claims["data"]
        }, ok,
    )

    jan = claims["data"][0]
    ok = check(
        "sources kept",
        jan["sources"] == [
            P(ACME, "Copy of JAN report 26.xlsx"),
            P(ACME, "Jan 26.xlsx"),
            P(ACME, "jan-report 26.xlsx"),
            P(ACME, "reissue", "Jan 26.xlsx"),
        ], ok,
    )

    apr = P(ACME, "Apr 26.xlsx")
    ok = check(
        "dateless and multi-sheet flagged",
        set(claims["errors"]) == FLAGGED
        and "sheets" in claims["errors"][apr], ok,
    )
    return ok


def check_dupes(ok, claims):
    cases = [
        (
            P(ACME, "reissue", "Jan 26.xlsx"),
            "same name as", "same name flagged",
        ),
        (P(MISC, "Mar 26.xlsx"), "near-dupe of", "near-dupe flagged"),
        (
            P(ACME, "jan-report 26.xlsx"),
            "possible dupe of", "possible dupe flagged",
        ),
        (
            P(MISC, "Report Apr 26.xlsx"),
            "paren variant of", "paren variant flagged",
        ),
    ]
    for path, want, name in cases:
        ok = check(
            name, want in claims["errors"].get(path, ""), ok,
        )
    return ok


def check_files(ok, claims):
    apr_pdf = P(ACME, "4.1.26.pdf")
    apr = P(ACME, "Apr 26.xlsx")
    apr_row = next(
        row for row in claims["data"]
        if row["title"] == "Acme Corp Claim"
        and row["month"] == "2026-04"
    )
    ok = check(
        "pdf anchors merge into month",
        apr_row["rows"] == 8
        and apr_row["sources"] == [apr_pdf, apr], ok,
    )

    jun_row = next(
        row for row in claims["data"]
        if row["title"] == "Harbor View Medical"
        and row["month"] == "2026-06"
    )
    ok = check(
        "pdf decoys excluded",
        jun_row["rows"] == 4
        and jun_row["sources"] == [P(MISC, "6.11.2026.pdf")],
        ok,
    )

    empties = [
        (
            P(MISC, "Stray-empty Jul 26.pdf"),
            "empty pdf", "empty pdf flagged",
        ),
        (
            P(MISC, "Empty-note Jul 26.xlsx"),
            "empty workbook", "empty workbook flagged",
        ),
        (
            P(ACME, "Mar 2025.xlsx"), "year 2025",
            "non-2026 year flagged",
        ),
        (
            P(MISC, "lost 26.pdf"),
            "no month in filename",
            "dateless unreadable reports no month",
        ),
    ]
    for path, want, name in empties:
        ok = check(name, claims["errors"].get(path) == want, ok)

    bogus = P(ACME, "Bogus Jun 26.xlsx")
    ok = check(
        "unreadable file kept in errors",
        bogus in claims["errors"], ok,
    )

    feb_pruned = P(ACME, "Copy of Feb 26.xlsx")
    feb_row = next(
        row for row in claims["data"]
        if row["title"] == "Acme Corp Claim"
        and row["month"] == "2026-02"
    )
    ok = check(
        "copy-prune holds single feb",
        feb_row["rows"] == 6 and feb_pruned not in feb_row["sources"],
        ok,
    )
    return ok


def check_pivot(ok, claims):
    head = "\t".join(
        ["Title", "Missing", "Jan", "Feb", "Mar", "Apr",
         "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Totals"]
    )
    acme = ["3", "11", "6", "0", "8", "0", "4",
            "0", "5", "3", "4", "41"]
    harbor = ["5", "0", "0", "8", "5", "2", "4",
              "3", "0", "0", "0", "22"]
    port = ["7", "0", "0", "7", "3", "4", "0",
            "0", "0", "0", "0", "14"]
    want = [
        head,
        "\t".join(["Acme Corp Claim"] + acme),
        "\t".join(["Harbor View Medical"] + harbor),
        "\t".join(["Portside Dental"] + port),
    ]
    with as_json(claims) as claims_file:
        code, out, pivot_err = run(
            "pivot", "--from-json", claims_file
        )
        ok = check("pivot TSV exact", out.splitlines() == want, ok)
        ok = check(
            "pivot prints only the table",
            code == 0 and pivot_err == "", ok,
        )
    return ok, (acme, harbor, port)


def check_sheet(ok, claims):
    with as_json(claims) as sheet_file:
        code, out, _ = run(
            "pivot", "--from-json", sheet_file, "--by-sheet",
        )
        sheet_lines = out.splitlines()
        sheet_head = "\t".join(
            ["Title", "File", "Sheet", "Missing", "Jan",
             "Feb", "Mar", "Apr", "May", "Jun", "Jul",
             "Aug", "Sep", "Oct", "Totals"]
        )
        ok = check(
            "sheet pivot header exact",
            code == 0 and sheet_lines[:1] == [sheet_head], ok,
        )
        month_keys = [f"2026-{m:02d}" for m in range(1, 11)]
        sheet_cells = {}
        apr_sheets = {}
        for line in sheet_lines[1:]:
            parts = line.split("\t")
            title, base, sheet = parts[0], parts[1], parts[2]
            for key, cell in zip(month_keys, parts[4:14]):
                sheet_cells[(title, key)] = sheet_cells.get(
                    (title, key), 0
                ) + int(cell)
            if title == "Acme Corp Claim" and base == "Apr 26.xlsx":
                apr_sheets[sheet] = int(parts[7])
        file_cells = {}
        for row in claims["data"]:
            file_cells[(row["title"], row["month"])] = row["rows"]
        present = {
            key: value for key, value in sheet_cells.items() if value
        }
        ok = check(
            "sheet rows sum to file rows [consistency]",
            present == file_cells, ok,
        )
        ok = check(
            "april sheets split 2 and 3",
            apr_sheets == {"Sheet": 2, "Sheet1": 3}, ok,
        )
    return ok


def check_order(ok, claims, want):
    acme, harbor, port = want
    with as_txt(
        "Portside Dental\nGhost Title\nAcme Corp Claim\n"
    ) as order_path:
        zeros = ["0"] * 10
        want_ordered = [
            "\t".join(["Portside Dental"] + port),
            "\t".join(["Ghost Title", "10"] + zeros + ["0"]),
            "\t".join(["Acme Corp Claim"] + acme),
            "\t".join(["Harbor View Medical"] + harbor),
        ]
        with as_json(claims) as claims_file:
            code, out, _ = run(
                "pivot", "--from-json", claims_file,
                "--order", order_path,
            )
            ok = check(
                "pivot order exact",
                out.splitlines() == want_ordered, ok,
            )
    with as_txt(
        "Acme Corp Claim\nAcme Corp Claim\n"
    ) as order_path:
        with as_json(claims) as claims_file:
            code, out, _ = run(
                "pivot", "--from-json", claims_file,
                "--order", order_path,
            )
            rows = out.splitlines()
            ok = check(
                "pivot order dedupes",
                code == 0 and rows.count(rows[0]) == 1
                and len(rows) == len(set(rows)), ok,
            )
    return ok


def check_walk(ok):
    code, first, first_err = run(ROOT, script="walk.py")
    lines = first.splitlines()
    ok = check("walk exits clean", code == 0, ok)
    # Bare paths, no tabs (pinned below), so path order
    # is line order; one sorted check covers both.
    ok = check(
        "walk stdout sorted by path",
        code == 0 and lines == sorted(lines), ok,
    )
    ok = check(
        "walk stderr counts lines",
        code == 0 and "lines in" in first_err, ok,
    )
    ok = check(
        "walk marks dirs, lists files",
        all(line and "\t" not in line for line in lines)
        and any(line.endswith("/") for line in lines), ok,
    )
    code, second, _ = run(ROOT, script="walk.py")
    ok = check(
        "walk rerun byte-identical",
        code == 0 and second == first, ok,
    )
    return ok, first


def check_heartbeat_reset(ok):
    from normalization import heartbeat, reset_heartbeat
    heartbeat(1, None, "warmup")
    reset_heartbeat()
    ok = check(
        "heartbeat reset clears the clock",
        heartbeat.start is None, ok,
    )
    buf = io.StringIO()
    with redirect_stderr(buf):
        heartbeat(1, None, "x")
    ok = check(
        "heartbeat restarts after reset",
        heartbeat.start is not None
        and "[1," in buf.getvalue(), ok,
    )
    reset_heartbeat()
    return ok


def check_heartbeat_flush(ok):
    from normalization import heartbeat, reset_heartbeat
    reset_heartbeat()
    buf = FlushCount()
    with redirect_stderr(buf):
        heartbeat(1, None, "x")
    ok = check(
        "heartbeat flushes live",
        "[1," in buf.getvalue()
        and buf.flushes > 0, ok,
    )
    reset_heartbeat()
    return ok


def check_walk_tripwire(ok):
    import walk as walkmod
    old = walkmod.TRIPWIRE
    walkmod.TRIPWIRE = 2
    try:
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("a.txt", "b.txt"):
                open(os.path.join(tmp, name), "w").close()
            buf = io.StringIO()
            with redirect_stderr(buf):
                lines = snapshot(tmp)
            ok = check(
                "walk tripwire warns past threshold",
                len(lines) == 2
                and "WARNING" in buf.getvalue()
                and "100000" not in buf.getvalue(), ok,
            )
    finally:
        walkmod.TRIPWIRE = old
    ok = check("walk tripwire restores", walkmod.TRIPWIRE == old, ok)
    return ok


def check_walk_ignore(ok):
    import walk as walkmod
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, "keep"))
        os.makedirs(os.path.join(tmp, "test", "deep"))
        for rel in (
            "keep/a.txt", "test/b.txt",
            "test/deep/c.txt", "top.txt",
        ):
            open(os.path.join(tmp, rel), "w").close()
        base = slash(tmp)
        want = sorted([
            f"{base}/keep/",
            f"{base}/keep/a.txt",
            f"{base}/test/",
            f"{base}/top.txt",
        ])
        ok = check(
            "walk ignore skips the dir contents",
            walkmod.snapshot(tmp, ignore=("test",))
            == want, ok,
        )
        code, out, _ = run(
            tmp, "--ignore=test", script="walk.py",
        )
        ok = check(
            "walk --ignore matches the lib",
            code == 0 and out.splitlines() == want, ok,
        )
        code, out, _ = run(tmp, script="walk.py")
        ok = check(
            "walk default keeps everything",
            code == 0
            and f"{base}/test/b.txt" in out.splitlines()
            and f"{base}/test/deep/c.txt"
            in out.splitlines(), ok,
        )
    return ok


def check_walk_streams(ok):
    import walk as walkmod

    class FakeEntry:
        def __init__(self, name):
            self.name = name

        def is_dir(self, follow_symlinks=False):
            return False

    yields = []

    def gen():
        for name in ("a.txt", "b.txt", "c.txt"):
            yields.append(name)
            yield FakeEntry(name)

    class FakeScan:
        def __enter__(self):
            return gen()

        def __exit__(self, *exc):
            return False

    seen = []

    def progress(done, total, path):
        seen.append(len(yields))

    with mock.patch(
        "os.scandir", return_value=FakeScan()
    ):
        walkmod.snapshot("testdata", progress=progress)
    # Buffered (sorted-first) code consumes every yield
    # before the first progress: [3, 3, 3], never this.
    ok = check(
        "walk streams progress live",
        seen == [1, 2, 3], ok,
    )
    return ok


def check_fuzz_files(ok):
    # Filenames are invisible to fuzz: an exact filename
    # as title still null-seeds. Dirs only, by design.
    root = P("testdata", "Name Co")
    title = "Quarterly Summary"
    lines = (
        f"{root}/\n"
        f"{root}/{title}.xlsx\n"
    )
    with as_txt(lines) as walk_file:
        with as_txt(f"{title}\n") as titles_file:
            code, out, _ = run(
                titles_file, walk_file, script="fuzz.py",
            )
            ok = check(
                "fuzz ignores filenames",
                code == 0 and out.splitlines() == [
                    f"{title}\t-\t\t\tno match"
                ], ok,
            )
    return ok


def check_walk_out(ok):
    with as_txt("", suffix=".txt") as out_file:
        code, plain, err = run(
            ROOT, f"--out={out_file}", script="walk.py",
        )
        code2, want, _ = run(ROOT, script="walk.py")
        with open(out_file) as handle:
            listed = handle.read()
        ok = check(
            "walk --out matches stdout",
            code == 0 and code2 == 0 and plain == ""
            and listed == want and "lines in" in err, ok,
        )
    return ok


def check_walk_partial(ok):
    import walk as walkmod
    with tempfile.TemporaryDirectory() as tmp:
        with tempfile.TemporaryDirectory() as outdir:
            for i in range(12):
                open(
                    os.path.join(tmp, f"f{i:02d}.txt"),
                    "w",
                ).close()
            out = os.path.join(outdir, "walk.txt")

            def progress(done, total, path):
                if done > 10:
                    raise SystemExit(1)

            try:
                walkmod.snapshot(
                    tmp, progress=progress, out=out, batch=5,
                )
                interrupted = False
            except SystemExit:
                interrupted = True
            with open(out) as handle:
                kept = handle.read().splitlines()
            full = walkmod.snapshot(tmp)
            ok = check(
                "walk kill leaves the last full batch",
                interrupted and len(kept) == 10
                and all(kept)
                and set(kept) <= set(full), ok,
            )
    return ok


def check_stdio_survives(ok):
    # Lone surrogates encode nowhere strict: stdio()
    # escapes them, the run survives under any locale.
    with tempfile.TemporaryDirectory() as tmp:
        raw = os.path.join(
            os.fsencode(tmp), b"\xed\xa0\x8a Jan 26.xlsx",
        )
        open(raw, "w").close()
        code, out, _ = run(
            tmp, script="walk.py",
            env={"PYTHONIOENCODING": "ascii:strict"},
        )
        ok = check(
            "walk survives undecodable names",
            code == 0 and "Jan 26.xlsx" in out, ok,
        )
        with as_txt("", suffix=".txt") as out_file:
            code, plain, _ = run(
                tmp, f"--out={out_file}", script="walk.py",
                env={"PYTHONIOENCODING": "ascii:strict"},
            )
            with open(out_file) as handle:
                listed = handle.read()
            ok = check(
                "walk --out survives undecodable names",
                code == 0 and plain == ""
                and "Jan 26.xlsx" in listed, ok,
            )
    return ok


def check_fuzz(ok, walk_out):
    with as_txt(walk_out) as walk_handle:
        code, out, err = run(TITLES, walk_handle, script="fuzz.py")
        rows = [line.split("\t") for line in out.splitlines()]
        mapping = {row[0]: row[1] for row in rows}
        ok = check(
            "fuzz parity with match",
            code == 0 and mapping == {
                "Acme Corp Claim": P(ROOT, "Acme Corp Claim Files"),
                "Harbor View Medical": HARBOR,
                "Portside Dental": P(ROOT, "Portside Dentail LLC"),
                "Stale Prior Title": P(ROOT, "Stale Prior Title"),
            }, ok,
        )
        ok = check(
            "fuzz score rides in note column",
            any(
                len(row) == 5 and "85.71" in row[4] for row in rows
            ), ok,
        )
        ok = check("fuzz stderr counts matched", "matched" in err, ok)

        with as_txt("Nobody Here ZZ\n") as ghost_handle:
            code, out, _ = run(
                ghost_handle, walk_handle, script="fuzz.py",
            )
            ok = check(
                "fuzz null-seeds the unmatched",
                code == 0 and out.splitlines() == [
                    "Nobody Here ZZ\t-\t\t\tno match"
                ], ok,
            )

        with as_txt(
            "Acme Corp Claim\nAcme Corp Claim Files\n"
        ) as clash:
            code, _, err = run(clash, walk_handle, script="fuzz.py")
            ok = check(
                "fuzz flags shared-dir claims",
                code == 0 and "COLLISION:" in err, ok,
            )

        with as_txt(
            "Harbor View Medical\nHarbor Medical\n"
        ) as pair:
            code, out, err = run(pair, walk_handle, script="fuzz.py")
            mapping = {
                row[0]: row[1] for row in (
                    line.split("\t") for line in out.splitlines()
                )
            }
            ok = check(
                "fuzz poison pair shares best",
                code == 0 and mapping == {
                    "Harbor View Medical": HARBOR,
                    "Harbor Medical": HARBOR,
                } and "COLLISION:" in err, ok,
            )
    return ok


def check_sieve(ok, walk_out):
    with as_txt(walk_out) as walk_handle:
        code, props, _ = run(TITLES, walk_handle, script="fuzz.py")
        with as_txt(props) as props_handle:
            code, new_out, _ = run(
                props_handle, walk_handle, script="sieve.py",
            )
            ok = check("sieve exits clean", code == 0, ok)
            ok = check(
                "sieve stdout stays machine-clean",
                code == 0 and json.loads(new_out), ok,
            )
            code, again, _ = run(
                props_handle, walk_handle, script="sieve.py",
            )
            ok = check(
                "sieve rerun byte-identical", again == new_out, ok,
            )

        with as_txt("Ghost Title\t-\t\t\n") as ghost_cur:
            code, out, err = run(
                ghost_cur, walk_handle, script="sieve.py",
            )
            ok = check(
                "sieve null warns, never vanishes",
                code == 0 and "not mapped to any dir" in err
                and json.loads(out) == {}, ok,
            )

        cases = [
            (
                f"A\t{ACME}\t\t\nB\t{ACME}\t\t\n",
                "shared dir",
                "sieve refuses bare double-claim",
            ),
            (
                f"Top\t{HARBOR}\t\t\nDeep\t{MISC}\t\t\n",
                "nested dir",
                "sieve refuses nested overlap",
            ),
        ]
        for text, want, name in cases:
            with as_txt(text) as cur:
                code, _, err = run(
                    cur, walk_handle, script="sieve.py"
                )
                ok = check(
                    name, code != 0 and want in err, ok,
                )

        split_dir = P(ROOT, "Split Co")
        with as_txt(f"W\t{split_dir}\t\t\n") as whole:
            code, out, _ = run(whole, walk_handle, script="sieve.py")
            everything = set(json.loads(out)["W"][split_dir])
        with as_txt(
            f"Split A\t{split_dir}\tA\t\n"
            f"Split B\t{split_dir}\tB\t\n"
        ) as parts:
            code, out, _ = run(parts, walk_handle, script="sieve.py")
            got = json.loads(out)
            union = (
                set(got["Split A"][split_dir])
                | set(got["Split B"][split_dir])
            )
            ok = check(
                "sieve token rows partition the dir",
                code == 0 and union == everything
                and got["Split A"][split_dir]
                and got["Split B"][split_dir], ok,
            )
    return ok


def check_year_guard(ok):
    # 2026 must stand alone: longer digit runs never
    # pass the gate, dated neighbors still do. Packed
    # 8-digit dates pass bare; 6- and 10-digit runs
    # without that shape stay out.
    root = P("testdata", "Guard Co")
    dated = f"{root}/Item Jan 26.xlsx"
    packed = f"{root}/Item 09152026.xlsx"
    long = f"{root}/Item 120268.xlsx"
    deca = f"{root}/Item 1234567890.xlsx"
    lines = f"{dated}\n{packed}\n{long}\n{deca}\n"
    with as_txt(lines) as walk_file:
        with as_txt(f"Guard\t{root}\t\t\n") as cur:
            code, out, _ = run(
                cur, walk_file, script="sieve.py"
            )
            got = json.loads(out) if code == 0 else {}
            ok = check(
                "year guard stays bounded",
                code == 0
                and got.get("Guard", {}).get(root)
                == [packed, dated], ok,
            )
    return ok


def check_cached_month(ok):
    # Rename keeps the stamp but not the bucket: the
    # fresh month wins over the cached one. Content
    # never opens on a hit, so the file stays empty.
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "Feb 26.xlsx")
        open(path, "w").close()
        info = os.stat(path)
        line = json.dumps({
            "title": "T", "path": path,
            "month": "2026-01", "rows": 5,
            "flag": None,
            "sheets": [{"sheet": "S", "rows": 5}],
            "error": None, "mtime": int(info.st_mtime),
            "size": info.st_size, "v": LOGIC,
        }) + "\n"
        with as_txt(line, suffix=".cache") as cache:
            scrape = {"T": {tmp: [path]}}
            with as_json(scrape) as scrape_file:
                code, out, err = run(
                    "count", "--from-json", scrape_file,
                    "--json", "--cache", cache,
                )
                rows = [
                    (row["title"], row["month"],
                     row["rows"])
                    for row in json.loads(out)["data"]
                ]
                ok = check(
                    "fresh month wins over cached",
                    code == 0
                    and rows == [("T", "2026-02", 5)]
                    and "(0 opened)" in err, ok,
                )
    return ok


def check_audit(ok, walk_out):
    with as_txt(walk_out) as walk_file:
        code, props, _ = run(TITLES, walk_file, script="fuzz.py")
        with as_txt(props) as props_handle:
            code, out, _ = run(
                props_handle, walk_file, script="sieve.py",
            )
            with as_json(json.loads(out)) as scrape_file:
                code, report, _ = run(
                    walk_file, scrape_file, script="audit.py",
                )
                ok = check(
                    "audit exits clean", code == 0, ok,
                )
                ok = check(
                    "audit finds zero keepable on testdata",
                    code == 0
                    and "KEEPABLE: 0" in report
                    and "*** INVESTIGATE ***" not in report,
                    ok,
                )
                code, drift, _ = run(
                    walk_file, scrape_file, scrape_file,
                    script="audit.py",
                )
                ok = check(
                    "audit self-diff zero drift [smoke]",
                    code == 0
                    and "doubled: 0" in drift
                    and "dropped: 0" in drift
                    and "added: 0" in drift, ok,
                )
                with as_txt(
                    format_scrape(json.loads(out))
                ) as dump:
                    code, redrift, _ = run(
                        walk_file, scrape_file, dump,
                        script="audit.py",
                    )
                    ok = check(
                        "audit reads human dumps [smoke]",
                        code == 0
                        and "doubled: 0" in redrift
                        and "dropped: 0" in redrift
                        and "added: 0" in redrift, ok,
                    )
                new = json.loads(out)
                kept = sorted(
                    path for groups in new.values()
                    for paths in groups.values()
                    for path in paths
                )
                old = {
                    title: {
                        root: list(paths)
                        for root, paths in groups.items()
                    }
                    for title, groups in new.items()
                }
                dup = kept[0]
                extra = P(ACME, "Extra Jan 26.xlsx")
                dateless = P(MISC, "random notes.xlsx")
                old["Dupe A"] = {ACME: [dup, extra, dateless]}
                with as_json(new) as new_file:
                    with as_json(old) as old_file:
                        code, drift, _ = run(
                            walk_file, new_file, old_file,
                            script="audit.py",
                        )
                        ok = check(
                            "audit names doubled paths",
                            code == 0 and "doubled: 1" in drift
                            and f"  {dup} <- " in drift, ok,
                        )
                        ok = check(
                            "audit counts dropped",
                            code == 0 and "dropped: 2" in drift,
                            ok,
                        )
                        ok = check(
                            "audit verdicts keepable drop",
                            code == 0
                            and "keepable (2026-01)" in drift,
                            ok,
                        )
                        ok = check(
                            "audit verdicts gated drop",
                            code == 0
                            and "gated: no 2026 token" in drift,
                            ok,
                        )
    return ok


@contextmanager
def as_pipeline():
    # Full legs once: walk text plus the count pipeline's
    # scrape file, parsed claims, and fresh stdout. Quiet
    # and progress suites rerun legs themselves, since
    # they assert on fresh stderr.
    walk_out = walk_text()
    with as_txt(walk_out) as walk_file:
        _, props, _ = run(TITLES, walk_file, script="fuzz.py")
        with as_txt(props) as props_file:
            _, out, _ = run(
                props_file, walk_file, script="sieve.py",
            )
            with as_json(json.loads(out)) as scrape_file:
                _, out, _ = run(
                    "count", "--from-json", scrape_file,
                    "--json",
                )
                yield walk_out, scrape_file, json.loads(out), out


def main():
    ok = True
    ok = check_usage(ok)
    ok = check_clean(ok)
    ok = check_progress(ok)
    ok = check_auto_walk(ok)
    ok = check_auto_sieve(ok)
    ok = check_auto_gate(ok)
    ok = check_auto_pivot(ok)

    with as_pipeline() as (walk_out, scrape_file, claims, fresh):
        ok = check_split(ok, walk_out)
        ok = check_sheet_split(ok, walk_out)
        ok = check_sheet_count(ok, walk_out)
        ok = check_strip(ok, walk_out)
        ok = check_reconcile(ok, walk_out)
        ok = check_audit(ok, walk_out)
        ok = check_filters(ok, scrape_file)
        ok = check_cache(ok, scrape_file, fresh)
        ok = check_counts(ok, claims)
        ok = check_dupes(ok, claims)
        ok = check_files(ok, claims)
        ok, want = check_pivot(ok, claims)
        ok = check_sheet(ok, claims)
        ok = check_order(ok, claims, want)

    ok, walk_out = check_walk(ok)
    ok = check_heartbeat_reset(ok)
    ok = check_heartbeat_flush(ok)
    ok = check_walk_tripwire(ok)
    ok = check_walk_ignore(ok)
    ok = check_walk_streams(ok)
    ok = check_fuzz_files(ok)
    ok = check_stdio_survives(ok)
    ok = check_walk_out(ok)
    ok = check_walk_partial(ok)
    ok = check_fuzz(ok, walk_out)
    ok = check_sieve(ok, walk_out)
    ok = check_year_guard(ok)
    ok = check_cached_month(ok)

    # Totals always print: a mid-suite crash leaves no
    # total, which reads as red, never green.
    print("")
    print(f"PASS {len(PASSED)}, FAIL {len(FAILED)}")
    if FAILED:
        print(f"*** {len(FAILED)} FAILURES ***")
        for name in FAILED:
            print(f"*** FAIL: {name}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
