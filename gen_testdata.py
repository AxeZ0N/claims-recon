"""Regenerate fixture workbooks with known content."""

import os
import sys

from openpyxl import Workbook

ROOT = "testdata"
KEEP = "titles.txt"
TITLES = [
    "Acme Corp Claim",
    "Harbor View Medical",
    "Portside Dental",
    "Stale Prior Title",
]
HEADERS = ["Name", "Amount"]

ACME = os.path.join("Acme Corp Claim Files", "2026")
HARBOR = "Harbor View Medical"
MISC = os.path.join(HARBOR, "misc")
DEEP = os.path.join(MISC, "deep")
PORT = os.path.join("Portside Dentail LLC", "2026")
STALE = "Stale Prior Title"
SPLIT = "Split Co"
SHEET = "Sheet Co"

# Relpath to per-sheet data-row counts.
FILES = {
    os.path.join(ACME, "Jan 26.xlsx"): [4],
    os.path.join(ACME, "Copy of JAN report 26.xlsx"): [2],
    os.path.join(ACME, "jan-report 26.xlsx"): [3],
    os.path.join(ACME, "reissue", "Jan 26.xlsx"): [2],
    os.path.join(ACME, "Feb 26.xlsx"): [6],
    os.path.join(ACME, "Copy of Feb 26.xlsx"): [6],
    os.path.join(ACME, "Copy of lost.xlsx"): [3],
    os.path.join(ACME, "Apr 26.xlsx"): [2, 3],
    os.path.join(ACME, "09152026.xlsx"): [3],
    os.path.join(ACME, "20261015.xlsx"): [4],
    os.path.join(ACME, "8.12.2026.xlsx"): [5],
    os.path.join(ACME, "Mar 2025.xlsx"): [4],
    os.path.join(HARBOR, "stray 2026 notes.xlsx"): [4],
    os.path.join(MISC, "Mar 26.xlsx"): [5],
    os.path.join(MISC, "Report (final) Apr 26.xlsx"): [2],
    os.path.join(MISC, "Report Apr 26.xlsx"): [3],
    os.path.join(MISC, "Copy  of Mar 26.xlsx"): [3],
    os.path.join(MISC, "summary 26.xlsx"): [2],
    os.path.join(MISC, "Empty-note Jul 26.xlsx"): [],
    os.path.join(MISC, "2026-05.xlsx"): [2],
    os.path.join(DEEP, "count 26 pcs.xlsx"): [3],
    os.path.join(PORT, "march.xlsx"): [7],
    os.path.join(PORT, "XYZ for May 02.xlsx"): [4],
    os.path.join(PORT, "4-2026.xlsx"): [3],
    # Prior-year only: scrape keeps nothing, warns.
    os.path.join(STALE, "Jan 2025.xlsx"): [4],
    # A/B token split: same dir, disjoint filenames.
    os.path.join(SPLIT, "Item A Jan 26.xlsx"): [2],
    os.path.join(SPLIT, "Item B Jan 26.xlsx"): [3],
}

# Sheet split: same files, disjoint sheet names. Inert
# until temp curated rows claim them (Split-Co shape).
SHEETS = {
    os.path.join(SHEET, "Shared Jan 26.xlsx"): [
        ("Alpha", 2),
        ("Beta", 3),
    ],
    os.path.join(SHEET, "Shared Feb 26.xlsx"): [
        ("Alpha", 2),
        ("Beta", 3),
    ],
}

# Read but never counted: no year token in the name.
DECOYS = [
    os.path.join(MISC, "readme.txt"),
    os.path.join(MISC, "random notes.xlsx"),
]

# Passes the scrape gate, then fails to read: one bad file
# never kills the run.
GARBAGE = {
    os.path.join(ACME, "Bogus Jun 26.xlsx"): b"not a workbook",
    os.path.join(MISC, "lost 26.pdf"): b"not a document",
}


def make_workbook(path, counts):
    book = Workbook()
    for i, n in enumerate(counts):
        sheet = book.active if i == 0 else book.create_sheet()
        sheet.append(HEADERS)
        for r in range(n):
            sheet.append([f"row {r + 1}", (r + 1) * 10])
    book.save(path)


def make_named_workbook(path, pairs):
    # Same rows as above; sheet names pinned so two
    # titles can split one file by exact name later.
    book = Workbook()
    for i, (name, n) in enumerate(pairs):
        sheet = book.active if i == 0 else book.create_sheet()
        sheet.title = name
        sheet.append(HEADERS)
        for r in range(n):
            sheet.append([f"row {r + 1}", (r + 1) * 10])
    book.save(path)


def make_stacked(path):
    # Second table rides along: documents the overcount.
    book = Workbook()
    sheet = book.active
    sheet.append(HEADERS)
    sheet.append(["row 1", 10])
    sheet.append(["row 2", 20])
    sheet.append([])
    sheet.append(["Other", "Stuff"])
    sheet.append(["row 3", 30])
    book.save(path)


def make_far(path):
    # Stray note far below: documents the overcount.
    book = Workbook()
    sheet = book.active
    sheet.append(HEADERS)
    sheet.append(["row 1", 10])
    sheet.append(["row 2", 20])
    sheet["A500"] = "stray note"
    book.save(path)


def pdf_escape(text):
    return (
        text.replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
    )


def make_pdf(path, lines):
    # Hand-rolled single-page PDF: no writer dep needed.
    content_lines = ["BT /F1 12 Tf 72 720 Td 14 TL"]
    for i, line in enumerate(lines):
        if i > 0:
            content_lines.append("T*")
        content_lines.append(f"({pdf_escape(line)}) Tj")
    content_lines.append("ET")
    content = "\n".join(content_lines).encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox "
        b"[0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> "
        b"/Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n" % len(content)
        + content + b"\nendstream",
    ]
    out = [b"%PDF-1.4\n"]
    offsets = [0]
    for i, body in enumerate(objs, start=1):
        offsets.append(sum(len(part) for part in out))
        out.append(b"%d 0 obj\n" % i + body + b"\nendobj\n")
    xref = sum(len(part) for part in out)
    out.append(b"xref\n0 %d\n" % (len(objs) + 1))
    out.append(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.append(b"%010d 00000 n \n" % off)
    out.append(
        b"trailer\n<< /Size %d /Root 1 0 R >>\n"
        b"startxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    )
    with open(path, "wb") as handle:
        handle.write(b"".join(out))


# PDF path to text lines: anchors are whitespace-bounded 9-digit
# blocks; decoys must not count.
PDFS = {
    os.path.join(ACME, "4.1.26.pdf"): [
        "claim 123456789 paid",
        "456789123 789123456",
    ],
    os.path.join(MISC, "6.11.2026.pdf"): [
        "member 111222333 ok",
        "member 444555666 ok",
        "claim 777888999-0 paid",
        "claim 888999111-42 ok",
        "decoys 12345678 1234567890",
        "attached X123456789 and 123456789, stay uncounted",
    ],
    os.path.join(MISC, "Stray-empty Jul 26.pdf"): [
        "no claims here",
        "nothing to count",
    ],
}


CUSTOM = {
    os.path.join(ACME, "Stacked-table Jun 26.xlsx"):
        make_stacked,
    os.path.join(MISC, "Stray-note Jul 26.xlsx"):
        make_far,
}


def main():
    keep = os.path.join(ROOT, KEEP)
    if not os.path.isfile(keep):
        sys.exit(
            f"refusing to wipe {ROOT}: "
            f"{keep} missing - run from repo root"
        )
    for dirpath, _, files in os.walk(ROOT):
        for name in files:
            if name != KEEP:
                os.unlink(os.path.join(dirpath, name))

    for rel, counts in FILES.items():
        full = os.path.join(ROOT, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        make_workbook(full, counts)

    for rel, pairs in SHEETS.items():
        full = os.path.join(ROOT, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        make_named_workbook(full, pairs)

    for rel, make in CUSTOM.items():
        full = os.path.join(ROOT, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        make(full)

    for rel, lines in PDFS.items():
        full = os.path.join(ROOT, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        make_pdf(full, lines)

    titles = os.path.join(ROOT, KEEP)
    with open(titles, "w") as handle:
        handle.write("\n".join(TITLES) + "\n")

    for rel in DECOYS:
        full = os.path.join(ROOT, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        open(full, "w").close()

    for rel, blob in GARBAGE.items():
        full = os.path.join(ROOT, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as handle:
            handle.write(blob)


if __name__ == "__main__":
    main()
