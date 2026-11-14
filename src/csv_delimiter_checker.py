"""csv-delimiter-checker-cli: check CSV files use one delimiter consistently.

Reads one or more CSV files (or folders of them), and reports every
row that uses a different delimiter from the rest of the file, with
the file and the line. A file that mixes commas and semicolons
imports as garbage in one tool and fine in another, and the failure
shows up downstream, not at the file. This tool catches the drift
at the file. Report-only: it never rewrites a file. Exit 0 when
every file is clean, 1 when any row disagrees on the delimiter (or
a file cannot be read or parsed), 2 for a usage error.

How the check works: the file's delimiter is found with the csv
module's Sniffer on a sample of the file, checked against a manual
count of the delimiters in the first row — the Sniffer's answer is
only trusted when it actually appears in that row. Then every row
gets a manual consistency pass: each candidate delimiter
(comma, semicolon, tab, pipe) is counted outside quoted fields, so
a semicolon inside "a;b" never counts as a delimiter. A row that
uses only the file's delimiter passes; a row that uses a different
one, or mixes two, is reported with its line. A row with no
delimiter at all is not a delimiter problem — that is a row-shape
problem, and repo #58's csv-column-count-checker-cli owns it.
A file whose rows carry no delimiter at all is a single-column
file and passes, unless one row introduces a delimiter the rest
of the file never uses.
"""

import argparse
import csv
import fnmatch
import io
import json
import os
import sys
from pathlib import Path

__version__ = "1.0.0"

CSV_SUFFIX = ".csv"

# The delimiters this tool knows, in preference order. The order
# breaks ties when the first row uses two delimiters equally.
CANDIDATES = [",", ";", "\t", "|"]


def display(delimiter):
    """A readable name for a delimiter in a report line."""
    if delimiter == "\t":
        return "tab"
    return delimiter


def count_unquoted(text, delimiter):
    """Count occurrences of delimiter outside quoted fields.

    A double quote toggles the quoted state, and a doubled quote
    inside a quoted field is one escaped quote, not a toggle — the
    same rule the csv module follows. A delimiter inside quotes
    is part of a value, not a field separator.
    """
    count = 0
    in_quotes = False
    i = 0
    while i < len(text):
        char = text[i]
        if char == '"':
            if in_quotes and i + 1 < len(text) and text[i + 1] == '"':
                i += 2
                continue
            in_quotes = not in_quotes
        elif char == delimiter and not in_quotes:
            count += 1
        i += 1
    return count


def row_delimiters(raw):
    """The candidate delimiters a raw row uses, in CANDIDATES order."""
    return [d for d in CANDIDATES if count_unquoted(raw, d) > 0]


def detect_delimiter(text, declared=None):
    """The file's delimiter, or None for a single-column file.

    A declared --delimiter always wins. Otherwise the csv
    Sniffer's answer is used when it actually appears, unquoted,
    in the first non-blank row; if the Sniffer cannot decide, or
    its answer does not appear in that row, the delimiter with
    the most unquoted occurrences in the first row wins (ties
    break in CANDIDATES order). No delimiter in the first row
    means a single-column file.
    """
    if declared is not None:
        return declared
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    first = lines[0]
    sample = "\n".join(lines[:10])
    try:
        sniffed = csv.Sniffer().sniff(sample, delimiters=CANDIDATES)
        if sniffed.delimiter in CANDIDATES:
            if count_unquoted(first, sniffed.delimiter) > 0:
                return sniffed.delimiter
    except csv.Error:
        pass
    used = row_delimiters(first)
    if not used:
        return None
    return used[0]


class Problem:
    """One problem in one file: path, line, plain reason.

    For a row that disagrees on the delimiter, the line is the
    line the row starts on, and the problem also carries the
    file's delimiter (expected) and the delimiters the row uses
    (found). For a file that cannot be parsed, the line is the
    line where the parse failed.
    """

    def __init__(self, path, line, reason, expected=None, found=None):
        self.path = path
        self.line = line
        self.reason = reason
        self.expected = expected
        self.found = found

    def text(self):
        return f"{self.path}:{self.line}: {self.reason}"

    def as_dict(self):
        data = {"file": self.path, "line": self.line,
                "reason": self.reason}
        if self.expected is not None or self.found is not None:
            data["expected"] = self.expected
            data["found"] = self.found
        return data


def check_text(text, path, delimiter=None):
    """Check one CSV document given as text. Returns a list of Problems."""
    lines = text.splitlines()
    nul_lines = [lineno for lineno, line in enumerate(lines, start=1)
                 if "\x00" in line]
    expected = detect_delimiter(text, declared=delimiter)
    parse_delimiter = expected if expected is not None else ","
    problems = []
    reader = csv.reader(io.StringIO(text, newline=""),
                        delimiter=parse_delimiter, strict=True)
    while True:
        start_line = reader.line_num + 1
        try:
            row = next(reader)
        except StopIteration:
            break
        except csv.Error as exc:
            problems.append(Problem(
                path, start_line, f"cannot parse CSV: {exc}"))
            break
        if row == []:
            continue
        end_line = reader.line_num
        raw = "\n".join(lines[start_line - 1:end_line])
        used = row_delimiters(raw)
        if expected is None:
            if used:
                names = " and ".join(display(d) for d in used)
                problems.append(Problem(
                    path, start_line,
                    f"row uses {names} but the file has no delimiter "
                    "(single column)",
                    expected=None, found=used))
            continue
        if not used or used == [expected]:
            continue
        if len(used) == 1:
            reason = (f"row uses {display(used[0])} instead of "
                      f"{display(expected)}")
        else:
            names = " and ".join(display(d) for d in used)
            reason = (f"row mixes {names}, "
                      f"expected {display(expected)}")
        problems.append(Problem(path, start_line, reason,
                                expected=expected, found=used))
    for lineno in nul_lines:
        problems.append(Problem(
            path, lineno,
            "line contains NUL byte (not valid CSV text)"))
    return problems


def check_file(path, delimiter=None):
    """Check one CSV file on disk. Returns a list of Problems."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return [Problem(str(path), 0,
                        f"cannot read file: {exc.strerror or exc}")]
    return check_text(text, str(path), delimiter)


def is_excluded(name, patterns):
    """True when a file name matches any --exclude glob pattern."""
    return any(fnmatch.fnmatchcase(name, pattern)
               for pattern in patterns)


def collect_files(paths, recursive=True, exclude=()):
    """Gather CSV files from the given paths.

    A file passed directly is always checked, even without a .csv
    extension and even if it matches an --exclude pattern. A folder
    contributes its .csv files (recursively unless --no-recursive),
    skipping .git and __pycache__ folders, never following directory
    links. Returns (files, missing) with files sorted and deduplicated.
    """
    files = []
    missing = []
    for raw in paths:
        path = Path(raw)
        if not path.exists():
            missing.append(raw)
            continue
        if path.is_file():
            files.append(str(path))
            continue
        for root, dirs, names in os.walk(path):
            dirs[:] = sorted(
                name for name in dirs
                if name not in (".git", "__pycache__")
                and not os.path.islink(os.path.join(root, name))
            )
            if not recursive:
                dirs[:] = []
            for name in sorted(names):
                if not name.lower().endswith(CSV_SUFFIX):
                    continue
                if is_excluded(name, exclude):
                    continue
                files.append(str(Path(root) / name))
    return sorted(set(files)), missing


def build_parser():
    parser = argparse.ArgumentParser(
        prog="csv_delimiter_checker",
        description="Check CSV files use one delimiter consistently.",
    )
    parser.add_argument(
        "paths", nargs="*", metavar="PATH",
        help="CSV file(s) or folder(s) to check",
    )
    parser.add_argument(
        "--delimiter", default=None,
        help="the delimiter the files use (default: detect it, "
             "comma, semicolon, tab or pipe)",
    )
    parser.add_argument(
        "--exclude", action="append", default=[], metavar="PATTERN",
        help="skip walked files whose name matches this glob "
             "(repeatable; direct files are always checked)",
    )
    parser.add_argument(
        "--no-recursive", action="store_true",
        help="do not walk into subfolders",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="print the result as machine-readable JSON "
             "(the summary goes to standard error)",
    )
    parser.add_argument(
        "--stdin", action="store_true",
        help="read one CSV document from standard input",
    )
    parser.add_argument(
        "--version", action="version", version="%(prog)s " + __version__,
    )
    return parser


def report_text(results, checked, total):
    """Print the plain-text report. Returns the exit code."""
    files_with_problems = sum(1 for _, probs in results if probs)
    for path, problems in results:
        if problems:
            for problem in problems:
                print(f"FAIL {problem.text()}")
        else:
            print(f"{path}: OK")
    if total == 0:
        print(f"OK — {checked} file(s) checked, "
              "no delimiter problems.")
        return 0
    print(f"Checked {checked} file(s), {total} problem(s) "
          f"in {files_with_problems} file(s).")
    return 1


def report_json(results, checked, total):
    """Print the JSON report. Returns the exit code."""
    files_with_problems = sum(1 for _, probs in results if probs)
    payload = {
        "files": [
            {
                "file": path,
                "problems": [problem.as_dict() for problem in problems],
            }
            for path, problems in results
        ],
        "summary": {
            "checked": checked,
            "files_with_problems": files_with_problems,
            "problems": total,
        },
    }
    print(json.dumps(payload, indent=2))
    print(f"Checked {checked} file(s), {total} problem(s) "
          f"in {files_with_problems} file(s).", file=sys.stderr)
    return 1 if total else 0


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.delimiter is not None and len(args.delimiter) != 1:
        parser.error("--delimiter must be a single character")
    if args.stdin:
        if args.paths:
            parser.error("--stdin takes no PATH arguments")
        results = [("<stdin>", check_text(
            sys.stdin.read(), "<stdin>", args.delimiter))]
        checked = 1
    else:
        if not args.paths:
            parser.error("give at least one PATH, or use --stdin")
        files, missing = collect_files(
            args.paths,
            recursive=not args.no_recursive,
            exclude=args.exclude,
        )
        if missing:
            for raw in missing:
                print(f"error: no such file or folder: {raw}",
                      file=sys.stderr)
            return 2
        if not files:
            print("error: no CSV files found", file=sys.stderr)
            return 2
        results = [(path, check_file(path, args.delimiter))
                   for path in files]
        checked = len(files)
    total = sum(len(problems) for _, problems in results)
    if args.json:
        return report_json(results, checked, total)
    return report_text(results, checked, total)


if __name__ == "__main__":
    sys.exit(main())
