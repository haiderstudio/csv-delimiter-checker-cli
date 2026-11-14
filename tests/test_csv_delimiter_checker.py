"""Tests for csv_delimiter_checker: delimiter drift, CLI, examples, hygiene.

CWD-robust: every CLI run uses absolute paths and every assertion
checks a file-name suffix plus the message text, never an absolute
path — so this suite passes from any working directory.
"""

import ast
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import csv_delimiter_checker as checker

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "csv_delimiter_checker.py"
EXAMPLES = ROOT / "examples"
README = ROOT / "README.md"


def problems(text, delimiter=None):
    """All problems in a document: (line, reason, expected, found)."""
    return [(p.line, p.reason, p.expected, p.found)
            for p in checker.check_text(text, "t.csv", delimiter)]


class TestDetection(unittest.TestCase):
    def test_comma_detected(self):
        self.assertEqual(
            checker.detect_delimiter("a,b\n1,2\n"), ",")

    def test_semicolon_detected(self):
        self.assertEqual(
            checker.detect_delimiter("a;b\n1;2\n"), ";")

    def test_tab_detected(self):
        self.assertEqual(
            checker.detect_delimiter("a\tb\n1\t2\n"), "\t")

    def test_pipe_detected(self):
        self.assertEqual(
            checker.detect_delimiter("a|b\n1|2\n"), "|")

    def test_single_column_detects_none(self):
        self.assertIsNone(checker.detect_delimiter("name\nAlice\n"))

    def test_empty_detects_none(self):
        self.assertIsNone(checker.detect_delimiter(""))

    def test_blank_lines_skipped_for_detection(self):
        self.assertEqual(
            checker.detect_delimiter("\n\na;b\n1;2\n"), ";")

    def test_declared_delimiter_wins(self):
        self.assertEqual(
            checker.detect_delimiter("a,b\n1,2\n", declared=";"), ";")

    def test_count_unquoted_ignores_quoted_delimiter(self):
        self.assertEqual(
            checker.count_unquoted('1,"a;b",2', ";"), 0)
        self.assertEqual(
            checker.count_unquoted('1,"a;b",2', ","), 2)

    def test_count_unquoted_doubled_quote(self):
        self.assertEqual(
            checker.count_unquoted('1,"say ""a;b""",2', ";"), 0)

    def test_row_delimiters_lists_each_used(self):
        self.assertEqual(
            checker.row_delimiters("1,2;3"), [",", ";"])
        self.assertEqual(checker.row_delimiters("1,2"), [","])
        self.assertEqual(checker.row_delimiters("abc"), [])


class TestConsistentFiles(unittest.TestCase):
    def test_consistent_comma_passes(self):
        self.assertEqual(
            problems("id,name,score\n1,Alice,90\n2,Bob,85\n"), [])

    def test_consistent_semicolon_passes(self):
        self.assertEqual(
            problems("id;name;score\n1;Alice;90\n2;Bob;85\n"), [])

    def test_consistent_tab_passes(self):
        self.assertEqual(
            problems("id\tname\tscore\n1\tAlice\t90\n2\tBob\t85\n"), [])

    def test_consistent_pipe_passes(self):
        self.assertEqual(
            problems("id|name|score\n1|Alice|90\n2|Bob|85\n"), [])

    def test_single_column_passes(self):
        self.assertEqual(problems("name\nAlice\nBob\n"), [])

    def test_header_only_passes(self):
        self.assertEqual(problems("a,b,c\n"), [])

    def test_empty_file_passes(self):
        self.assertEqual(problems(""), [])

    def test_blank_lines_skipped(self):
        self.assertEqual(
            problems("a,b\n1,2\n\n\n3,4\n"), [])

    def test_no_trailing_newline_passes(self):
        self.assertEqual(problems("a,b\n1,2"), [])

    def test_crlf_consistent_passes(self):
        self.assertEqual(problems("a,b\r\n1,2\r\n3,4\r\n"), [])

    def test_declared_delimiter_matching_passes(self):
        self.assertEqual(
            problems("a;b\n1;2\n", delimiter=";"), [])

    def test_row_with_no_delimiter_is_not_a_delimiter_problem(self):
        # A one-field row in a comma file is a row-shape problem
        # (repo #58's job), not delimiter drift.
        self.assertEqual(problems("a,b\n1,2\n3\n"), [])


class TestMixedDelimiters(unittest.TestCase):
    def test_one_semicolon_row_in_comma_file(self):
        found = problems("a,b\n1,2\n3;4\n")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][0], 3)
        self.assertEqual(found[0][1], "row uses ; instead of ,")
        self.assertEqual(found[0][2], ",")
        self.assertEqual(found[0][3], [";"])

    def test_two_bad_rows_line_numbers(self):
        found = problems("id,name,score\n1;Alice;90\n2,Bob,85\n"
                         "3;Carol;88\n")
        self.assertEqual([p[0] for p in found], [2, 4])
        self.assertEqual(found[0][1], "row uses ; instead of ,")
        self.assertEqual(found[1][1], "row uses ; instead of ,")

    def test_comma_row_in_semicolon_file(self):
        found = problems("a;b\n1;2\n3,4\n")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][0], 3)
        self.assertEqual(found[0][1], "row uses , instead of ;")

    def test_pipe_row_in_tab_file(self):
        found = problems("a\tb\n1\t2\n3|4\n")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][1], "row uses | instead of tab")

    def test_tab_row_in_comma_file(self):
        found = problems("a,b\n1,2\n3\t4\n")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][1], "row uses tab instead of ,")

    def test_row_mixing_two_delimiters(self):
        found = problems("a,b\n1,2;3\n")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][0], 2)
        self.assertEqual(found[0][1],
                         "row mixes , and ;, expected ,")
        self.assertEqual(found[0][3], [",", ";"])

    def test_first_row_mixing_is_flagged(self):
        found = problems("a,b;c\n1,2,3\n")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][0], 1)
        self.assertIn("mixes", found[0][1])

    def test_bad_row_after_many_good_rows(self):
        found = problems("a,b\n1,2\n3,4\n5,6\n7,8\n9;10\n")
        self.assertEqual([p[0] for p in found], [6])

    def test_single_column_row_introducing_a_delimiter(self):
        found = problems("name\nAlice\nBob;Carol\n")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][0], 3)
        self.assertIn("no delimiter", found[0][1])
        self.assertIn("single column", found[0][1])
        self.assertIsNone(found[0][2])
        self.assertEqual(found[0][3], [";"])

    def test_declared_wrong_delimiter_flags_every_row(self):
        found = problems("a,b\n1,2\n", delimiter=";")
        self.assertEqual(len(found), 2)
        self.assertEqual(found[0][1], "row uses , instead of ;")

    def test_problem_text_format(self):
        problem = checker.check_text("a,b\n1;2\n", "f.csv")[0]
        self.assertEqual(problem.text(),
                         "f.csv:2: row uses ; instead of ,")

    def test_problem_as_dict(self):
        problem = checker.check_text("a,b\n1;2\n", "f.csv")[0]
        self.assertEqual(problem.as_dict(), {
            "file": "f.csv",
            "line": 2,
            "reason": "row uses ; instead of ,",
            "expected": ",",
            "found": [";"],
        })


class TestQuotedDelimiters(unittest.TestCase):
    def test_semicolon_inside_quotes_passes(self):
        self.assertEqual(
            problems('a,b\n1,"semi;colon",90\n'), [])

    def test_comma_inside_quotes_in_semicolon_file_passes(self):
        self.assertEqual(
            problems('a;b\n1;"comma, inside";90\n', delimiter=";"), [])

    def test_tab_inside_quotes_passes(self):
        self.assertEqual(
            problems('a,b\n1,"tab\tinside",90\n'), [])

    def test_pipe_inside_quotes_passes(self):
        self.assertEqual(
            problems('a,b\n1,"pipe|inside",90\n'), [])

    def test_doubled_quote_with_delimiter_inside_passes(self):
        self.assertEqual(
            problems('a,b\n1,"say ""a;b""",90\n'), [])

    def test_multiline_quoted_field_with_delimiter_passes(self):
        self.assertEqual(
            problems('a,b\n1,"line one\nline two; here"\n2,3\n'), [])

    def test_bad_row_after_multiline_quoted_field_line(self):
        found = problems('id,note\n1,"line one\nline two"\n2;3;4\n')
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][0], 4)
        self.assertEqual(found[0][1], "row uses ; instead of ,")

    def test_bad_row_that_is_itself_multiline(self):
        # The semicolon is outside the quotes, so the row is
        # flagged on the line where the row starts.
        found = problems('a,b\n1,"x\ny",3;4\n')
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][0], 2)
        self.assertIn("mixes", found[0][1])


class TestEdgeCases(unittest.TestCase):
    def test_nul_byte_is_a_problem(self):
        found = problems("a,b\n1,\x002\n")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][0], 2)
        self.assertIn("NUL byte", found[0][1])

    def test_nul_line_reported_alongside_delimiter_problem(self):
        found = problems("a,b\n1,2\n1;2\n3,\x004\n")
        self.assertEqual(len(found), 2)
        self.assertIn("instead of", found[0][1])
        self.assertIn("NUL byte", found[1][1])
        self.assertEqual(found[1][0], 4)

    def test_unbalanced_quote_is_a_parse_problem(self):
        found = problems('a,b\n1,"x\n2,3\n')
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][0], 2)
        self.assertIn("cannot parse CSV", found[0][1])
        self.assertIn("unexpected end of data", found[0][1])

    def test_problems_before_parse_error_are_still_reported(self):
        found = problems('a,b\n1;2\n3,"x\n')
        self.assertEqual(len(found), 2)
        self.assertIn("instead of", found[0][1])
        self.assertIn("cannot parse CSV", found[1][1])
        self.assertEqual(found[1][0], 3)


class TestCheckFile(unittest.TestCase):
    def test_unreadable_path(self):
        found = checker.check_file("/nonexistent-dir-xyz/f.csv")
        self.assertEqual(len(found), 1)
        self.assertIn("cannot read file", found[0].reason)

    def test_file_on_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.csv"
            path.write_text("a,b\n1;2\n")
            found = checker.check_file(str(path))
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0].line, 2)
            self.assertEqual(found[0].reason, "row uses ; instead of ,")


class TestCollection(unittest.TestCase):
    def test_folder_walk_finds_csv_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.csv").write_text("a,b\n1,2\n")
            (root / "b.txt").write_text("a,b\n1;2\n")
            (root / "sub").mkdir()
            (root / "sub" / "c.csv").write_text("a,b\n1,2\n")
            files, missing = checker.collect_files([str(root)])
            self.assertEqual(missing, [])
            self.assertEqual(
                files, [str(root / "a.csv"), str(root / "sub" / "c.csv")])

    def test_git_folder_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            (root / ".git" / "x.csv").write_text("a,b\n1;2\n")
            (root / "a.csv").write_text("a,b\n1,2\n")
            files, _ = checker.collect_files([str(root)])
            self.assertEqual(files, [str(root / "a.csv")])

    def test_no_recursive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.csv").write_text("a,b\n1,2\n")
            (root / "sub").mkdir()
            (root / "sub" / "b.csv").write_text("a,b\n1,2\n")
            files, _ = checker.collect_files([str(root)], recursive=False)
            self.assertEqual(files, [str(root / "a.csv")])

    def test_exclude_pattern(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "draft-a.csv").write_text("a,b\n1,2\n")
            (root / "final.csv").write_text("a,b\n1,2\n")
            files, _ = checker.collect_files(
                [str(root)], exclude=["draft-*"])
            self.assertEqual(files, [str(root / "final.csv")])

    def test_direct_file_checked_despite_exclude_and_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "draft-data.txt"
            target.write_text("a,b\n1;2\n")
            files, _ = checker.collect_files(
                [str(target)], exclude=["draft-*"])
            self.assertEqual(files, [str(target)])

    def test_missing_path_reported(self):
        files, missing = checker.collect_files(["/no-such-path-xyz"])
        self.assertEqual(files, [])
        self.assertEqual(missing, ["/no-such-path-xyz"])

    def test_uppercase_extension_walked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "UP.CSV").write_text("a,b\n1,2\n")
            files, _ = checker.collect_files([str(root)])
            self.assertEqual(files, [str(root / "UP.CSV")])

    def test_results_sorted_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "b.csv").write_text("a,b\n1,2\n")
            (root / "a.csv").write_text("a,b\n1,2\n")
            files, _ = checker.collect_files(
                [str(root / "b.csv"), str(root), str(root / "a.csv")])
            self.assertEqual(files, [str(root / "a.csv"),
                                     str(root / "b.csv")])


class TestCLI(unittest.TestCase):
    def run_cli(self, *args, stdin=None, cwd=None):
        return subprocess.run(
            [sys.executable, str(SRC), *args],
            input=stdin, capture_output=True, text=True, cwd=cwd,
        )

    def test_clean_file_exit_0(self):
        result = self.run_cli(str(EXAMPLES / "good.csv"))
        self.assertEqual(result.returncode, 0)
        self.assertIn("good.csv: OK", result.stdout)
        self.assertIn("no delimiter problems", result.stdout)

    def test_bad_file_exit_1(self):
        result = self.run_cli(str(EXAMPLES / "bad.csv"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("bad.csv:2: row uses ; instead of ,",
                      result.stdout)
        self.assertIn("bad.csv:4: row uses ; instead of ,",
                      result.stdout)

    def test_quoted_example_exit_0(self):
        result = self.run_cli(str(EXAMPLES / "quoted.csv"))
        self.assertEqual(result.returncode, 0)
        self.assertIn("quoted.csv: OK", result.stdout)

    def test_folder_exit_1_and_summary(self):
        result = self.run_cli(str(EXAMPLES))
        self.assertEqual(result.returncode, 1)
        self.assertIn("Checked 3 file(s), 2 problem(s) in 1 file(s).",
                      result.stdout)

    def test_no_args_exit_2(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 2)

    def test_missing_path_exit_2(self):
        result = self.run_cli("no-such-file.csv")
        self.assertEqual(result.returncode, 2)
        self.assertIn("no such file or folder", result.stderr)

    def test_empty_folder_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_cli(tmp)
        self.assertEqual(result.returncode, 2)
        self.assertIn("no CSV files found", result.stderr)

    def test_bad_delimiter_exit_2(self):
        result = self.run_cli("--delimiter", ";;",
                              str(EXAMPLES / "good.csv"))
        self.assertEqual(result.returncode, 2)

    def test_bad_flag_exit_2(self):
        result = self.run_cli("--nope", str(EXAMPLES / "good.csv"))
        self.assertEqual(result.returncode, 2)

    def test_delimiter_flag_matching(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "semi.csv"
            path.write_text("id;name;score\n1;Alice;90\n2;Bob;85\n")
            result = self.run_cli("--delimiter", ";", str(path))
        self.assertEqual(result.returncode, 0)
        self.assertIn("semi.csv: OK", result.stdout)

    def test_delimiter_flag_wrong(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "semi.csv"
            path.write_text("id;name;score\n1,Alice,90\n")
            result = self.run_cli("--delimiter", ";", str(path))
        self.assertEqual(result.returncode, 1)
        self.assertIn("semi.csv:2: row uses , instead of ;",
                      result.stdout)

    def test_stdin(self):
        result = self.run_cli("--stdin", stdin="a,b\n1;2\n")
        self.assertEqual(result.returncode, 1)
        self.assertIn("FAIL <stdin>:2: row uses ; instead of ,",
                      result.stdout)

    def test_stdin_clean(self):
        result = self.run_cli("--stdin", stdin="a,b\n1,2\n")
        self.assertEqual(result.returncode, 0)

    def test_stdin_with_path_exit_2(self):
        result = self.run_cli("--stdin", str(EXAMPLES / "good.csv"))
        self.assertEqual(result.returncode, 2)

    def test_json_output(self):
        result = self.run_cli("--json",
                              str(EXAMPLES / "bad.csv"))
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["summary"]["problems"], 2)
        self.assertEqual(payload["summary"]["checked"], 1)
        self.assertTrue(payload["files"][0]["file"]
                        .endswith("bad.csv"))
        first = payload["files"][0]["problems"][0]
        self.assertEqual(first["line"], 2)
        self.assertEqual(first["reason"], "row uses ; instead of ,")
        self.assertEqual(first["expected"], ",")
        self.assertEqual(first["found"], [";"])
        second = payload["files"][0]["problems"][1]
        self.assertEqual(second["line"], 4)
        self.assertEqual(second["expected"], ",")
        self.assertEqual(second["found"], [";"])
        self.assertIn("Checked 1 file(s), 2 problem(s)",
                      result.stderr)

    def test_json_clean(self):
        result = self.run_cli("--json", str(EXAMPLES / "good.csv"))
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["summary"]["problems"], 0)

    def test_version(self):
        result = self.run_cli("--version")
        self.assertEqual(result.returncode, 0)
        self.assertIn("1.0.0", result.stdout)

    def test_exclude_flag(self):
        result = self.run_cli("--exclude", "bad.csv",
                              str(EXAMPLES))
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("bad.csv", result.stdout)
        self.assertIn("good.csv: OK", result.stdout)


class TestCwdRobustness(unittest.TestCase):
    """The CLI works from any working directory."""

    def test_cli_from_tmp(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, str(SRC),
                 str(EXAMPLES / "bad.csv")],
                capture_output=True, text=True, cwd=tmp,
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("bad.csv:2: row uses ; instead of ,",
                      result.stdout)

    def test_cli_from_filesystem_root(self):
        result = subprocess.run(
            [sys.executable, str(SRC), str(EXAMPLES / "good.csv")],
            capture_output=True, text=True, cwd="/",
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("good.csv: OK", result.stdout)

    def test_cli_from_unrelated_dir(self):
        # The CLI must work from any folder, not only the repo root:
        # run it from a fresh temp folder (no local paths involved,
        # so this passes on a CI runner too).
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, str(SRC), str(EXAMPLES / "quoted.csv")],
                capture_output=True, text=True, cwd=tmp,
            )
        self.assertEqual(result.returncode, 0)
        self.assertIn("quoted.csv: OK", result.stdout)

    def test_cli_from_tmp_folder_walk(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, str(SRC), str(EXAMPLES)],
                capture_output=True, text=True, cwd=tmp,
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("Checked 3 file(s), 2 problem(s) in 1 file(s).",
                      result.stdout)


class TestExamples(unittest.TestCase):
    def test_bundled_files_expected_problems(self):
        expected = {
            "good.csv": [],
            "quoted.csv": [],
            "bad.csv": [
                (2, "row uses ; instead of ,"),
                (4, "row uses ; instead of ,"),
            ],
        }
        for name, want in expected.items():
            text = (EXAMPLES / name).read_text()
            got = [(p.line, p.reason)
                   for p in checker.check_text(text, name)]
            self.assertEqual(got, want, name)

    def test_sample_output_matches_fresh_run(self):
        result = subprocess.run(
            ["sh", str(EXAMPLES / "run-example.sh")],
            capture_output=True, text=True, cwd="/tmp",
        )
        self.assertEqual(result.returncode, 0)
        sample = (EXAMPLES / "sample-output.md").read_text()
        block = sample.split("```\n")[1]
        self.assertEqual(result.stdout, block)

    def test_readme_quoted_outputs_are_real(self):
        readme = README.read_text()
        for line in [
            "examples/good.csv: OK",
            "OK — 1 file(s) checked, no delimiter problems.",
            "FAIL examples/bad.csv:2: row uses ; instead of ,",
            "FAIL examples/bad.csv:4: row uses ; instead of ,",
            "examples/quoted.csv: OK",
            "Checked 3 file(s), 2 problem(s) in 1 file(s).",
            "FAIL <stdin>:2: row uses ; instead of ,",
            "FAIL <stdin>:4: row uses ; instead of ,",
            "semi.csv: OK",
        ]:
            self.assertIn(line, readme, line)


class TestHygiene(unittest.TestCase):
    def test_no_placeholder_text(self):
        banned = ["TODO", "FIXME", "XXX", "coming soon", "lorem"]
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            if ".git" in path.parts or "__pycache__" in path.parts:
                continue
            if "tests" in path.parts:
                continue
            text = path.read_text(errors="replace")
            for word in banned:
                self.assertNotIn(word, text,
                                 f"{word} in {path.relative_to(ROOT)}")

    def test_no_absolute_paths(self):
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            if ".git" in path.parts or "__pycache__" in path.parts:
                continue
            if "tests" in path.parts:
                continue
            text = path.read_text(errors="replace")
            self.assertNotIn("/home/hatch", text,
                             f"absolute path in {path.relative_to(ROOT)}")
            self.assertNotIn("/Users/", text,
                             f"absolute path in {path.relative_to(ROOT)}")
            self.assertNotIn("/tmp/", text,
                             f"absolute path in {path.relative_to(ROOT)}")

    def test_stdlib_only_imports(self):
        allowed_src = {
            "argparse", "csv", "fnmatch", "io", "json", "os", "sys",
            "pathlib",
        }
        allowed_tests = allowed_src | {
            "ast", "json", "subprocess", "tempfile", "unittest",
            "csv_delimiter_checker",
        }
        for path, allowed in [(SRC, allowed_src),
                              (Path(__file__), allowed_tests)]:
            tree = ast.parse(path.read_text())
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(a.name.split(".")[0]
                                    for a in node.names)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imported.add(node.module.split(".")[0])
            self.assertTrue(imported <= allowed,
                            f"{path.name} imports non-stdlib: "
                            f"{imported - allowed}")
            self.assertNotIn("yaml", imported)

    def test_no_yaml_anywhere_in_source(self):
        text = SRC.read_text()
        self.assertNotIn("yaml", text)

    def test_no_secrets_in_repo(self):
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            if ".git" in path.parts or "__pycache__" in path.parts:
                continue
            if "tests" in path.parts:
                continue
            text = path.read_text(errors="replace").lower()
            for marker in ["api_key", "api-key", "password =", "secret ="]:
                self.assertNotIn(marker, text,
                                 f"possible secret in {path.relative_to(ROOT)}")

    def test_gitignore_env_first(self):
        lines = (ROOT / ".gitignore").read_text().splitlines()
        self.assertEqual(lines[0], ".env")

    def test_ci_runs_this_test_file(self):
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
        self.assertIn("actions/checkout", ci)
        self.assertIn("setup-python", ci)
        self.assertIn("test_csv_delimiter_checker.py", ci)
        self.assertIn("push", ci)
        self.assertIn("pull_request", ci)


if __name__ == "__main__":
    unittest.main()
