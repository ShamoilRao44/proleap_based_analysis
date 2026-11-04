# Step 3 build plan: scanners for CSD, JCL/PROC, BMS, DDL/DCLGEN, IMS and control cards

This document is a complete build instruction. Follow it exactly, in order. Every design decision has already been made. When something is not specified, choose the simplest option that satisfies the text and list it in the final report (section 14). If a test expectation in this document contradicts the algorithm text, follow the algorithm text and report the difference.

---

## 0. Rules for the implementer

1. **Test only on the AWS repo:** `C:\My Folder\TCS\aws-mainframe-modernization-carddemo`. Never run any tool from this step on `CardDemo-Cobol-main` or `cics-banking-sample-application-cbsa-July2024Refresh`, and do not open files in them. The user tests those manually. Everything that only exists there (DDL, DCLGEN, IMS, inline SQL, column-0 CSD, `INCLUDE`) is tested with the fixtures given in section 11.
2. **Do not modify** anything in `inventory/`, `fetch_copybooks/`, `cobol-ast-runner/`, `facts/`. New code goes into `scanners/` only. The scanners are self-contained: they must not import `facts_lib`.
3. **Python:** standard library only, Python 3.8. No type hints with generics (`list[str]`), no `match`, no walrus operator, no third-party packages.
4. All JSON is written with `json.dump(obj, f, indent=1, ensure_ascii=False)`, UTF-8, `newline="\n"`. All names (programs, DD names, datasets, tables, mapsets, transactions) are stored in **upper case**, except free text (descriptions, initial values, raw operand text).
5. Never commit. The user commits.
6. **Stop conditions.** Stop and report to the user (do not work around) if:
   - a check in section 10 fails and the cause is not a bug in the code you wrote;
   - the AWS inventory file `analysis_out/aws-carddemo/inventory.json` does not exist and running `python inventory/inventory.py "C:\My Folder\TCS\aws-mainframe-modernization-carddemo" --out analysis_out/aws-carddemo` does not create it.
7. Paths in this document are relative to `C:\My Folder\TCS\proleap_based_analysis` unless they start with a drive letter. Write temporary scripts only to the scratchpad directory of your session.
8. Output of the scanners goes to `<out>/facts/...` (the same `<out>` as steps 1 and 2). For the AWS test use `analysis_out/aws-carddemo`.

---

## 1. What gets built

```
scanners/
├── run_scanners.py                 driver (CLI)
├── README.md
├── scan_lib/
│   ├── __init__.py                 (empty)
│   ├── common.py                   shared helpers
│   ├── asm_stmt.py                 assembler-style statement reader (BMS, IMS)
│   ├── csd.py
│   ├── bms.py
│   ├── ims.py
│   ├── ddl.py                      DDL, DCLGEN and inline SQL
│   ├── utilities.py                IDCAMS, SORT, SDSF, TSO/DB2, PARM parsers
│   ├── jcl.py                      JCL and PROC scanner (symbols, DDs, steps, expansion)
│   ├── control.py                  control card files
│   ├── crosscheck.py               cross-checks for the report
│   └── report.py
└── tests/
    ├── __init__.py                 (empty)
    ├── test_common.py
    ├── test_csd.py
    ├── test_bms.py
    ├── test_ims.py
    ├── test_ddl.py
    ├── test_utilities.py
    └── test_jcl.py
docs/SCANNERS_SCHEMA.md             (new)
```

Data flow:

```
inventory.json ──► run_scanners.py ──► pass 1: PROC members (jcl.py)  ──┐
                                   ├─► pass 2: csd, bms, ims, ddl, control files
                                   └─► pass 3: JCL jobs (jcl.py, with PROC expansion) ──► facts/<kind>/<NAME>.json
                                                                        scan_index.json, scan_report.md
```

Output files under `<out>/facts/`:

| Folder | Content | Schema id |
|---|---|---|
| `csd/` | one file per CSD file | `csd-facts/1` |
| `jcl/` | one file per JCL member | `jcl-facts/1` |
| `proc/` | one file per PROC member | `jcl-facts/1` (kind `proc`) |
| `bms/` | one file per BMS source | `bms-facts/1` |
| `ddl/` | one file per `ddl` or `dclgen` file | `ddl-facts/1` |
| `ims/` | one file per DBD or PSB | `ims-facts/1` |
| `control/` | one file per control card file | `control-facts/1` |
| `scan_index.json`, `scan_report.md` | index and report | `scan-index/1` |

Assembler sources and macro libraries (`assembler`, `asm_macro`) are **not** scanned in this step.

Each facts file name is the member name (upper case file name without extension). If two files of the same kind have the same member name, the first (sorted by path) keeps `NAME`, the others become `NAME~2`, `NAME~3`. The `path` field inside the file always holds the real relative path.

---

## 2. Shared helpers

### 2.1 `scan_lib/common.py`

```python
def read_text(path)           # bytes -> utf-8, on UnicodeDecodeError latin-1
def split_lines(text)         # normalise \r\n and \r to \n, split, drop one trailing empty element
def write_json(path, obj)     # create parent dirs, indent=1, ensure_ascii=False, newline="\n"
def load_json(path)
def member_name(path)         # upper case base name without the last extension
def unquote(s)
def split_top(text, sep=",")
def take_operand_field(text)
def parse_params(text)
def paren_args(text)
def sub_params(value)
def cap(s, n)                 # s if len(s) <= n else s[:n] + "..."
```

Behaviour:

- `unquote(s)`: strip; if length ≥ 2 and first char equals last char and is `'` or `"`, return the inner text with each doubled quote character replaced by one; else return the stripped text.
- `split_top(text, sep=",")`: split `text` at `sep` characters that are outside parentheses and outside quotes. Quotes are `'...'` and `"..."`; a quote character toggles the quote state (so a doubled quote inside a literal toggles twice and is harmless). Parentheses are counted only outside quotes. Empty pieces are kept (needed for `DISP=(,CATLG)`). Returns `[]` if `text.strip()` is empty. Pieces are **not** stripped.
- `take_operand_field(text)`: the part of `text` before the first whitespace character that is outside quotes and parentheses (the rest is a comment).
- `parse_params(text)`: for each piece of `split_top(text)` (stripped, empty pieces skipped): if it matches `^([A-Za-z0-9#@$&._-]+)=(.*)$` (DOTALL) the item is `(KEY_UPPER, value_stripped)`, else `(None, piece)`. Returns a list of tuples in order.
- `paren_args(text)`: reads `text` left to right and returns `[(WORD_UPPER, arg_or_None)]`. Skip whitespace and commas. A word is `[A-Za-z0-9#@$_-]+`. After a word, skip whitespace; if the next character is `(`, read the balanced argument (parentheses inside quotes ignored) and store the text between the outer parentheses, stripped; otherwise the argument is `None`. Any other character is skipped.
- `sub_params(value)`: if `value` starts with `(` and its matching `)` is the last character, return the stripped pieces of `split_top(inner)`; else return `[value.strip()]`.

### 2.2 `scan_lib/asm_stmt.py`

`read_asm_statements(lines)` returns a list of `{"label", "op", "operands", "line", "end_line"}` for assembler-style source (BMS macros, IMS DBD/PSB). `line` and `end_line` are 1-based physical line numbers.

Algorithm, for physical line index `i` (0-based):
1. Skip lines that are blank, or start with `*`, or start with `.*`.
2. If the first character is not a space or tab, `label` = the first whitespace-delimited token (upper case) and the rest follows; otherwise `label` = `""`. `op` = the next token (upper case). `operands` starts as `take_operand_field(<rest after op>.lstrip())`.
3. The statement is **continued** if the physical line has length ≥ 72 and the character in column 72 (index 71) is not a space or tab. It is also continued (tolerant rule) if the piece taken so far ends with `,`, the next physical line exists, is not a comment, is not blank, and its first 15 characters are all spaces.
4. For each continuation line `nl`: take `nl[15:71]` if `len(nl) > 15` else `nl.strip()`; append `take_operand_field(that.lstrip())` to `operands`; decide again whether it is continued with the same two rules.
5. For the first line, only characters up to column 71 (index 70) are considered (`line[:71]`) before applying `take_operand_field`.
6. `end_line` is the line number of the last physical line used.

---

## 3. `scan_lib/csd.py`

```python
def parse_lines(lines, first_line=1)   # -> {"definitions": [...], "commands": [...]}
def scan_file(path, rec, root)         # -> facts dict (schema csd-facts/1)
def summarize(definitions)             # -> {"by_type": {TYPE: n}, "groups": [...]}
```

`parse_lines` algorithm:
1. A line is a comment if its stripped text starts with `*`, or is blank.
2. Statement keywords: `DEFINE DELETE ADD ALTER COPY APPEND REMOVE LIST INSTALL MOVE RENAME CHECK UPGRADE USERDEFINE EXTRACT INITIALIZE PRINT SCAN SERVICE VERIFY`. A non-comment line **starts a statement** if it matches `^\s*([A-Za-z]+)(?=\s|$)(.*)$`, the first word upper-cased is in the keyword list, and the remaining text does **not** match `^\s*\(` (this keeps attribute lines such as `DELETE(YES) READ(YES)` from starting a statement). Any other non-comment line continues the current statement. Lines before the first statement are ignored.
3. For each statement, `text` = its lines stripped and joined with one space. Record `line` (first line number, offset by `first_line - 1`) and `end_line`.
4. **DEFINE**: match `^(?i)DEFINE\s+([A-Z0-9]+)\s*\(\s*([^)]*?)\s*\)(.*)$` on `text`. If it does not match, record it as a command. Otherwise: `type` = group 1 upper, `name` = group 2 upper, rest = group 3. Attributes: `paren_args(rest)`; the key is the word (upper); the value is `unquote(arg)` for a string argument (an argument that is entirely one quoted literal) else the stripped argument text; a word without argument gets `True`; if a key repeats keep the first.
5. Definition object (all keys always present):
   `{"type", "name", "group", "description", "line", "end_line", "attrs", ...typed keys}` where `group` = `attrs.get("GROUP")` and `description` = `attrs.get("DESCRIPTION")`. Typed keys:
   - `TRANSACTION`: `"program"` = `attrs.get("PROGRAM")` upper (or null);
   - `PROGRAM`: `"language"` = `attrs.get("LANGUAGE")`, `"transid"` = `attrs.get("TRANSID")`;
   - `FILE`: `"dsname"` = `attrs.get("DSNAME")` (upper, or null);
   - `LIBRARY`: `"dsnames"` = list of the values of `DSNAME01` … `DSNAME16` that exist, upper;
   - `TDQUEUE`: `"queue_type"` = `attrs.get("TYPE")`;
   - `MAPSET`, other types: no typed keys.
6. Any statement that is not a DEFINE is added to `commands` as `{"verb", "text" (cap 200), "line"}`.

`summarize`: `by_type` counts per type (sorted keys), `groups` = sorted unique non-null groups.

`scan_file(path, rec, root)` returns:
```json
{"schema": "csd-facts/1", "name": "<member>", "path": "<relative path>", "source": "file",
 "definitions": [...], "commands": [...], "summary": {"by_type": {...}, "groups": [...]}, "warnings": []}
```
`name` is `rec["name"]`. `path` is `rec["path"]`.

---

## 4. `scan_lib/bms.py`

```python
def parse_lines(lines)      # -> list of mapset dicts
def scan_file(path, rec, root, symbolic_copybooks)   # -> facts dict (schema bms-facts/1)
```

`parse_lines` uses `read_asm_statements(lines)`. For each statement, `params = dict` built from `parse_params(operands)` (keys upper, first occurrence kept, positional items ignored).

- `op == "DFHMSD"`: if `params.get("TYPE", "").upper() == "FINAL"` → close the current mapset. Otherwise start a mapset: `{"name": label, "line", "attrs": params, "maps": []}`.
- `op == "DFHMDI"`: start a map in the current mapset: `{"name": label, "line", "size": [rows, cols] from SIZE=(r,c) (ints, or null), "attrs": params, "fields": []}`. If there is no current mapset, create one with name `""` and add the warning `"DFHMDI without DFHMSD"`.
- `op == "DFHMDF"`: a field of the current map. If there is no current map, add the warning `"DFHMDF without DFHMDI"` and skip it. Field object:
  - `name` = label or null; `line`;
  - `pos` = `[row, col]` from `POS=(r,c)` (ints) or null; `length` = int from `LENGTH` or null;
  - `attrb` = list of upper-case items of `sub_params(ATTRB)` (empty list if missing); `initial` = `unquote(INITIAL)` or null; `color`, `hilight` = the raw upper value or null;
  - `role`: `"input"` if `"UNPROT"` is in `attrb`; else `"output"` if `name` is not null; else `"label"` if `initial` is not null; else `"filler"`;
  - `attrs` = the full params dict.
- All other ops are ignored.
- A map gets, after parsing, `"field_count"`, `"named_fields"` (fields with a name), `"input_fields"` (role input), `"labels"` (role label).

`scan_file` returns:
```json
{"schema": "bms-facts/1", "name": "<member>", "path": "...", "mapsets": [ {name, line, attrs, maps:[...], symbolic_copybook} ],
 "summary": {"mapsets": n, "maps": n, "fields": n}, "warnings": []}
```
`symbolic_copybook` of a mapset: look up `mapset.name` in the dict `symbolic_copybooks` (upper copybook member name → relative path, built by the driver from inventory files of type `copybook` with subtype `bms_symbolic_map`); value is the path or null.

---

## 5. `scan_lib/ims.py`

```python
def parse_lines(lines)      # -> {"dbd": {...}|None, "psb": {...}|None, "warnings": []}
def scan_file(path, rec, root)   # -> facts dict (schema ims-facts/1)
```

Use `read_asm_statements`. Parameters: `params = parse_params(operands)` converted to a dict (first occurrence wins).

**DBD members:**
- `DBD`: `dbd = {"name": NAME, "access": upper items of sub_params(ACCESS), "line", "datasets": [], "segments": []}`.
- `DATASET` (label may be present, e.g. `DSG001`): append `{"label", "dd1": DD1, "dd2": DD2, "size": SIZE raw, "line"}` to `datasets`.
- `SEGM`: append `{"name": NAME, "parent": <see below>, "bytes": int(BYTES) or null, "rules": RULES raw, "pointer": POINTER raw, "line", "fields": [], "lchild": []}`. Parent: raw `PARENT` value; if it is `0` → null; else the first name found by regex `[A-Z0-9#@$]+` after stripping parentheses and commas (for `((PAUTSUM0,))` → `PAUTSUM0`).
- `FIELD` (belongs to the last segment): `NAME=(ACCNTID,SEQ,U)` → `{"name": first item, "seq": second item is SEQ (bool), "unique": third item == "U" (bool; for `M` false), "start": int(START), "bytes": int(BYTES), "type": TYPE, "line"}`. If `NAME` is a plain word, `seq` and `unique` are false.
- `LCHILD` (belongs to the last segment): `NAME=(PAUTINDX,DBPAUTX0)` → `{"segment": first, "dbd": second, "pointer": POINTER raw, "line"}`.
- `DBDGEN`, `FINISH`, `END`, `TITLE`, `PRINT` and anything else: ignored. A `SEGM`/`FIELD`/`LCHILD` before `DBD` adds the warning `"<op> before DBD"` and is skipped.

**PSB members:**
- `PCB` (label may be present): append to `pcbs`: `{"index": 1-based count, "label", "type": TYPE upper, "dbdname": DBDNAME, "procopt": PROCOPT, "keylen": int or null, "access_hint", "line", "segments": []}`. `access_hint` = `"update"` if `procopt` contains any of `A I R D`, else `"read"` if `procopt` is not empty, else null.
- `SENSEG`: append `{"name": NAME, "parent": parent (same rule as SEGM; `0` → null), "procopt": PROCOPT or null}` to the last PCB. Without a PCB: warning `"SENSEG before PCB"`.
- `PSBGEN`: `psb = {"name": PSBNAME, "lang": LANG, "cmpat": CMPAT, "line", "pcbs": pcbs}`.
- A PSB source whose `PSBGEN` is missing but which has PCB statements still gets a `psb` object with `name` = the member name and `line` null.

`scan_file` returns:
```json
{"schema": "ims-facts/1", "name": "<member>", "path": "...", "kind": "dbd"|"psb",
 "declared_name": "<DBD NAME or PSBNAME>", "dbd": {...}|null, "psb": {...}|null, "warnings": []}
```
`kind` is `"dbd"` if a `dbd` object exists, else `"psb"`.

---

## 6. `scan_lib/ddl.py`

```python
def strip_comments(text)            # remove /* ... */ and -- ... (outside quotes)
def split_statements(text)          # -> [(statement_text, first_line)]
def parse_sql(text, first_line=1)   # -> body dict (tables, indexes, views, other, alters, drops, dml)
def parse_dclgen(lines)             # -> body dict + host structure
def scan_file(path, rec, root)      # -> facts dict (schema ddl-facts/1)
```

### 6.1 Statement splitting

- `strip_comments`: replace every `/* ... */` (not nested, may span lines) by the same number of newline characters it contained; remove `--` to the end of line when the `--` is outside quotes. Preserve newlines so line numbers stay right.
- `split_statements(text)`: split at `;` outside single and double quotes. For each piece with non-blank text, the returned line number is 1 + the number of newlines before the first non-blank character of the piece (counted from the start of `text`). The text is returned stripped. `parse_sql(text, first_line)` adds `first_line - 1` to these numbers.

### 6.2 `parse_sql`

Statements are classified by their first words (upper case, whitespace collapsed for matching):

- `CREATE [GLOBAL TEMPORARY] TABLE [IF NOT EXISTS] <name> (` … matching `)` … rest.
  - `name`: strip double quotes; `qualified` = upper name; `schema` = the part before the last `.` (or null); `name` = the part after.
  - Body = text inside the outer parentheses; items = `split_top(body)` stripped, non-empty.
  - An item is a **constraint** if it matches (case-insensitive) `^(CONSTRAINT\s+\S+\s+)?(PRIMARY\s+KEY|FOREIGN\s+KEY|UNIQUE|CHECK)\b`.
    - `PRIMARY KEY (a, b)` → `primary_key` = list of upper column names.
    - `FOREIGN KEY (a) REFERENCES t (b)` → `foreign_keys.append({"columns", "ref_table", "ref_columns"})` (`ref_columns` empty list if omitted).
    - `UNIQUE (a, b)` → `unique.append([...])`. `CHECK` is ignored.
  - Otherwise the item is a **column**: `name` = first token (strip quotes, upper). Type: the rest matched with `^(LONG\s+VARCHAR|DOUBLE\s+PRECISION|[A-Z]+)(?:\s*\(\s*(\d+)\s*(?:,\s*(\d+))?\s*\))?` (case-insensitive, then upper); `type` = group 1, `length` = int(group 2) or null, `scale` = int(group 3) or null. `nullable` = False if the rest contains `NOT NULL`, else True. `default` = True if the rest contains `DEFAULT`, else False. An inline `PRIMARY KEY` in the rest adds the column to `primary_key`.
  - `tablespace` = group 1 of `\bIN\s+([A-Z0-9_.]+)` searched in the text after the closing parenthesis, or null.
  - Table object: `{"schema", "name", "qualified", "columns": [{name,type,length,scale,nullable,default}], "primary_key", "foreign_keys", "unique", "tablespace", "line", "host_structure": null}`.
- `CREATE [UNIQUE] INDEX <name> ON <table> ( <cols> )`: index object `{"name", "table" (upper, quotes removed), "unique": bool, "columns": [{"name", "order": "ASC"|"DESC"}] (order default ASC), "line"}`.
- `CREATE [OR REPLACE] VIEW <name> ... AS <select>`: `{"name", "tables": [...], "line"}` where `tables` are the table names found after `FROM` or `JOIN` in the select (regex `\b(?:FROM|JOIN)\s+([A-Z0-9_#@$."]+)`, de-duplicated, order kept).
- `CREATE DATABASE|TABLESPACE|STOGROUP|SCHEMA|ALIAS|SYNONYM|SEQUENCE|TYPE <name>` → `other.append({"kind", "name", "line"})`.
- `ALTER TABLE <name> ...` → `alters.append({"table", "text" (cap 200), "line"})`.
- `DROP <kind> <name>` → `drops.append({"kind", "name", "line"})`.
- `INSERT INTO t`, `UPDATE t`, `DELETE FROM t`, `SELECT ... FROM t` → `dml.append({"kind": "insert|update|delete|select", "tables": [{"name", "op"}], "line"})`; ops: insert → `insert`, update → `update`, delete → `delete`, tables found after `FROM`/`JOIN` → `read`. (For delete/update, tables after `FROM`/`JOIN` are `read`.)
- Everything else (`SET`, `GRANT`, `COMMIT`, `CONNECT`, …) is ignored.

The body dict is `{"tables": [], "indexes": [], "views": [], "other": [], "alters": [], "drops": [], "dml": []}`.

### 6.3 `parse_dclgen(lines)` (DCLGEN member, fixed format)

1. Code lines: for each line, the content is `line[7:72]`; skip the line if column 7 (index 6) is `*` or `/`, or the content is blank.
2. Join the content of all code lines with `\n`. Find `EXEC SQL DECLARE <name> TABLE ( ... ) END-EXEC` with the regex `(?is)EXEC\s+SQL\s+DECLARE\s+(\S+)\s+TABLE\s*\((.*)\)\s*END-EXEC`. Parse the table exactly like `CREATE TABLE` columns (same column parser) with `name`/`qualified`/`schema` from group 1. If there is no match, the body has no tables and the warning `"no DECLARE TABLE found"` is returned.
3. Host structure: the code lines after the one that contains `END-EXEC`. For each line match `^\s*(\d{2})\s+([A-Z0-9-]+)\s*(.*?)\.\s*$` (upper-cased text). `PIC` = regex `\bPIC(?:TURE)?\s+(\S+)` on the rest; `usage` = regex `\b(COMP(?:UTATIONAL)?(?:-[1-5])?|BINARY|PACKED-DECIMAL)\b` on the rest. Collect `fields = [{"level": int, "name", "pic", "usage"}]`; the structure name is the name of the first level-01 line. Result `host_structure = {"name", "fields"}`.
4. `host_var` per column: the host field whose name equals the column name with `_` replaced by `-` (first match, level ≠ 49), else null. Add `"host_var"` to every column of this table (null when no match).

### 6.4 `scan_file`

- `rec["type"] == "dclgen"` → `kind = "dclgen"`, body from `parse_dclgen(lines)`.
- Otherwise `kind = "ddl"`, body from `parse_sql(strip_comments(text))`.

Returns `{"schema": "ddl-facts/1", "name", "path", "kind", ...body keys..., "summary": {"tables": n, "indexes": n, "views": n}, "warnings": []}`.

---

## 7. `scan_lib/utilities.py`

All functions take a list of text lines (the inline data of a DD) and return plain lists/dicts. Common preprocessing, `join_continued(lines, markers)`: remove `/* ... */` comments (they may span lines); a line whose right-stripped text ends with one of the characters in `markers` (for example `"-+"`) is joined with the next line (the marker removed, one space inserted); returns a list of `(first_line_index, text)`.

### 7.1 `idcams_parse(lines)`

Use `join_continued(lines, "-+")`. Skip empty logical lines. The verb is the first word, upper. Handled verbs: `DEFINE DELETE REPRO LISTCAT PRINT ALTER IMPORT EXPORT BLDINDEX VERIFY EXAMINE`. Logical lines starting with `IF`, `ELSE`, `SET`, `DO`, `END`, `PARM`, `CANCEL` are ignored. Any other first word is ignored.

Each command is an object with all of these keys (null / empty when not applicable):
`{"verb", "subtype", "name", "names", "object_type", "infile", "outfile", "indataset", "outdataset", "attrs", "text", "line"}`.

- `text` = the logical line (cap 300); `line` = the first physical line index of the logical line + 1 (index within `lines`, the caller adds its own offset).
- `DEFINE <second word> ...`: `subtype` = second word upper, normalised: `GENERATIONDATAGROUP` → `GDG`, `ALTERNATEINDEX` → `AIX`. `names` = all matches of `NAME\s*\(\s*([^)\s]+)\s*\)` (upper, in order); `name` = the first. `attrs` (dict, only keys that are present): `KEYS` → `[len, offset]` (ints) from `KEYS\s*\(\s*(\d+)\s+(\d+)\s*\)`; `RECORDSIZE` → `[avg, max]`; `LIMIT` → int; `RELATE` → name; `ORGANIZATION` → one of `INDEXED`, `NONINDEXED`, `NUMBERED`, `LINEAR` if that word appears (as a standalone word).
- `DELETE`: after the verb, the next token is the name (if it starts with `(`, `names` = the words inside the parentheses and `name` = the first); `object_type` = the first standalone word among `CLUSTER GDG GENERATIONDATAGROUP NONVSAM AIX ALTERNATEINDEX PATH USERCATALOG PAGESPACE` found after the name (`ALTERNATEINDEX` → `AIX`, `GENERATIONDATAGROUP` → `GDG`), else null. `subtype` = `object_type`.
- `REPRO`: `infile` ← `(?:INFILE|IFILE)\s*\(\s*([^)\s]+)`; `outfile` ← `(?:OUTFILE|OFILE)`; `indataset` ← `(?:INDATASET|INDS)`; `outdataset` ← `(?:OUTDATASET|OUTDS)`. All upper.
- `PRINT`: `infile` / `indataset` as for REPRO.
- `LISTCAT`, `ALTER`, `IMPORT`, `EXPORT`, `BLDINDEX`, `VERIFY`, `EXAMINE`: `name` = value of the first `ENTRIES\s*\(([^)\s]+)` or `LEVEL\s*\(...` or, for `ALTER`/`EXPORT`/`IMPORT`/`VERIFY`, the first token after the verb; `text` as above.

### 7.2 `sort_parse(lines)`

Remove `/* ... */` comments and lines whose first non-space character is `*`. Join a line with the next when the right-stripped line ends with `,`. Each logical line, stripped, whose first word (upper) is one of `SORT MERGE INCLUDE OMIT INREC OUTREC OUTFIL SUM OPTION MODS RECORD ALTSEQ END` becomes `{"verb", "text" (cap 500), "fields": <raw text inside FIELDS=(...) or null>}`. `fields` is only set for `SORT` and `MERGE` (regex `FIELDS\s*=\s*\((.*)\)` on the logical line, DOTALL). Lines with any other first word (for example the data of `SYMNAMES`) are ignored.

### 7.3 `sdsf_parse(lines)`

For each line (inline data of `ISFIN`): `m = re.search(r"/F\s+(\w+)\s*,\s*'([^']*)'", line, re.I)`. If it matches, `region` = group 1 upper, `cmd` = group 2. Then `c = re.search(r"CEMT\s+(SET|INQUIRE|PERFORM)\s+([A-Z]+)\s*\(\s*([^)]*?)\s*\)\s*([A-Z]*)", cmd, re.I)`. If it matches, emit `{"region", "verb": group 1 upper, "resource_type", "resource": group 3 upper, "action", "line": index+1}`. `resource_type` map (key = group 2 upper): `FIL`/`FILE` → `FILE`; `PROG`/`PROGRAM` → `PROGRAM`; `TRAN`/`TRANSACTION` → `TRANSACTION`; `TDQ`/`TDQUEUE` → `TDQUEUE`; anything else → the word itself. `action` map (group 4 upper): `CLO`/`CLOSED` → `CLOSE`; `OPE`/`OPEN` → `OPEN`; `ENA`/`ENABLED` → `ENABLE`; `DIS`/`DISABLED` → `DISABLE`; `NEW`/`NEWCOPY` → `NEWCOPY`; empty → null; anything else → the word itself.

### 7.4 `tso_parse(lines)`

Use `join_continued(lines, "-")`. For each logical line: `RUN\s+PROGRAM\s*\(\s*(\w+)\s*\)` → `{"program": group 1 upper, "plan": value of PLAN\s*\(\s*(\w+) in the same logical line (upper) or null, "line"}`. Also `DSN\s+SYSTEM\s*\(\s*(\w+)\s*\)` sets `subsystem` for all later runs in the same call. Returns a list of `{"program", "plan", "subsystem", "line"}`.

### 7.5 `parm_invokes(program, parm)`

For `program == "DFSRRC00"`: strip surrounding quotes and parentheses from `parm`, split on commas, strip; items = `[region_type, program, psb, ...]`; return `[{"program": items[1].upper(), "psb": items[2].upper() if present else None, "via": "DFSRRC00 PARM"}]` when `items` has at least 2 elements and `items[0].upper()` is in `DLI BMP DBB`; else `[]`. For every other program return `[]`.

---

## 8. `scan_lib/jcl.py`

```python
UTILITIES = {"IDCAMS", "SORT", "ICEMAN", "DFSORT", "SYNCSORT", "IEBGENER", "IEBCOPY", "IEFBR14", "IKJEFT01",
             "IKJEFT1A", "IKJEFT1B", "DFHCSDUP", "DSNTEP2", "DSNTEP4", "DSNUTILB", "SDSF", "IEBCOMPR",
             "IEBUPDTE", "IEHLIST", "IEHPROGM", "ADRDSSU", "FTP", "DFSRRC00", "IRXJCL", "DFHCSDUP"}
BUILD_PROGRAMS = {"IGYCRCTL", "ASMA90", "ASMA90X", "IEWL", "HEWL", "IEWBLINK", "DSNHPC", "DFHECP1$", "DFHEAP1$",
                  "DFHEBRZP", "DFHYITVL", "CCNDRVR", "EDCCOMP"}
LIBRARY_DDS = {"STEPLIB", "JOBLIB", "SYSLIB", "DFHRPL", "STEPCAT", "JOBCAT"}
SYSTEM_SYMBOLS = {"SYSUID", "SYSJOBNAME", "SYSNAME", "SYSPLEX", "SYSCLONE", "SYSJOBID", "LYR", "LMON", "LDAY",
                  "LHR", "LMIN", "LSEC", "YR4", "YR2", "MON", "DAY", "HR", "MIN", "SEC", "HRS", "JDAY"}

def read_cards(lines)                    # -> list of cards
def parse_member(lines, name, ctx)       # -> raw structure (unexpanded)
def expand(raw, ctx)                     # -> facts dict with flat_steps
def scan_file(path, rec, root, ctx)      # -> facts dict (schema jcl-facts/1)
```

`ctx` is a dict built by the driver: `{"procs": {UPPER_NAME: raw_structure}, "members": {UPPER_MEMBER: [lines]}}`. `procs` is keyed by member name **and** by declared PROC name (member name wins when both match different files). `members` holds the lines of every inventory file of type `jcl`, `proc`, `control_card`, `other_source` or `unknown`, keyed by upper member name (used for `INCLUDE`).

### 8.1 `read_cards(lines)`

Returns cards `{"line", "end_line", "name", "op", "operands", "inline"}`; `inline` is null or `{"lines": [(line_no, text), ...], "dlm": None|"xx"}`.

For physical line `i` (line number `i+1`), `raw = line.rstrip("\r\n")`:
1. `raw.startswith("//*")` → comment, skipped (it does not end a pending continuation).
2. `raw.startswith("//")`: `text = raw[:71]` (columns 1–71 only).
   - If `text.strip() == "//"` → card with `op = ""` (null statement), name `""`.
   - If a card is **open** (previous card's operand field ended with `,`, see below) and `raw[2:3] in (" ", "")`: this is a continuation line: `piece = take_operand_field(text[2:].lstrip())` is appended to the open card's `operands`; `end_line` is updated; re-evaluate whether it is still open.
   - Otherwise a new statement: `m = re.match(r"^//(\S*)\s+(\S+)(?:\s+(.*))?$", text)`. If `text[2:3]` is a space the name is empty and the pattern is applied to `"//" + "" + text[2:]` (that is, `name = ""`, `op` = first token). Unmatched lines are skipped. `name` and `op` are upper-cased. For `op in ("IF", "ELSE", "ENDIF", "THEN")` the `operands` are the whole remaining text, stripped, and the card is never open. For every other op `operands = take_operand_field(rest.lstrip())`.
   - A card is **open** after processing a line when its operand field (the last piece) ends with `,` and `op` is not one of the IF family.
3. `raw.startswith("/*")` (and not inside inline data): delimiter card `op = "DELIM"`.
4. Any other line outside inline data is ignored.

**Inline data:** after a `DD` card whose first positional operand is `*` or `DATA` (or whose `operands` text, split with `split_top`, contains an item equal to `*` or `DATA`), the following lines until the end of data belong to that card's `inline`. Optional `DLM=xx` operand: `dlm = xx` (without quotes). End of data: with `dlm` set, a line that starts with `dlm` ends the data and is consumed; without `dlm`, a line starting with `/*` ends the data and is consumed, and a line starting with `//` ends the data and is not consumed. Data lines are stored as `(line_no, raw[:80])`.

### 8.2 Symbols

- `subst(text, symbols)` → `(new_text, unresolved_names)`: replace each match of `&([A-Za-z#@$][A-Za-z0-9#@$]*)\.?` (symbol name upper-cased for the lookup; the single optional `.` that terminates the name is consumed) by `symbols[name]` if present; otherwise leave the match unchanged and add the name to `unresolved_names` unless it is in `SYSTEM_SYMBOLS`. `&&NAME` (two ampersands) is a temporary dataset, not a symbol: the regex must not match when the `&` is preceded or followed by another `&` (use `(?<!&)&(?!&)`). Resolved values may themselves contain symbols: repeat the substitution up to 3 times.
- `SET` card: `parse_params(operands)` items `(KEY, value)` update the symbol table (`KEY` upper, value unquoted, then `subst` against the current table).

### 8.3 Operands of statements

`params(card)` = list of `(KEY|None, value)` from `parse_params(card["operands"])`. Helper `pget(params, key)` returns the first value for `key`, else null.

**JOB:** `{"name": card.name, "line", "class": CLASS, "msgclass": MSGCLASS, "notify": NOTIFY, "programmer": the second positional item (unquoted) or null, "accounting": the first positional item or null}`.

**EXEC:**
- `PGM=x` → `kind = "program"`, `program = x.upper()` (after `subst`); `PROC=x` → `kind = "proc"`, `proc = x.upper()`; neither, but a positional first item → `kind = "proc"`, `proc` = that item upper.
- `parm` = `unquote(PARM)` after `subst`; `cond` = raw `COND`; `region` = `REGION`; `time` = `TIME`.
- `params` (dict): every other `KEY=value` item except `PGM PROC PARM COND REGION TIME ACCT DYNAMNBR PERFORM ADDRSPC CCSID RD`; value unquoted. These are symbolic parameters for a proc.

**DD:** the DD object (all keys always present):

```json
{"name": "TRANFILE", "line": 12, "concat": false,
 "dsn_raw": "AWS.M2.X", "dsn": "AWS.M2.X", "member": null, "generation": null,
 "temp": false, "null_file": false, "referback": null,
 "disp": {"raw": "SHR", "status": "SHR", "normal": null, "abnormal": null},
 "sysout": false, "dummy": false, "inline": null,
 "mode_hint": "read", "dcb": null, "unit": null, "ddname_ref": null,
 "override_of": null, "added_by_override": false, "unresolved_symbols": []}
```

- `dsn_raw` = value of `DSN` or `DSNAME` (unquoted), else null. `dsn` = `dsn_raw` after `subst` (upper). Then:
  - `referback`: if the value starts with `*.` → `referback` = the rest upper (`STEP.DD`), `dsn` = null.
  - `temp`: `dsn` starts with `&&` → true.
  - `null_file`: `dsn == "NULLFILE"` → true.
  - member / generation: if `dsn` matches `^(.+)\(([^)]+)\)$`: group 2 matching `^[+-]?\d+$` → `generation` = group 2 (string, for example `"+1"`, `"0"`); otherwise `member` = group 2 upper; in both cases `dsn` = group 1.
- `disp`: from `DISP`: raw value; `sub_params(raw)` pieces (empty pieces stay empty strings): `status` = first (upper, or null if empty), `normal` = second (or null), `abnormal` = third (or null). If `DISP` is absent, `disp` is null.
- `sysout`: `SYSOUT` present. `dummy`: a positional item `DUMMY` present, or `DSN=NULLFILE` is **not** dummy (keep `null_file` separate).
- `inline`: from the card's inline data: `{"kind": "*" or "DATA", "lines": count, "dlm": dlm, "symbols": value of SYMBOLS or null}`; null if none.
- `dcb`: from `DCB`: pieces of `sub_params`; `KEY=value` pieces for `LRECL RECFM BLKSIZE DSORG` give `{"lrecl": int|null, "recfm", "blksize": int|null, "dsorg", "ref": <piece starting with "*." or null>}`; null if no DCB. `unit` = `UNIT`. `ddname_ref` = `DDNAME`.
- `mode_hint` (first rule that applies): `dummy` → `"dummy"`; `sysout` → `"sysout"`; `inline` → `"inline"`; name in `LIBRARY_DDS` → `"library"`; `disp.normal == "DELETE"` → `"delete"`; `disp.status == "NEW"` → `"create"`; `"MOD"` → `"append"`; `"SHR"` → `"read"`; `"OLD"` → `"old"`; otherwise `"unknown"`.
- `unresolved_symbols`: the unresolved names reported by `subst` for `dsn_raw`.
- A DD card with an empty `name` is a concatenation: its `name` is taken from the previous DD of the same step, `concat` = true.
- A DD whose name contains `.` is an **override** when the current step is a proc step: `override_of = {"proc_step": part before the first dot, "dd": the rest after the last dot}` and the DD's `name` is the `dd` part.

### 8.4 `parse_member(lines, name, ctx)`

Walk the cards in order and build:

```python
raw = {"kind": "job"|"proc"|"fragment", "jobs": [...], "symbols": {...}, "defaults": {...}, "jcllib": [],
       "includes": [], "instream_procs": {NAME: raw_proc}, "steps": [], "job_dds": [], "warnings": [],
       "declared_name": None}
```

- `JOB` → append the JOB object to `jobs`; the symbol table is **not** reset (first job's symbols apply to the rest of the file). Steps carry `job` = the name of the current job (or null).
- `PROC` card (name = proc name): `declared_name` = card name; `defaults` = dict from `parse_params(operands)` (value unquoted). If it appears before the first JOB or before any step and the member has no JOB card, the member `kind` is `"proc"`. If a PROC card appears after a JOB card, it starts an **in-stream proc**: the steps until the matching `PEND` go to `instream_procs[NAME]` (a nested `raw` with `defaults` and `steps`).
- `PEND` ends an in-stream proc (or is ignored in a proc member).
- `kind`: `"job"` if at least one JOB card exists; else `"proc"` if a PROC card exists; else `"fragment"`.
- `SET`, `JCLLIB` (`jcllib` = upper items of `sub_params(ORDER)` unquoted), `INCLUDE` (see below).
- `INCLUDE MEMBER=X`: `member = X.upper()`; look it up in `ctx["members"]`; if found, parse its lines with `read_cards` and process its cards **in place** (only `SET`, `INCLUDE` cards are used; nesting depth ≤ 3); append `{"member", "found": bool}` to `includes`.
- `IF` / `ELSE` / `ENDIF`: maintain a stack. `IF` pushes the operand text up to the last ` THEN` (case-insensitive; if there is no THEN keep the whole text), stripped, cap 200; `ELSE` replaces the top by `"NOT (" + top + ")"`; `ENDIF` pops. `if_context` of a step = copy of the stack at the time of its EXEC.
- `EXEC` → a step object (all keys always present):
  ```json
  {"index": 1, "name": "STEP15", "line": 3, "job": "POSTTRAN", "kind": "program", "program": "CBTRN02C",
   "proc": null, "parm": null, "cond": null, "region": null, "params": {}, "if_context": [],
   "utility": false, "build": false, "dds": [], "overrides": [], "invokes": [], "utility_data": {},
   "proc_found": null, "expanded": null, "expanded_from": null, "via_step": null, "warnings": []}
  ```
  `index` = 1-based position among the EXEC cards of the member. `utility` = `program in UTILITIES`; `build` = `program in BUILD_PROGRAMS`.
- `DD` → added to the current step's `dds`; if the current step is a proc step and the DD is an override (qualified name), to its `overrides` instead. A DD before the first EXEC goes to `job_dds`.
- All `dds` get `subst` applied to `dsn_raw` using the symbols known at that point (job symbols; for DDs inside a proc member, only the proc `defaults` plus job symbols). Names that remain unresolved are kept in the DD's `unresolved_symbols`.
- **Utility data** (computed when the step's DDs are complete, that is, when the next EXEC/PEND/JOB card or the end of the member is reached). For each DD that has inline data, depending on the step program and the DD name:
  - `IDCAMS`, DD `SYSIN`: `utility_data["idcams_commands"] = idcams_parse(lines)`; each command's `line` gets the DD's first data line number added (`line = first_data_line + command_line - 1`).
  - `SORT`, `ICEMAN`, `DFSORT`, `SYNCSORT`, DD `SYSIN`: `utility_data["sort_statements"] = sort_parse(lines)`.
  - `SDSF`, DD `ISFIN`: `utility_data["sdsf_commands"] = sdsf_parse(lines)`.
  - `DFHCSDUP`, DD `SYSIN`: `utility_data["inline_csd"] = csd.parse_lines(lines, first_line=<first data line>)`, but only the `definitions` and `commands` (as a dict with those two keys). If the DD has `SYMBOLS` set (any value), apply `subst` to every data line before parsing, using the current symbols.
  - `IKJEFT01`, `IKJEFT1A`, `IKJEFT1B`, DD `SYSTSIN`: `utility_data["tso_runs"] = tso_parse(lines)`; and `invokes` gets `{"program", "plan", "via": "SYSTSIN RUN PROGRAM"}` for each run.
  - `IKJEFT01`, `IKJEFT1A`, `IKJEFT1B`, `DSNTEP2`, `DSNTEP4` with a DD `SYSIN` that has inline data: `utility_data["inline_sql"] = ddl.parse_sql(ddl.strip_comments("\n".join(lines)), first_line=<first data line>)`; keep the keys `tables`, `indexes`, `views`, `other`, `alters`, `drops`, `dml` only.
  - Any step: `invokes` gets `{"program": program, "via": "EXEC PGM"}` when `kind == "program"` and the program is not a utility and not a build program; `parm_invokes(program, parm)` results are added too.
- **Warnings:** a step name used twice in one job → warning `"duplicate step name <NAME>"` on the second step; a proc step whose proc cannot be found is handled in expansion.

### 8.5 `expand(raw, ctx)` and `scan_file`

`scan_file(path, rec, root, ctx)` reads the file, calls `parse_member`, then for `kind == "job"` (and for `fragment`) builds the final facts with `flat_steps`. For `kind == "proc"` it returns the unexpanded structure (`flat_steps = null`).

Expansion of a proc step `s` (kind `"proc"`):
1. Find the proc: first `raw["instream_procs"][s.proc]`, then `ctx["procs"][s.proc]`. If not found: `s.proc_found = False`, `s.expanded = null`, nothing is added to `flat_steps` for it (the step itself is added to `flat_steps` so that it is not lost, with `kind` still `"proc"`). If found: `s.proc_found = True`.
2. Symbols for the expansion: start from the job's symbol table, overlay the proc `defaults`, overlay `s.params` (each value after `subst` with the job symbols).
3. For each step `ps` of the proc (deep-copied): `name` = `s.name + "." + ps.name`; `expanded_from` = the proc name; `via_step` = `s.name`; `job` = `s.job`; `if_context` = `s.if_context` + `ps.if_context`; `program`, `parm`, and every DD's `dsn_raw` are re-substituted with the expansion symbols and the DD fields `dsn`, `member`, `generation`, `temp`, `null_file`, `referback`, `unresolved_symbols`, `mode_hint` are recomputed with the same rules as in 8.3.
4. Overrides: for each override DD of `s` whose `override_of.proc_step` equals `ps.name` (original proc step name): if `ps` has a DD with the same name (case-insensitive) the override **replaces it entirely** (keep the position); otherwise it is appended with `added_by_override = true`. `dsn_raw` of the override is substituted with the **job** symbols plus `s.params`.
5. If `ps.kind == "proc"` the expansion is applied recursively (depth ≤ 3; a proc name already on the expansion stack stops the recursion with the warning `"recursive proc <NAME>"` on that step).
6. `s.expanded` = the list of expanded steps (flat, in order, including recursively expanded ones). `flat_steps` receives the expanded steps instead of `s`.
7. Non-proc steps are added to `flat_steps` as they are (deep copies). `index` of `flat_steps` entries is renumbered 1..n.
8. **Referbacks:** for every DD in `flat_steps` with `referback = "STEP.DD"`: if an earlier flat step with that name (or whose name ends with `.STEP`) has a DD with that name and a `dsn`, copy its `dsn`, `member`, `generation` into the DD and set `referback_resolved = true`; else `referback_resolved = false`.

Final facts for a job or fragment:

```json
{"schema": "jcl-facts/1", "name": "<member>", "path": "...", "kind": "job",
 "declared_name": "<job name or proc name or null>", "jobs": [...], "symbols": {...}, "jcllib": [],
 "includes": [], "instream_procs": ["NAME", ...], "steps": [...], "flat_steps": [...], "job_dds": [...],
 "programs_run": ["CBTRN02C", ...], "procs_used": [{"name": "REPROC", "found": true}],
 "utilities_used": ["IDCAMS", ...], "datasets": [...], "unresolved_symbols": [...],
 "summary": {"steps": n, "flat_steps": n, "dds": n}, "warnings": []}
```

- `programs_run`: sorted unique `program` of flat steps with `kind == "program"` that are not utilities and not build programs, plus the `program` of every `invokes` entry (also from utility steps).
- `utilities_used`: sorted unique programs of flat steps that are in `UTILITIES`.
- `datasets`: one entry per distinct `(dsn, generation)` among all DDs of `flat_steps` and `job_dds` that have a `dsn` and are not `temp`, not `null_file`, not `dummy`, not `sysout`: `{"dsn", "generation", "refs": [{"step": flat step name, "dd": DD name, "member": member or null, "mode_hint": ..., "disp": raw DISP or null}]}`; sorted by `dsn`.
- `unresolved_symbols`: sorted unique names from all DDs of flat steps.
- For a proc member: `kind = "proc"`, `declared_name` = the PROC name, `defaults`, `steps`, `flat_steps = null`, `programs_run` computed from its own steps (unexpanded), `procs_used` from its own proc steps (`found` looked up in `ctx["procs"]`).

Data written for steps/DDs inside `steps` keeps all keys from 8.4 (with the unexpanded view); `flat_steps` has the same keys.

---

## 9. Control cards, driver, report

### 9.1 `scan_lib/control.py`

`scan_file(path, rec, root)`:
- Read the lines; remove `/* ... */` comments.
- If any logical line (after `join_continued(lines, "-+")`) starts with one of the IDCAMS verbs (`REPRO DEFINE DELETE LISTCAT PRINT ALTER IMPORT EXPORT BLDINDEX VERIFY`) → `kind = "idcams"`, `commands = idcams_parse(lines)`.
- Else if `sort_parse(lines)` is not empty → `kind = "sort"`, `statements = sort_parse(lines)`.
- Else `kind = "unknown"`, `head` = the first 5 non-blank lines.

Returns `{"schema": "control-facts/1", "name", "path", "kind", "commands" | "statements" | "head", "warnings": []}`.

### 9.2 `run_scanners.py`

```
python3 scanners/run_scanners.py --inventory <analysis_dir>/inventory.json --out <analysis_dir>
                                 [--codebase ROOT] [--only NAME[,NAME...]]
```

Steps:
1. Load the inventory. `root` = `--codebase` or `meta.codebase_root`. Records with `encoding` in (`ebcdic`, `binary`) are skipped and listed in the report (`skipped_encoding`).
2. Build indexes:
   - `symbolic_copybooks`: upper `name` → `path` of inventory files with `type == "copybook"` and `subtype == "bms_symbolic_map"`.
   - `members`: for inventory types `jcl`, `proc`, `control_card`, `other_source`, `unknown`: upper member name → lines of the file (read lazily and cached).
   - Source program names: upper `name` and upper `declared_name` of all files of type `cobol_program`, `assembler`.
3. **Pass 1 (PROC members):** for each file of type `proc`: `jcl.parse_member(lines, name, ctx)`; store the raw structure in `ctx["procs"]` under the upper member name; and under the upper declared PROC name if that key is not already taken by a member-name entry. (A member-name entry always overwrites a declared-name entry.) Process the files sorted by path.
4. **Pass 2:** scan every file of type `csd`, `bms`, `ims_dbd`, `ims_psb`, `ddl`, `dclgen`, `control_card` with the matching module.
5. **Pass 3:** scan every file of type `jcl` and `proc` with `jcl.scan_file` and write the results (proc files now through `scan_file`, which re-parses them; it must produce the same structure as in pass 1).
6. Write each result to `<out>/facts/<folder>/<NAME>.json` (folder: `csd`, `jcl`, `proc`, `bms`, `ddl`, `ims`, `control`; DBD/PSB → `ims`; dclgen → `ddl`). A scanner that raises an exception: log the traceback to `<out>/facts/logs/scan_errors.log`, record status `error`, continue.
7. Write `<out>/facts/scan_index.json`: `{"schema": "scan-index/1", "generated", "codebase_root", "entries": [{"kind", "name", "facts_name", "path", "facts_file", "status", "summary"}]}`; `summary` = the `summary` dict of the facts (or `{}`), `status` is `ok`, `error` or `skipped_encoding`.
8. Write `<out>/facts/scan_report.md` (section 9.3).
9. Print `[scan] N files: K ok, E errors, S skipped` and exit 0.

### 9.3 Report (`scan_lib/report.py`, `scan_lib/crosscheck.py`)

`scan_report.md` sections, in this order:

1. `# Scan report: <codebase_root>` and a line with the time and the number of files.
2. **Summary by kind:** table `| Kind | Files | Errors | Skipped |` for csd, jcl, proc, bms, ddl, ims, control; then a line `Not scanned by this step: assembler N, asm_macro N`.
3. **CSD:** per CSD file (and per JCL with inline CSD): counts per definition type.
4. **JCL:** table `| Member | Kind | Steps | Flat steps | Programs run | Procs not found | Unresolved symbols |`.
5. **Cross-checks** (each as a sub-section; write `none` when the list is empty; sections C6–C9 are written only if `<out>/facts/cobol/*.json` exist, otherwise one line `skipped: no COBOL facts found`):
   - **C1 CSD programs without source:** for every PROGRAM definition in CSD files (and, in a separate list, in inline CSDs of JCL) whose name is not in the source program names. Columns: file, program.
   - **C2 CSD transactions whose program has no PROGRAM definition in the same CSD file.**
   - **C3 Mapsets**, three lists: (a) MAPSET definitions in CSD **files** without BMS source; (b) MAPSET definitions in **inline** CSDs of JCL without BMS source (informational); (c) BMS mapsets without any MAPSET definition in CSD files or inline CSDs.
   - **C4 JCL programs not in the codebase:** flat steps with `kind == "program"`, not utility, not build, whose program is not in the source program names, plus `invokes` programs not in the source names. Columns: job, step, program.
   - **C5 Procs not found:** job, step, proc name.
   - **C6 CICS files used by COBOL but not defined in any CSD FILE:** from the COBOL facts, every resource with `kind == "cics_file"`, the values of `name_resolved`; compared with all CSD FILE names (files and inline). Columns: program, file.
   - **C7 Batch DD names:** for every flat step whose program has COBOL facts: `expected` = set of `files_io[].dd`; `present` = set of DD names of the step; list (a) expected but missing, (b) present but not expected, ignoring DDs with `mode_hint` in (`library`, `sysout`, `dummy`) and names starting with `SYS`.
   - **C8 Mapsets used by COBOL without BMS source and without CSD MAPSET:** values of `mapset_resolved` of resources with `kind == "map"`.
   - **C9 DB2 tables used by COBOL but not defined in any DDL, DCLGEN or inline SQL:** values of `name_resolved` of `db2_table` resources, compared with `qualified` and `name` of all tables found (files and inline SQL); informational.
6. **Unresolved JCL symbols:** table member → names.
7. **Warnings:** count per scanner; list of the first 50 warnings with their member.

---

## 10. Task order and acceptance checks

| Task | Content | Done when |
|---|---|---|
| 3.1 | `common.py`, `asm_stmt.py`, `csd.py`, `test_common.py`, `test_csd.py` | Checks S1 and unit tests pass |
| 3.2 | `bms.py`, `ims.py`, `test_bms.py`, `test_ims.py` | Check S2 and unit tests pass |
| 3.3 | `ddl.py`, `test_ddl.py` | Unit tests pass |
| 3.4 | `utilities.py`, `test_utilities.py` | Unit tests pass |
| 3.5 | `jcl.py`, `control.py`, `test_jcl.py` | Checks S3–S9 and unit tests pass |
| 3.6 | `crosscheck.py`, `report.py`, `run_scanners.py` | Checks S10–S12 pass |
| 3.7 | docs, final report | Section 12 and 14 delivered |

Run all tests with `python -m unittest discover -s scanners/tests -t scanners`.

Write the check scripts to the scratchpad. Prerequisite: `analysis_out/aws-carddemo/inventory.json` exists (section 0.6). `APP` = `C:\My Folder\TCS\aws-mainframe-modernization-carddemo\app`.

| # | After task | Check | Pass criteria |
|---|---|---|---|
| S1 | 3.1 | `csd.scan_file` on `APP\csd\CARDDEMO.CSD` | 64 definitions: FILE 8, MAPSET 17, PROGRAM 18, TRANSACTION 18, LIBRARY 2, TDQUEUE 1; `groups == ["CARDDEMO"]`; transaction `CC00` → program `COSGN00C`; `CM00` → `COMEN01C`; `CDV1` → `COCRDSEC`; every transaction has a non-null `program`; file `ACCTDAT` has `dsname == "AWS.M2.CARDDEMO.ACCTDATA.VSAM.KSDS"`; file `CCXREF` has `description == "CARD TO ACCOUNT XREF"` and `dsname == "AWS.M2.CARDDEMO.CARDXREF.VSAM.KSDS"`; `commands == []` |
| S2 | 3.2 | `bms.scan_file` on all 17 files in `APP\bms` | field counts (sum over all maps) per member: COACTUP 128, COACTVW 100, COADM01 28, COBIL00 24, COCRDLI 72, COCRDSL 31, COCRDUP 34, COMEN01 28, CORPT00 42, COSGN00 37, COTRN00 89, COTRN01 56, COTRN02 61, COUSR00 89, COUSR01 28, COUSR02 29, COUSR03 26; each file has 1 mapset and 1 map; `COMEN01`: map `COMEN1A`, `size == [24, 80]`, first field has no name, `pos == [1, 1]`, `length == 5`, `initial == "Tran:"`, `role == "label"`; field `TRNNAME` has `pos == [1, 7]`, `length == 4`, `role == "output"` |
| S3 | 3.5 | `jcl.scan_file` on `APP\jcl\POSTTRAN.jcl` (with the driver's ctx) | kind `job`, job name `POSTTRAN`; 1 step `STEP15`, program `CBTRN02C`; 9 DDs in this order: STEPLIB, SYSPRINT, SYSOUT, TRANFILE, DALYTRAN, XREFFILE, DALYREJS, ACCTFILE, TCATBALF; `TRANFILE` dsn `AWS.M2.CARDDEMO.TRANSACT.VSAM.KSDS`, `mode_hint == "read"`; `DALYREJS` dsn `AWS.M2.CARDDEMO.DALYREJS`, `generation == "+1"`, `mode_hint == "create"`; `STEPLIB` `mode_hint == "library"`; `SYSPRINT` `mode_hint == "sysout"`; `programs_run == ["CBTRN02C"]` |
| S4 | 3.5 | `APP\jcl\TRANREPT.jcl` and the proc members | `jcllib == ["AWS.M2.CARDDEMO.PROC"]`; 3 steps as written (`STEP05R` proc `REPROC`, `STEP05R` program `SORT`, `STEP10R` program `CBTRN03C`); a warning `duplicate step name STEP05R`; the proc step has `proc_found == true` and 1 expanded step named `STEP05R.PRC001` (program `IDCAMS`); `flat_steps` has 3 entries named `STEP05R.PRC001`, `STEP05R`, `STEP10R`; in `STEP05R.PRC001`: DD `FILEIN` dsn `AWS.M2.CARDDEMO.TRANSACT.VSAM.KSDS` (override), `FILEOUT` dsn `AWS.M2.CARDDEMO.TRANSACT.BKUP` with `generation == "+1"` and `mode_hint == "create"`, `SYSIN` dsn `AWS.M2.CARDDEMO.CNTL` with `member == "REPROCT"`, `SYSPRINT` sysout; no unresolved symbols in the job; the SORT step has `utility == true` and `sort_statements` verbs exactly `["SORT", "INCLUDE"]`; `programs_run == ["CBTRN03C"]` |
| S5 | 3.5 | `APP\jcl\TRANBKP.jcl` | flat steps `STEP05R.PRC001`, `STEP05`, `STEP10`; `STEP05` `idcams_commands` has 2 `DELETE` entries: names `AWS.M2.CARDDEMO.TRANSACT.VSAM.KSDS` (object_type `CLUSTER`) and `AWS.M2.CARDDEMO.TRANSACT.VSAM.AIX` (object_type `AIX`); `STEP10` has `cond == "(4,LT)"` and a `DEFINE` with `subtype == "CLUSTER"`, `name == "AWS.M2.CARDDEMO.TRANSACT.VSAM.KSDS"`, `attrs["KEYS"] == [16, 0]`, `attrs["RECORDSIZE"] == [350, 350]` |
| S6 | 3.5 | `APP\jcl\ACCTFILE.jcl` | 3 steps `STEP05`, `STEP10`, `STEP15`, all `IDCAMS`; `STEP15` has `REPRO` with `infile == "ACCTDATA"`, `outfile == "ACCTVSAM"`, and DD `ACCTDATA` dsn `AWS.M2.CARDDEMO.ACCTDATA.PS`, DD `ACCTVSAM` dsn `AWS.M2.CARDDEMO.ACCTDATA.VSAM.KSDS` |
| S7 | 3.5 | `APP\jcl\DEFGDGB.jcl` | every `DEFINE` command has `subtype == "GDG"` and `attrs["LIMIT"] == 5`; the number of `DEFINE` commands equals the number of lines in the file that contain `DEFINE GENERATIONDATAGROUP` (count it with a script) |
| S8 | 3.5 | `APP\jcl\CLOSEFIL.jcl` and `OPENFIL.jcl` | each has 1 step with program `SDSF` and 5 `sdsf_commands`, region `CICSAWSA`, verb `SET`, resource_type `FILE`, action `CLOSE` (CLOSEFIL) or `OPEN` (OPENFIL); the resources are `TRANSACT`, `CCXREF`, `ACCTDAT`, `CXACAIX`, `USRSEC` |
| S9 | 3.5 | `APP\jcl\CBADMCDJ.jcl`, `APP\proc\REPROC.prc`, `APP\proc\TRANREPT.prc`, `APP\ctl\REPROCT.ctl` | CBADMCDJ: symbols `{"HLQ": "AWS.M2.CARDDEMO"}`; step `STEP1` program `DFHCSDUP`, `inline_csd.definitions` has 45 entries: MAPSET 20, PROGRAM 19, TRANSACTION 5, LIBRARY 1; the LIBRARY `COM2DOLL` has `dsnames == ["AWS.M2.CARDDEMO.LOADLIB"]`; PROGRAM `COSGN00C` has `transid == "CC00"`. REPROC.prc: kind `proc`, `declared_name == "REPROC"`, 1 step `PRC001` (IDCAMS), DDs `SYSPRINT, FILEIN, FILEOUT, SYSIN`; `FILEIN` has `null_file == true`; `SYSIN` has `dsn == "&CNTLLIB"`, `member == "REPROCT"`, `unresolved_symbols == ["CNTLLIB"]`. TRANREPT.prc: kind `proc`, `declared_name == "REPROC"`, `procs_used == [{"name": "REPROC", "found": true}]`. REPROCT.ctl: `control.scan_file` gives kind `idcams` and one command: verb `REPRO`, `infile == "FILEIN"`, `outfile == "FILEOUT"` |
| S10 | 3.6 | `run_scanners.py` on `analysis_out/aws-carddemo` | exit 0; `[scan]` line reports 49 files (28 jcl, 2 proc, 1 csd, 17 bms, 1 control), 0 errors; `scan_index.json` and `scan_report.md` exist; the proc named `REPROC` is looked up as member `REPROC.prc`, not `TRANREPT.prc` (check the expanded step of `TRANREPT.jcl` has program `IDCAMS`) |
| S11 | 3.6 | Report cross-checks on AWS | C1: for `CARDDEMO.CSD` exactly one program, `COCRDSEC`; the inline CSD of `CBADMCDJ` lists its 19 programs minus those that have source (report the list; do not assert the number); C3: lists (a) and (c) are empty (list (b) shows the inline mapsets of `CBADMCDJ` that have other names; report it, do not assert it); C4: none; C5: none; C6: none (if not none, report the names and do not change the code to hide them); C7: no "expected but missing" entry for the `POSTTRAN` step; C8: none |
| S12 | 3.6 | Repeatability | running the driver twice gives identical JSON files (compare file contents, ignoring the `generated` timestamp in `scan_index.json`) |

---

## 11. Unit tests and fixtures

Build fixed-column text in Python with helpers, do not paste column-sensitive text by hand:

```python
def asm(text, cont=False):
    """Assembler source line: text padded to column 71, continuation char '-' in column 72."""
    return text.ljust(71) + ("-" if cont else "")

def cob(text, ind=" "):
    """COBOL fixed-format line: 6 blanks, indicator, text."""
    return "      " + ind + text
```

`test_common.py`:
- `split_top("DISP=(NEW,CATLG,DELETE),UNIT=SYSDA,DCB=(RECFM=F,LRECL=430)")` → 3 pieces; `split_top("A,'B,C',D")` → `["A", "'B,C'", "D"]`; `split_top("(,CATLG)")` returns `["(,CATLG)"]`; `split_top("")` → `[]`.
- `sub_params("(,CATLG)")` → `["", "CATLG"]`; `sub_params("SHR")` → `["SHR"]`.
- `take_operand_field("DISP=SHR, comment text")` → `"DISP=SHR,"`; `take_operand_field("PARM='A B',X=1 rest")` → `"PARM='A B',X=1"`.
- `parse_params("PGM=IDCAMS,REGION=0M,'TEXT'")` → `[("PGM","IDCAMS"),("REGION","0M"),(None,"'TEXT'")]`.
- `paren_args("DSNAME01(&HLQ..LOADLIB) GROUP(X) ATOMIC")` → `[("DSNAME01","&HLQ..LOADLIB"),("GROUP","X"),("ATOMIC",None)]`.

`test_csd.py`:
- AWS-style: lines `[" DEFINE FILE(ACCTDAT) GROUP(CARDDEMO)", " DESCRIPTION(TEST FILE)", "        DSNAME(AWS.X.ACCT) RLSACCESS(NO)", "        BROWSE(YES) DELETE(YES) READ(YES)"]` → 1 definition `FILE ACCTDAT`, group `CARDDEMO`, description `TEST FILE`, dsname `AWS.X.ACCT`, `attrs["DELETE"] == "YES"`, no commands (the `DELETE(YES)` text must not start a statement).
- CBSA-style (statement keyword at column 0, quoted description, comment lines): `["* comment", "", " DELETE GROUP(BANK)", "", "DEFINE TRANSACTION(BKB2) GROUP(BANK)", " DESCRIPTION('BANK Online Bank to Bank Transfer Receive')", "        PROGRAM(XFRB2BR) TWASIZE(0) PROFILE(DFHCICST) STATUS(ENABLED)"]` → one command `DELETE` with text `DELETE GROUP(BANK)`, one definition `TRANSACTION BKB2` with `program == "XFRB2BR"` and `description == "BANK Online Bank to Bank Transfer Receive"`.
- `["  DEFINE PROGRAM(COSGN00C) GROUP(CARDDEMO) DA(ANY) TRANSID(CC00)"]` → type `PROGRAM`, `transid == "CC00"`.
- `first_line=10` shifts `line` numbers by 9.

`test_bms.py` (use `asm()`):
```python
lines = [
 asm("COMEN01 DFHMSD CTRL=(ALARM,FREEKB),", True),
 asm("               EXTATT=YES,", True),
 asm("               TYPE=&&SYSPARM"),
 asm("COMEN1A DFHMDI COLUMN=1,", True),
 asm("               LINE=1,", True),
 asm("               SIZE=(24,80)"),
 asm("        DFHMDF ATTRB=(ASKIP,NORM),", True),
 asm("               LENGTH=5,", True),
 asm("               POS=(1,1),", True),
 asm("               INITIAL='Tran:'"),
 asm("TRNNAME DFHMDF ATTRB=(ASKIP,FSET,NORM),", True),
 asm("               LENGTH=4,", True),
 asm("               POS=(1,7)"),
 asm("CUSTID  DFHMDF ATTRB=(UNPROT,FSET),LENGTH=9,POS=(5,20)"),
 asm("        DFHMSD TYPE=FINAL"),
]
```
Expected: 1 mapset `COMEN01`, attrs `EXTATT == "YES"`; 1 map `COMEN1A`, `size == [24, 80]`; 3 fields; field 0: name null, pos `[1,1]`, length 5, initial `Tran:`, role `label`; field 1: `TRNNAME`, attrb `["ASKIP","FSET","NORM"]`, role `output`; field 2: `CUSTID`, role `input`, pos `[5,20]`, length 9. `symbolic_copybook` is looked up from the dict passed in.

`test_ims.py` (use `asm()`; the DBD/PSB are the shapes of the CardDemo authorization sample):
```python
dbd = [
 "***********************************************************************",
 "         TITLE   'ASSEMBLE OF DBDNAME=DBPAUTP0 '",
 asm("       DBD     NAME=DBPAUTP0,ACCESS=(HIDAM,VSAM),PASSWD=NO,", True),
 asm("               EXIT=(*,KEY,DATA,NOPATH,(NOCASCADE),LOG),", True),
 asm("               VERSION="),
 "DSG001 DATASET DD1=DDPAUTP0,SIZE=(4096),SCAN=3",
 asm("       SEGM    NAME=PAUTSUM0,PARENT=0,BYTES=100,RULES=(,HERE),", True),
 asm("               POINTER=(TWINBWD)"),
 "       FIELD   NAME=(ACCNTID,SEQ,U),START=1,BYTES=6,TYPE=P",
 asm("       LCHILD  NAME=(PAUTINDX,DBPAUTX0),", True),
 asm("               POINTER=INDX"),
 "       SEGM    NAME=PAUTDTL1,PARENT=((PAUTSUM0,)),BYTES=200",
 "       FIELD   NAME=(PAUT9CTS,SEQ,U),START=1,BYTES=8,TYPE=C",
 "       DBDGEN",
 "       FINISH",
 "       END",
]
psb = [
 "PAUTBPCB PCB   TYPE=DB,DBDNAME=DBPAUTP0,PROCOPT=AP,KEYLEN=14",
 "         SENSEG  NAME=PAUTSUM0,PARENT=0",
 "         SENSEG  NAME=PAUTDTL1,PARENT=PAUTSUM0",
 "         PSBGEN  LANG=COBOL,PSBNAME=PSBPAUTB,CMPAT=YES",
 "         END",
]
```
Expected DBD: name `DBPAUTP0`, access `["HIDAM","VSAM"]`; 1 dataset (label `DSG001`, dd1 `DDPAUTP0`); 2 segments: `PAUTSUM0` (parent null, bytes 100, 1 field `ACCNTID` seq true unique true start 1 bytes 6, 1 lchild segment `PAUTINDX` dbd `DBPAUTX0`), `PAUTDTL1` (parent `PAUTSUM0`, bytes 200). Expected PSB: name `PSBPAUTB`, lang `COBOL`; 1 PCB (index 1, label `PAUTBPCB`, type `DB`, dbdname `DBPAUTP0`, procopt `AP`, keylen 14, access_hint `update`) with 2 segments (`PAUTSUM0` parent null, `PAUTDTL1` parent `PAUTSUM0`). A second PSB test: `PCB TYPE=DB,DBDNAME=X,PROCOPT=GOTP` → access_hint `read`... wait: `GOTP` contains no A/I/R/D → `read`; (note `GOTP` letters are G O T P).

`test_ddl.py`:
```python
ddl = """CREATE TABLE CARDDEMO.AUTHFRDS
(CARD_NUM              CHAR(16)    NOT NULL,
    AUTH_TS                TIMESTAMP   NOT NULL,
    MERCHANT_NAME          VARCHAR(22)         ,
    TRANSACTION_AMT        DECIMAL(12,2)       ,
    ACCT_ID                DECIMAL(11)         ,
    PRIMARY KEY(CARD_NUM,AUTH_TS )             );
CREATE UNIQUE INDEX CARDDEMO.XAUTHFRD
    ON CARDDEMO.AUTHFRDS
    (CARD_NUM ASC, AUTH_TS DESC)
    COPY YES;
"""
```
Expected: 1 table `CARDDEMO.AUTHFRDS` (schema `CARDDEMO`, name `AUTHFRDS`), 5 columns; `CARD_NUM` type `CHAR` length 16 nullable false; `AUTH_TS` type `TIMESTAMP` length null; `MERCHANT_NAME` `VARCHAR` 22 nullable true; `TRANSACTION_AMT` `DECIMAL` 12 scale 2; `ACCT_ID` `DECIMAL` 11 scale null; `primary_key == ["CARD_NUM","AUTH_TS"]`; 1 index `CARDDEMO.XAUTHFRD`, unique true, table `CARDDEMO.AUTHFRDS`, columns `[{"name":"CARD_NUM","order":"ASC"},{"name":"AUTH_TS","order":"DESC"}]`.

Inline SQL as found in a JCL SYSIN (CBSA style):
```python
sql = """SET CURRENT SQLID = 'IBMUSER';
CREATE TABLE IBMUSER.ACCOUNT (
   ACCOUNT_SORTCODE CHAR(6) NOT NULL,
   ACCOUNT_NUMBER CHAR(8) NOT NULL,
   ACCOUNT_AVAILABLE_BALANCE DECIMAL(12, 2)
)
IN CBSA.ACCOUNT NOT VOLATILE
CARDINALITY AUDIT NONE DATA CAPTURE NONE;
CREATE UNIQUE INDEX IBMUSER.ACCTINDX
  ON IBMUSER.ACCOUNT(ACCOUNT_SORTCODE,ACCOUNT_NUMBER)
  USING STOGROUP ACCOUNT;
"""
```
Expected: 1 table `IBMUSER.ACCOUNT` with `tablespace == "CBSA.ACCOUNT"`, 3 columns, `ACCOUNT_AVAILABLE_BALANCE` scale 2; 1 index `IBMUSER.ACCTINDX` with 2 columns; the `SET` statement is ignored.

DCLGEN (build with `cob()`; comment lines use `ind="*"`):
```python
dcl = [
 cob("******************************************************************", "*"),
 cob("* DCLGEN TABLE(AWSTSSC.AUTHFRDS)                                 *", "*"),
 cob("   EXEC SQL DECLARE CARDDEMO.AUTHFRDS TABLE"),
 cob("   ( CARD_NUM                       CHAR(16) NOT NULL,"),
 cob("     AUTH_TS                        TIMESTAMP NOT NULL,"),
 cob("     MERCHANT_NAME                  VARCHAR(22),"),
 cob("     ACCT_ID                        DECIMAL(11, 0)"),
 cob("   ) END-EXEC."),
 cob("******************************************************************", "*"),
 cob("01  DCLAUTHFRDS."),
 cob("    10 CARD-NUM             PIC X(16)."),
 cob("    10 AUTH-TS              PIC X(26)."),
 cob("    10 MERCHANT-NAME."),
 cob("       49 MERCHANT-NAME-LEN  PIC S9(4) USAGE COMP."),
 cob("       49 MERCHANT-NAME-TEXT PIC X(22)."),
 cob("    10 ACCT-ID              PIC S9(11)V USAGE COMP-3."),
]
```
Expected: 1 table `CARDDEMO.AUTHFRDS`, 4 columns; `host_structure.name == "DCLAUTHFRDS"`; fields include `CARD-NUM` pic `X(16)`, `ACCT-ID` pic `S9(11)V` usage `COMP-3`; column host vars: `CARD_NUM` → `CARD-NUM`, `AUTH_TS` → `AUTH-TS`, `MERCHANT_NAME` → `MERCHANT-NAME`, `ACCT_ID` → `ACCT-ID`.

`test_utilities.py`:
- `idcams_parse` on `["   DELETE AWS.X.ACCT.KSDS -", "          CLUSTER", "   IF MAXCC LE 08 THEN SET MAXCC = 0", "   DEFINE CLUSTER (NAME(AWS.X.ACCT.KSDS) -", "          CYLINDERS(1 5) -", "          KEYS(11 0) -", "          RECORDSIZE(300 300) -", "          INDEXED -", "          ) -", "          DATA (NAME(AWS.X.ACCT.KSDS.DATA) -", "          )", "   REPRO INFILE(ACCTDATA) OUTFILE(ACCTVSAM)", "   DEFINE GENERATIONDATAGROUP -", "   (NAME(AWS.X.TRAN.BKUP) -", "    LIMIT(5) -", "    SCRATCH -", "   )"]` → 4 commands in order: DELETE (name `AWS.X.ACCT.KSDS`, object_type `CLUSTER`), DEFINE CLUSTER (name `AWS.X.ACCT.KSDS`, names has 2 entries, `attrs["KEYS"] == [11, 0]`, `attrs["RECORDSIZE"] == [300, 300]`, `attrs["ORGANIZATION"] == "INDEXED"`), REPRO (infile `ACCTDATA`, outfile `ACCTVSAM`), DEFINE GDG (name `AWS.X.TRAN.BKUP`, `attrs["LIMIT"] == 5`).
- `sort_parse` on `["TRAN-CARD-NUM,263,16,ZD", "PARM-START-DATE,C'2022-01-01'", " SORT FIELDS=(TRAN-CARD-NUM,A)", " INCLUDE COND=(TRAN-PROC-DT,GE,PARM-START-DATE,AND,", "         TRAN-PROC-DT,LE,PARM-END-DATE)"]` → verbs `["SORT", "INCLUDE"]`; SORT `fields == "TRAN-CARD-NUM,A"`; the INCLUDE text contains `PARM-END-DATE`.
- `sdsf_parse` on `[" /F CICSAWSA,'CEMT SET FIL(TRANSACT ) CLO'", " /F CICSAWSA,'CEMT SET FIL(CCXREF ) OPE'"]` → 2 entries: region `CICSAWSA`, verb `SET`, resource_type `FILE`, resources `TRANSACT` and `CCXREF`, actions `CLOSE` and `OPEN`.
- `tso_parse` on `["  DSN SYSTEM(DBCG)", "  RUN PROGRAM(DSNTEP2)  PLAN(DSNTEP12) -", "       LIB('DSNC10.DBCG.RUNLIB.LOAD') PARMS('/ALIGN(MID)')", "  END"]` → one entry: program `DSNTEP2`, plan `DSNTEP12`, subsystem `DBCG`.
- `parm_invokes("DFSRRC00", "DLI,PAUTB01,PSBPAUTB")` → `[{"program": "PAUTB01", "psb": "PSBPAUTB", "via": "DFSRRC00 PARM"}]`; `parm_invokes("IDCAMS", "X")` → `[]`.

`test_jcl.py` (call `read_cards`, `parse_member`, and the expansion with a hand-made `ctx`):
- Cards: `["//POSTTRAN JOB 'POSTTRAN',CLASS=A,MSGCLASS=0,", "// NOTIFY=&SYSUID", "//STEP15 EXEC PGM=CBTRN02C", "//STEPLIB  DD DISP=SHR,", "//            DSN=AWS.M2.CARDDEMO.LOADLIB", "//SYSIN DD *", "  DELETE X -", "    CLUSTER", "/*", "//DD2 DD DUMMY", "//*comment", "//"]` → cards: JOB (name `POSTTRAN`, operands containing `NOTIFY=&SYSUID`), EXEC, DD `STEPLIB` with operands `DISP=SHR,DSN=AWS.M2.CARDDEMO.LOADLIB`, DD `SYSIN` with `inline.lines` of length 2, DD `DD2`, and a final null statement (`op == ""`); the comment is skipped.
- DD parsing: `//TRANREPT DD DISP=(NEW,CATLG,DELETE),UNIT=SYSDA,DCB=(LRECL=133,RECFM=FB,BLKSIZE=0),SPACE=(CYL,(1,1),RLSE),DSN=AWS.M2.CARDDEMO.TRANREPT(+1)` → `dsn == "AWS.M2.CARDDEMO.TRANREPT"`, `generation == "+1"`, `disp == {"raw": "(NEW,CATLG,DELETE)", "status": "NEW", "normal": "CATLG", "abnormal": "DELETE"}`, `mode_hint == "create"`, `dcb == {"lrecl": 133, "recfm": "FB", "blksize": 0, "dsorg": None, "ref": None}`.
- `//OUT DD DSN=&&TEMP,DISP=(,PASS)` → `temp == true`, `disp.status is None`, `disp.normal == "PASS"`. `//IN DD DSN=AWS.X.LIB(MEMB),DISP=SHR` → `member == "MEMB"`. `//Z DD DUMMY` → `dummy`, `mode_hint == "dummy"`.
- Symbols: lines `["// SET HLQ=AWS.M2.CARDDEMO", "//STEP1 EXEC PGM=DFHCSDUP,PARM='CSD(READWRITE)'", "//STEPLIB DD DSN=&HLQ..LOADLIB,DISP=SHR", "//X DD DSN=&MISSING..DATA,DISP=SHR", "//Y DD DSN=&SYSUID..DATA,DISP=SHR"]` → STEPLIB `dsn == "AWS.M2.CARDDEMO.LOADLIB"`; X unresolved `["MISSING"]`; Y has no unresolved symbols (system symbol).
- Include: ctx `members = {"DEFAULT": ["// SET CICSHLQ=DFH560.CICS"]}`, lines `["// INCLUDE MEMBER=DEFAULT", "//S1 EXEC PGM=X", "//L DD DSN=&CICSHLQ..SDFHLOAD,DISP=SHR"]` → `includes == [{"member": "DEFAULT", "found": True}]` and L's dsn `DFH560.CICS.SDFHLOAD`.
- Proc expansion: ctx `procs = {"REPROC": parse_member(["//REPROC PROC", "//PRC001 EXEC PGM=IDCAMS", "//FILEIN DD DISP=SHR,DSN=NULLFILE", "//FILEOUT DD DISP=SHR,DSN=NULLFILE", "//SYSIN DD DISP=SHR,DSN=&CNTLLIB(REPROCT)", "// PEND"], "REPROC", {...})}` and job `["//J JOB", "//S1 EXEC PROC=REPROC,", "// CNTLLIB=AWS.CNTL", "//PRC001.FILEIN DD DISP=SHR,DSN=AWS.IN", "//PRC001.FILEOUT DD DISP=(NEW,CATLG),DSN=AWS.OUT(+1)", "//S2 EXEC PGM=MYPROG"]` → `flat_steps` names `["S1.PRC001", "S2"]`; in `S1.PRC001`: `FILEIN` dsn `AWS.IN`; `FILEOUT` dsn `AWS.OUT`, generation `+1`; `SYSIN` dsn `AWS.CNTL`, member `REPROCT`; `programs_run == ["MYPROG"]`; `procs_used == [{"name": "REPROC", "found": True}]`. With an empty `procs` dict: `procs_used == [{"name": "REPROC", "found": False}]`, `flat_steps` still has 2 entries (`S1` and `S2`).
- In-stream data for DFHCSDUP with symbols: lines `["// SET HLQ=AWS.X", "//S1 EXEC PGM=DFHCSDUP", "//SYSIN DD *,SYMBOLS=JCLONLY", "  DEFINE LIBRARY(COM2DOLL) GROUP(G)", "        DSNAME01(&HLQ..LOADLIB)", "  DEFINE TRANSACTION(CCDM) GROUP(G)", "        PROGRAM(COADM00C)", "/*"]` → `inline_csd.definitions` has 2 entries; the library has `dsnames == ["AWS.X.LOADLIB"]`; the transaction has `program == "COADM00C"`.
- Inline SQL (CBSA style): lines `["//GRANT EXEC PGM=IKJEFT01,DYNAMNBR=20", "//SYSTSIN DD *", "  DSN SYSTEM(DBCG)", "  RUN PROGRAM(DSNTEP2) PLAN(DSNTEP12) -", "       LIB('DSNC10.DBCG.RUNLIB.LOAD')", "  END", "//SYSIN DD *", "SET CURRENT SQLID = 'IBMUSER';", "CREATE DATABASE CBSA", "       BUFFERPOOL BP1;", "/*"]` → `tso_runs` has 1 entry (program `DSNTEP2`); `invokes` contains `DSNTEP2` with plan `DSNTEP12`; `inline_sql.other` has 1 entry with kind `DATABASE`, name `CBSA`.
- IF context: lines `["//S1 EXEC PGM=A", "// IF (S1.RC = 0) THEN", "//S2 EXEC PGM=B", "// ELSE", "//S3 EXEC PGM=C", "// ENDIF", "//S4 EXEC PGM=D"]` → `if_context` of S2 is `["(S1.RC = 0)"]`, S3 `["NOT ((S1.RC = 0))"]`, S4 `[]`.
- Duplicate step name warning appears on the second step.
- A file without a JOB card and with a `PROC` card → `kind == "proc"`; a file with only `SET` cards → `kind == "fragment"`.

Add `test_csd.py`, `test_bms.py` etc. so that `python -m unittest discover -s scanners/tests -t scanners` runs all of them.

---

## 12. Documentation tasks (task 3.7)

1. `scanners/README.md`, written for a person on the offline VM with no AI assistant: purpose (2 lines); requirements (Python 3.8+, the output of `inventory.py`; **no Java needed**); the command with every option explained; the output folder table from section 1; how to read `scan_report.md` (what each cross-check C1–C9 means and what to do about it); troubleshooting (`scan_errors.log`, files skipped as EBCDIC, proc not found because its file is not in the codebase, unresolved symbols come from `SET` statements or procs outside the codebase).
2. `docs/SCANNERS_SCHEMA.md`: the schemas of sections 3–9 (keys and meaning) plus one short real example each taken from the AWS output: a CSD `TRANSACTION` definition, a BMS field, a JCL step with its DDs (from `POSTTRAN`), and a flat expanded step (from `TRANREPT`). Add a table "How later stages use the scanner facts": Stage 3 graph: CSD `transactions → program`, CSD `files → dsname`, JCL `flat_steps` (`program` → `dds` → `dsn`), `datasets`, `inline_csd`, `sdsf_commands` (job → CICS file); Stage 4 modules: JCL jobs and the datasets they write (`mode_hint` + the program's `files_io.access_summary`), tables from DDL/DCLGEN, IMS PSB/DBD segments; Stage 8 documents: BMS fields and maps for screen descriptions, DDL columns for data dictionary tables, JCL job flow for batch run books.
3. In `docs/MODULARIZATION_PLAN.md`, under `### 2b. Other artefacts (Python)`, add one line at the top: `Detailed build plan: [STEP3_BUILD_PLAN.md](STEP3_BUILD_PLAN.md). Output schema: [SCANNERS_SCHEMA.md](SCANNERS_SCHEMA.md).`

---

## 13. Things not to do

- No COBOL parsing and no Java in this step.
- No LLM calls.
- No new dependencies.
- Do not scan assembler sources or macro libraries.
- Do not resolve dataset names to CICS file names or ddnames to COBOL files across files in the scanners; that is the graph builder's job (step 4). The report cross-checks only compare name sets.
- Do not "improve" expected values to make a check pass. If real output differs, report it.
- Do not run anything on `CardDemo-Cobol-main` or CBSA, and do not open their files.

---

## 14. Final report to the user

When all tasks are done, report in this format:

1. Files created and edited (list).
2. Results of S1–S12 and the unit tests: pass/fail and, for any fail, the actual output.
3. Numbers from the AWS run: files per kind, errors, total flat steps, datasets found, list of CSD programs without source (file CSD and inline CSD separately), all cross-check results, run time.
4. Every place where this plan was unclear and what you chose (rule in the header of this document).
5. The exact commands the user runs on the other two repos (the `run_scanners.py` command for `analysis_out/carddemo-main` and `analysis_out/cbsa`, assuming `inventory.py` and `run_facts.py` were run before), and a short list of what to look at first in each `scan_report.md` (C1, C4, C5, C9 and any `scan_errors.log`).
