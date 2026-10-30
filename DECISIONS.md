# Engineering Decisions

The notable roads *not* taken, and why. Each entry: the
situation, the decision, the consequences. Several are pinned
by tests in `checks.py`; per project policy, reversing a pinned
decision means replacing its pin, never silently dropping it.

## 1. The human pass is mandatory, and happens once, early

**Situation:** Master title lists lie. They contain misspellings
(`Dentail`), slash-vs-space variants, half-remembered report
words that exist nowhere on disk, and titles spanning nested
dirs and multiple sheets. Trusting a fully automatic matcher
meant silent miscounts in a downstream financial report.

**Decision:** `fuzz` only *proposes* (fuzzy directory-name
matching, score attached). A human curates `curated.txt` — the
single hand-edited artifact in the system — and every later
stage is a mechanical function of it. No stage after curation
accepts human input; `auto` refuses to run if `curated.txt` is
missing rather than guessing.

**Consequences:** The manual tax is paid once, up front.
Everything downstream is deterministic and auditable. The
trade is explicit: curation speed is bounded by human
attention, so the pipeline makes curation cheap (proposals
with scores, disk strings beside them) rather than trying to
eliminate it.

## 2. Fuzzy matching proposes directories only, never filenames

**Situation:** After triage on a drive where claim titles
appeared inside filenames scattered under junk directories,
extending the proposer to match filenames too was proposed.

**Decision:** Rejected, on four independent grounds:

1. Exact substring search already covers the use case —
   instantly and transparently (`grep`/`findstr`), with no
   code to maintain.
2. Fuzzy *filename* scoring is inexact, unexplainable to an
   auditor, and O(n²) over hundreds of thousands of files.
3. Every filename hit still needs a proposed directory, and
   scattered hits force either row explosion or a silent
   wrong pick — exactly the judgment call the human pass
   exists to make.
4. Auto-suggested match tokens invite rubber-stamping, which
   defeats the purpose of requiring human curation at all.

Pinned by the `fuzz ignores filenames` test.

## 3. Exact parsing beats clever parsing

**Situation:** Counting claim rows requires resolving a month
from each filename — in at least ten coexisting dialects
(`Jan-26`, `4.1.26`, ISO `2026-05`, REV `4-2026`, packed
`MMDDYYYY`/`YYYYMMDD`, PDF numeric anchors) — plus counting
rows inside workbooks and PDFs.

**Decision:** One explicit regex dialect table. Dataframe
libraries and heuristic/ML extraction were both rejected:
exact matching is simpler, fully explainable per row, and
faster (row counting runs on `python-calamine`, ~10x over
pure-Python parsing). Files whose names match no dialect are
*dateless*: listed at zero rows with a reason, never dropped
silently.

**Consequences:** Two known overcount classes (stacked tables,
far-flung stray notes) are documented rather than "fixed" —
detecting them reliably is as hard as correcting them, and a
documented bias is auditable while a heuristic one is not.

## 4. No similarity score bands, no threshold-lowering

**Situation:** The fuzzy matcher's scores invite automation:
"count anything scoring 90+ automatically."

**Decision:** Rejected. Score bands are inexact, unexplainable
per row, and O(n²) to tune. Lowering thresholds to catch
renamed entities is a junk magnet. The score instead rides
along in a note column where a human can see it.

## 5. Dialects that can't be distinguished stay out

**Situation:** `MM.DD` without a year looked like a missing
format.

**Decision:** Rejected after census: plain sequence IDs wear
exactly the same clothes, so admitting the dialect would
misdate ID numbers as months. Files stay listed (at zero
rows, with the reason).

## 6. No micro-tools; observability lives in the artifacts

**Situation:** Tempting to add `inventory`, `peek`, `trace`,
`diff` subcommands for debugging.

**Decision:** Rejected as overkill: every stage already writes
human-readable receipts to stderr (machine-clean data on
stdout), and each artifact is plain text/JSON — trivially
grep-able, diffable, and re-inspectable after the fact. One
exception earned its place: `reconcile.py`, because in the
target operator environment ad-hoc set-diffing at the keyboard
isn't available; an artifact-backed failsafe there is
evidence, not preference.

## 7. Determinism is part of the spec

Sorted directory listings, fixed artifact names per run
(overwrite, don't version), golden fixtures with known row
counts, and a memoized cache whose seeded run must be
*byte-identical* to a cold run. Reruns are comparable with
`cmp`; drift is detectable, not debatable.

## 8. Fail loud, or don't fail at all

One directory claimed by two titles → hard refusal (unless
both claims provably partition the files by token or exact
sheet name). Nested dirs across titles → refusal.
Listed-but-absent sheet names → loud error. Trailing padding
in curated rows → merges loudly instead of mismatching
silently. One bad file, however, never aborts a count run —
it lands in the `errors` map with its reason. An audit gate
blocks report output until every walked file is reconciled
to zero orphans.

## 9. Derived artifacts are disposable; hand-owned ones are
protected

`count.cache` regenerates from a cold run. `walk.txt` is
machine-owned and never hand-edited. `curated.txt` gets a
backup written before any automated stage touches it, and
stages refuse (rather than proceed) when it's absent.

## 10. Deferred on purpose

Glued-month filenames, `(1)` / `- Copy` duplicate markers,
stdin title input, per-title relist keys (to cut warm-cache
runs that are stat-bound), and threaded `--jobs`. Each has a
recorded re-open trigger: build only when the friction
recurs and is measured.
