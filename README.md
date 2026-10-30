# claims-recon

Deterministic pipeline: a drive of workbooks and PDFs in, an
audited monthly claims report out.

## Problem

Given a drive of workbooks and PDFs, a template of master
titles, and a mapping from each title to its directories,
filenames, and sheets: report claim rows per title per month,
with a reason for every file and sheet count skips, except
pruned copies and sieve-gated files, which tally only in
aggregate (sieve warnings, audit orphan counts).

See [DECISIONS.md](DECISIONS.md) for the design decisions
behind the pipeline, including the roads not taken.

## Setup

Bare `python` (`py` on Windows), 3.12+. `walk`, `fuzz`,
and `sieve` need only stdlib plus `rapidfuzz`. `count`
additionally needs `pypdf`, `python-calamine`
(`openpyxl` is only for `gen_testdata.py`):

```
pip install openpyxl pypdf python-calamine rapidfuzz
```

## Workflow

Tools run as `python <tool> …` from the repo root
(bare names below).

```
walk <root> > walk.txt                  # 2> line count
fuzz titles.txt walk.txt > proposals.txt
# human pass: proposals.txt -> curated.txt
sieve curated.txt walk.txt > scrape.json
python audit.py walk.txt scrape.json   # orphans reconcile
python main.py count --from-json scrape.json --json --cache count.cache > count.json
python main.py pivot --from-json count.json
```

The human pass is mandatory, not optional: `fuzz`
matches directory names only, never filenames, and
master titles lie — misspellings (`Dentail`), slashes
vs spaces, half-remembered report words that exist
nowhere on disk, nested dirs, multi-sheet files. Read
every proposal against the disk strings, derive tokens
from filenames as found, and freeze `curated.txt`: it
is the only hand-edited artifact in the pipeline, and
every later stage derives from it. Pay the manual tax
once, early; everything downstream is mechanical.

`cmp walk.txt <(walk root)` answers staleness. Walk,
fuzz, sieve, count, and auto take `--progress` for a
heartbeat (first, then every 50th). `count --cache`
memoizes opens (see `count.cache` below); seeded runs
match fresh byte-identical. `count`
and `pivot` live in `main.py` — both accept `scrape.json`
from either `sieve` or `auto`, which share the schema.

Sheet split (optional legs): `sieve --sheets sheets.json`
writes `{title: [names]}` for sheet-scoped titles only
(absent means unfiltered); `count --sheets sheets.json`
sums listed sheets per title, missing names error loud.

One command from curated on (`--sheets`, `--cache`,
`--order`, `--by-sheet` optional; curation stays manual,
missing file refuses, nonzero `KEEPABLE` stops it):

```
python main.py auto --root <root> --curated curated.txt --sheets sheets.json --cache count.cache
```

Live runbook: fixed artifact names per run, overwrite
instead of versioning. Walk needs its stderr receipt
(`N lines in Ns`) or the listing is suspect. Paste only
after Totals reconcile (filtered A+B = unfiltered);
matching unfiltered rows are the control, not the
result. `Missing 10` must match sieve warnings 1:1
(re-checkable any time). Read error signatures before
opening pivots. `reconcile.py` proves filtered A+B
against unfiltered before pasting.
Hostile drives: ignore attics, walk with `--out`,
year-token census per attic, `grep` filenames
(`fuzz` matches dirs only), token-split curated rows,
disjointness check per `scrape.json`; zero resolves
with receipts is a null report, not a failure.

## Demo

`gen_testdata.py` builds `testdata/`: real Excel + PDF
files with known counts (`testdata/titles.txt` is
committed as the bootstrap sentinel; everything else in
`testdata/` is generated, not tracked). The demo needs no
curation — `fuzz` proposes every title, so the whole flow
runs as-is. Treat that tidiness as the exception: on
live drives the human pass is mandatory (see Workflow).

```sh
python gen_testdata.py
python walk.py testdata > walk.txt
python fuzz.py testdata/titles.txt walk.txt > curated.txt
python sieve.py curated.txt walk.txt > scrape.json
python main.py count --from-json scrape.json
```

`Portside Dental` proposes at 85.71 on purpose, to show a
non-100 score above threshold (it rides in the note
column). `python checks.py` runs the full suite: walk,
fuzz, sieve, count, audit and auto behavior, strips,
splits, reconcile, exact month counts, sources, and
every flag tier.

## Artifacts

- `walk.txt`: bare paths sorted by path, `dir/`
  entries for dirs. Machine-owned, never hand-edited.
  `--ignore=name` (repeatable) omits that dirname's
  contents at any depth; the dir entry stays.
  `--out=file` checkpoints every 10000 lines (atomic
  replace, final write sorted); keep it outside the
  walked root. A kill leaves the last full batch.
- `curated.txt`: source of truth, hand-owned. One claim
  per line, titles-file order:
  `title\tdir\tcontains\tsheets\tnote`. Empty field =
  unscoped, `-` dir = explicitly unmapped (warns).
  `sheets` is comma-separated exact names
  (`Alpha,Beta`); empty means unfiltered. `sieve`
  exempts all-sheet-scoped shared dirs and writes the
  `--sheets` sidecar; `count --sheets` sums listed
  sheets only. Fields strip ends-only on read, so
  padding merges loud instead of mismatching silent.
  The note column carries scores and
  lingers harmlessly. Pay the manual tax here, once,
  early: no later stage takes human input.
- `scrape.json`: `{title: {dir: [paths]}}`. Token- or
  sheet-scoped sharing never collides. Partitions
  reconcile (A + B == combined).
- `count.json`: `{data: [{title, month, rows, sources,
  sheets}], errors: {path: reason}}`, months are
  `YYYY-MM`. Sheet rows always sum back to the file-mode
  cells.
- `count.cache`: one JSON record per opened file,
  appended and flushed as completed. Disposable;
  regenerates from a cold run.
- `pivot` prints the paste-over matrix (`Title`,
  `Missing`, `Jan`…`Dec`, `Totals`) as TSV from
  `count.json`; pipe it to your clipboard and paste over
  the template. `--order titles.txt`
  follows template row order (missing zero-fill, unknown
  appended). `--by-sheet` prints one row per file sheet
  (`Title`, `File`, `Sheet`, months) instead. Generated,
  don't curate.
- Every path uses forward slashes (`/mnt/drive/...`), even
  on Windows: paste-safe, no backslash escaping in JSON.
- One aggregation is one folder: `titles.txt` in, artifacts
  out. Reruns stay comparable because listings are sorted
  and deterministic.
- Not yet: per-title relist keys.

## Flags

Counted (summed): `same name as`, `near-dupe of`,
`paren variant of`, `possible dupe of`, `N sheets`.
Listed at 0 rows: `empty workbook`, `empty pdf`.
Skipped, never counted: `no month in filename`,
`year XXXX`, unreadable files (reason is the error).
Sheet-filtered title: unlisted sheets uncounted;
listed-but-absent names `missing sheet X` in errors.

## Rules

- Header is the first non-empty row; the rest hold data.
- Totals rows count. Month-first: names, `M.D.YY`,
  `M.D.YYYY` (day ignored), `YYYY-M`, `M-YYYY`, ISO
  `2026-05`, REV `4-2026`, hyphen-suffixed PDF anchors,
  packed `MMDDYYYY`/`YYYYMMDD`. Anything else is dateless.
- PDFs count whitespace-bounded 9-digit anchors, one per row.
- Documented overcounts, no warning (detection is as hard
  as correction): stacked tables, far stray notes.

## Failure modes

- Missing args: every tool prints usage, exit 2.
- `count --from-json` fed human text: exits naming the
  file, with a `--json` hint (upstream ran without
  `--json`).
- One dir claimed by two titles: `COLLISION:` warning in
  `fuzz`, hard `shared dir` failure in `sieve` — unless
  every claimant scopes by `contains` token or exact
  `sheets` name (same-dir splits never double-count by
  construction). Shared sheet names fail loud as
  `shared sheet`. Nested dirs across titles fail loud
  as `nested dir`.
- Title with nothing kept: `WARNING:` in `sieve`
  (`not mapped to any dir` means unmapped; `0 of N` kept
  means files outside the tracked year; `no files found`
  means bad dir). A token matching zero files warns per
  claim.
- One bad file never fails `count`; see `errors`.

## License

MIT — see [LICENSE](LICENSE).
