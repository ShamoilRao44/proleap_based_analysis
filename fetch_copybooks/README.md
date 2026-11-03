# fetch_copybooks

Copies the copybooks one COBOL program needs into `<program folder>/copybooks/`, by searching the whole codebase. Nested COPY statements are followed until no new copybooks appear. Uses only the Python standard library (3.8+), so nothing needs to be installed.

## Usage

```
python3 fetch_copybooks.py <program_file> <codebase_root> [--format fixed|variable|free] [--stub-missing]
```

Example:

```
mkdir -p ~/isolated/CUCO003
cp /data/codebase/<path>/CUCO003 ~/isolated/CUCO003/
python3 fetch_copybooks.py ~/isolated/CUCO003/CUCO003 /data/codebase --stub-missing
```

Result:

```
~/isolated/CUCO003/
  CUCO003
  copybooks/                 all copybooks found, flat (plus empty stubs with --stub-missing)
  copybook_report.json       found / missing / duplicates, with referencing file and line
  missing_copybooks.txt      one line per missing copybook: NAME <tab> referenced by
```

Exit code `0` means all copybooks were found, `2` means some are missing, and `1` means bad arguments.

## How it works

1. Reads the code area only. In `fixed` format that is columns 8-72; comment lines (`*` or `/` in column 7) and `*>` comments are skipped.
2. Finds `COPY name`, `COPY 'name'` and `COPY name OF/IN lib`, including statements split across lines. A `COPY` inside a string literal or inside a data name such as `WS-COPY-FLAG` is ignored.
3. Matches names without regard to case and ignores file extensions, so `COPY cpya` matches `CPYA`, `CpyA.cpy` and so on.
4. Iteration 1 handles the program's own COPY statements. Each later iteration scans only the copybooks copied in the previous one, and only names not already found or reported missing are looked up.
5. When one name matches several files, it prefers the file whose folder matches the `OF/IN` library, then a file without an extension, then the first in sorted order. All candidates are listed in the report so you can check the choice.

## Options

- `--stub-missing` creates an empty file for each copybook it cannot find, so the ProLeap parser does not stop at the first missing one. Leave it off if you only want the report.
- `--format` sets the source format. The default is `fixed` (mainframe layout). Use `variable` when code runs past column 72, or `free` for free-format source.

## Notes

- Copied files keep their original names. The summary lists the extensions found. Give those, plus `""` for no extension, to the parser as copybook extensions.
- `EXEC SQL INCLUDE` members (DCLGEN, SQLCA) are deliberately not fetched. The ProLeap parser does not expand them, so they are not needed to build the AST.
- Re-running is safe: existing files in `copybooks/` are overwritten.
