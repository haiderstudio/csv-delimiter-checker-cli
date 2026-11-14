# Sample output

Output of `sh examples/run-example.sh` — the checker run over the
whole `examples/` folder (3 files, 2 problems in 1 file):

```
FAIL examples/bad.csv:2: row uses ; instead of ,
FAIL examples/bad.csv:4: row uses ; instead of ,
examples/good.csv: OK
examples/quoted.csv: OK
Checked 3 file(s), 2 problem(s) in 1 file(s).
```

`examples/bad.csv` mixes delimiters: rows 2 and 4 use semicolons
while the header and row 3 use commas. `examples/good.csv` uses
commas on every row, and `examples/quoted.csv` is clean — the
semicolon and tab inside its quoted fields are values, not
delimiters, and the multi-line quoted field on lines 4–5 is one row.
