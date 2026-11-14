# csv-delimiter-checker-cli

Check CSV files use one delimiter consistently, fail CI when rows disagree.

[![CI](https://github.com/haiderstudio/csv-delimiter-checker-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/haiderstudio/csv-delimiter-checker-cli/actions/workflows/ci.yml) [![Licence: MIT](https://img.shields.io/badge/Licence-MIT-yellow.svg)](LICENSE)

## What it does

`csv_delimiter_checker` reads each CSV file you point it at
and reports every row that uses a different delimiter from the
rest of the file, with the file and the line it starts on:

- A file that mixes commas and semicolons imports as garbage
  in one tool and fine in another, and the failure shows up
  downstream, not at the file. This tool reports the row that
  disagrees, so you can find the bad row at once. The `bad.csv`
  example has a comma header, but rows 2 and 4 use semicolons,
  and both are reported with their lines.
- The file's delimiter is found with the `csv` module's
  Sniffer on a sample of the file, checked against a manual
  count of the delimiters in the first row — the Sniffer's
  answer is only trusted when it actually appears in that
  row. Then every row gets a manual consistency pass: each
  candidate delimiter (comma, semicolon, tab, pipe) is counted
  outside quoted fields, so a semicolon inside `"a;b"` never
  counts as a delimiter.
- A row that uses a different delimiter is reported as
  `row uses ; instead of ,`. A row that uses two delimiters
  at once is reported as `row mixes , and ;, expected ,`.
  A row that uses no delimiter at all is not flagged here —
  that is a row-shape problem, and repo #58's
  `csv-column-count-checker-cli` owns it.
- A quoted field that spans several lines (an address with a
  line break inside quotes, for example) is one row, and its
  line is the line where the row starts. A quoted field with
  a delimiter inside it is one field, not two — the
  `quoted.csv` example has a semicolon and a tab inside
  quotes, and a multi-line quoted field with a semicolon in
  it, and passes clean.
- A file whose rows carry no delimiter at all is a
  single-column file and passes — unless one row introduces
  a delimiter the rest of the file never uses, which is
  reported as `row uses ; but the file has no delimiter
  (single column)`.
- A file that cannot be parsed at all — an unbalanced quote —
  is reported as a problem for that file, with the line where
  the parse failed, and any delimiter problems found before
  that line are still reported. A line with a NUL byte in it
  is reported as a problem for that line, and the rest of the
  file is still checked. Fixing the broken quoting is repo
  #80's `csv-quote-checker-cli`'s job.
- It exits 1 when any row disagrees on the delimiter (or an
  unreadable file is found), so it can fail a CI run. A clean
  folder exits 0.
- CSV files come from the command line (one or more), or from a
  folder walk: every `.csv` file under a folder, recursively by
  default (`--no-recursive` stops at the top level). `.git` and
  `__pycache__` folders are never walked, and directory links
  are never followed, so a link cycle cannot loop the check.
- `--delimiter` declares the delimiter the files use, for
  example `--delimiter ';'` for semicolon files. A file
  checked with the wrong delimiter is flagged on every row
  that uses the real one — so pick the delimiter your files
  use, or leave it off and let the tool detect it.
- `--exclude PATTERN` skips walked files by glob, for example
  `--exclude 'draft-*'`. It can be repeated. A file passed
  directly on the command line is always checked, even if it
  matches an exclude pattern and even if it has no `.csv`
  extension.
- `--stdin` reads one CSV document from standard input.
- `--json` prints the result as machine-readable JSON (the
  summary goes to standard error, so standard output stays
  clean JSON). Each problem carries the file's delimiter
  (`expected`) and the delimiters the row uses (`found`).
- It is report-only and runs fully offline: it never edits a
  file, sends nothing anywhere, and needs no API key. Python
  standard library only — the `csv` module's Sniffer does the
  detection, and a manual consistency pass checks every row.

## What it does NOT do

- It does not check column counts — that is repo #58's
  `csv-column-count-checker-cli`. A row with the wrong number
  of columns but the same delimiter passes here. Delimiter
  drift is a different check from row shape, on the same
  files.
- It does not check duplicate rows — that is repo #84's
  `csv-duplicate-row-checker-cli`. A repeated row with a
  consistent delimiter passes here.
- It does not check empty rows or empty cells — that is repo
  #73's `csv-empty-checker-cli`. A blank line passes here.
- It does not check the header row's names or duplicates —
  that is repo #40's `csv-header-checker-cli`.
- It does not check quotes — that is repo #80's
  `csv-quote-checker-cli`. An unbalanced quote is reported
  only as a file that cannot be parsed, not as a quoting
  problem.
- It does not fix a mixed delimiter. A row that disagrees is
  reported; deciding which delimiter the file should use is
  your job.
- An empty file passes: it has no rows to disagree. A
  header-only file passes for the same reason.

## Who it is for

Anyone who ships CSV data files and wants them to import the
same way everywhere: a data analyst checking a spreadsheet
export before it goes into a database, a developer adding a
CI step that fails the build when a data file mixes its
delimiter, or anyone tidying a folder of CSVs that came from
different tools — one exports commas, another exports
semicolons, and the mixed file only breaks when it is loaded.
One drifted row is invisible in the file itself — this
catches it before the import does.

## How this differs from similar tools

The exact name `csv-delimiter-checker-cli` matches 0
repositories on GitHub (checked Nov 13, 2026), and the wider
field is small: `csv delimiter checker` matches 2
repositories. Both do the exact job, and both are 0 stars:
naxels/go_csv_file_checker — "Golang delimiter separated
file checker" (a Go tool, with a Go test file, no CI
workflow); and kraxmo/csv_checker — "Checks files and
directories for properly delimited data" (a Python tool,
with a test file, no CI workflow). Neither one is a tested
Python standard-library CLI that checks CSV files for
delimiter drift as its one job, reports each disagreeing
row with file and line, and exits 1 for CI. This tool does
that one job: a Python standard-library-only CLI that checks
CSV files use one delimiter consistently — no install beyond
Python, no website, no network.

## Install

Python standard library only — no packages to download. You need
Python 3.8 or newer. Clone the repo and run it in place:

```
git clone https://github.com/haiderstudio/csv-delimiter-checker-cli.git
cd csv-delimiter-checker-cli
python3 src/csv_delimiter_checker.py examples/good.csv
```

```
examples/good.csv: OK
OK — 1 file(s) checked, no delimiter problems.
```

## Usage

Check one clean file (every row uses commas):

```
python3 src/csv_delimiter_checker.py examples/good.csv
```

```
examples/good.csv: OK
OK — 1 file(s) checked, no delimiter problems.
```

Check a file with mixed delimiters (rows 2 and 4 use
semicolons while the header and row 3 use commas):

```
python3 src/csv_delimiter_checker.py examples/bad.csv
```

```
FAIL examples/bad.csv:2: row uses ; instead of ,
FAIL examples/bad.csv:4: row uses ; instead of ,
Checked 1 file(s), 2 problem(s) in 1 file(s).
```

Check a file of quoted fields with delimiters inside the
quotes — a semicolon and a tab inside quotes, and a
multi-line quoted field with a semicolon in it — no row
disagrees, so it passes:

```
python3 src/csv_delimiter_checker.py examples/quoted.csv
```

```
examples/quoted.csv: OK
OK — 1 file(s) checked, no delimiter problems.
```

Check a whole folder:

```
python3 src/csv_delimiter_checker.py examples/
```

```
FAIL examples/bad.csv:2: row uses ; instead of ,
FAIL examples/bad.csv:4: row uses ; instead of ,
examples/good.csv: OK
examples/quoted.csv: OK
Checked 3 file(s), 2 problem(s) in 1 file(s).
```

Check a semicolon file — first make one, then check it with
the flag (delete it after; it is only a scratch file):

```
printf 'id;name;score\n1;Alice;90\n2;Bob;85\n' > semi.csv
python3 src/csv_delimiter_checker.py --delimiter ';' semi.csv
rm semi.csv
```

```
semi.csv: OK
OK — 1 file(s) checked, no delimiter problems.
```

Check one document from standard input:

```
python3 src/csv_delimiter_checker.py --stdin < examples/bad.csv
```

```
FAIL <stdin>:2: row uses ; instead of ,
FAIL <stdin>:4: row uses ; instead of ,
Checked 1 file(s), 2 problem(s) in 1 file(s).
```

Machine-readable output with `--json` (the summary goes to
standard error, so standard output stays clean JSON):

```
python3 src/csv_delimiter_checker.py --json examples/bad.csv
```

```
{
  "files": [
    {
      "file": "examples/bad.csv",
      "problems": [
        {
          "file": "examples/bad.csv",
          "line": 2,
          "reason": "row uses ; instead of ,",
          "expected": ",",
          "found": [
            ";"
          ]
        },
        {
          "file": "examples/bad.csv",
          "line": 4,
          "reason": "row uses ; instead of ,",
          "expected": ",",
          "found": [
            ";"
          ]
        }
      ]
    }
  ],
  "summary": {
    "checked": 1,
    "files_with_problems": 1,
    "problems": 2
  }
}
```

Exit codes: 0 when every checked file is clean, 1 when any
row disagrees on the delimiter (or an unreadable file is
found), 2 for a usage problem (no files given, a bad flag,
a bad `--delimiter` value, or a missing file or folder).

## Examples

### 1. A folder of data files, mixed delimiters in one

`examples/` holds three CSV files. Two are clean, one mixes
delimiters:

```
python3 src/csv_delimiter_checker.py examples/
```

```
FAIL examples/bad.csv:2: row uses ; instead of ,
FAIL examples/bad.csv:4: row uses ; instead of ,
examples/good.csv: OK
examples/quoted.csv: OK
Checked 3 file(s), 2 problem(s) in 1 file(s).
```

### 2. Delimiters inside quoted fields are not delimiters

`examples/quoted.csv` has a semicolon and a tab inside
quoted fields, and a multi-line quoted field with a
semicolon in it. None of those count as delimiters, so the
file passes — the quotes protect the values, and the line
break inside quotes never splits a row:

```
python3 src/csv_delimiter_checker.py examples/quoted.csv
```

```
examples/quoted.csv: OK
OK — 1 file(s) checked, no delimiter problems.
```

### 3. The bundled examples, all at once

```
sh examples/run-example.sh
```

The script checks the whole `examples/` folder (fail, on
purpose — it picks up the mixed delimiters). Its full output is in
`examples/sample-output.md`, ending with `Checked 3 file(s),
2 problem(s) in 1 file(s).` The failing run exits 1, which
is the expected result — the script ends with exit 0 so it
can be run as a demo.

## How it is tested

Tests, standard library `unittest` only, no packages to install:

```
python3 tests/test_csv_delimiter_checker.py
```

The tests cover: delimiter detection (comma, semicolon,
tab, pipe, single-column files, blank lines before the
first row, a declared delimiter winning, unquoted counting
with doubled quotes), consistent files (all four
delimiters, single-column, header-only, empty, blank lines
skipped, CRLF, a declared delimiter, a row with no
delimiter at all passing as a row-shape problem, not a
delimiter problem), mixed delimiters (one bad row, two bad
rows with line numbers, comma in a semicolon file, pipe in
a tab file, tab in a comma file, a row mixing two
delimiters, the first row itself mixing, a bad row after
many good rows, a single-column row introducing a
delimiter, a wrong declared delimiter flagging every row),
quoted delimiters (semicolon, comma, tab, and pipe inside
quotes, doubled quotes, a multi-line quoted field with a
delimiter inside it, a bad row after a multi-line quoted
field on the right line, a bad row that is itself
multi-line), edge cases (a NUL byte, an unbalanced quote
reported as a parse problem with problems found before it
still reported, an unreadable path), file collection (a
folder walk, `.git` skipped, `--no-recursive`, `--exclude`,
a direct file checked even without a `.csv` extension and
even if excluded, an empty folder, uppercase `.CSV`
extensions, sorted and deduplicated results), the CLI (exit
0/1/2, each flag, `--stdin` good and bad, `--json` output
with `expected` and `found`, `--version`, bad flags, a bad
delimiter, missing paths, a folder summary count, and every
bundled example file read back with its expected problems),
the bundled examples (sample output compared byte-for-byte
against a fresh run, and the README-quoted outputs checked
against it), working-directory robustness (the tests pass
from the repo root, from a temp folder, and from the
filesystem root — paths are checked by file name and
message, never by an absolute path), and hygiene checks (no
placeholder text, no absolute paths, stdlib imports only,
`.env` first in `.gitignore`, CI file runs the test file).

## Contributing

Small, focused improvements are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

MIT — see [LICENSE](LICENSE).

## Original work

This tool was written from scratch for this repo. The idea
of checking CSV files for a consistent delimiter is not new
— the similar tools named above (the Go delimiter checker
and the Python delimiter checker) are listed in "How this
differs" — but every line of code here is original, and the
tool builds on nothing but Python's standard library.
