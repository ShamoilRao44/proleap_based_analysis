# Facts schema `cobol-facts/1`

One file per COBOL program: `<analysis_dir>/facts/cobol/<NAME>.json`, written by `facts/run_facts.py`. Later pipeline stages read only these files. `facts/_index.json` lists them all.

A **location** (`loc`, `start`, `end`, `first_loc`) is always `[file_index, line]`. `file_index` points into the program's `files` list (0 is the program itself, higher numbers are copybooks) and `line` is the real line number in that file. `[0, 0]` means unknown. Missing values are never omitted: they are `null`, `[]` or `{}`.

## Keys

| Key | Content |
|---|---|
| `schema` | `"cobol-facts/1"` |
| `name`, `path` | member name, path relative to the codebase root |
| `program_id` | first of the `PROGRAM-ID`s, or null |
| `source` | `proleap` (parser) or `text` (fallback text scan) |
| `quality` | `status`, `parser`, `syntax_error_count`, `syntax_error_samples` (first 20, with `loc` and `msg`), `line_map_exact_ratio` (share of preprocessed lines mapped to an exact source line), `missing_copybooks`, `fallback_reason` (why the text scan was used, else null), `parse_ms` |
| `files` | `[{index, path, name, kind}]`, kind is `program` or `copybook` |
| `metrics` | `lines`, `code_lines`, `comment_lines`, `blank_lines`, `statements`, `paragraphs`, `complexity` (sum), `est_tokens_program` (tokens of the program file), `est_tokens_expanded` (tokens after copybook expansion), `cics_commands` (command to count), `statement_types` (type to count) |
| `kind` | `cics_online` (has `EXEC CICS`), `batch_subroutine` (`PROCEDURE DIVISION USING`), or `batch_main` |
| `flags` | `uses_cics`, `uses_db2`, `uses_ims`, `uses_mq`, `uses_files` |
| `interface` | `procedure_using`, `linkage_records`, `commarea` (`{name, size}` for `DFHCOMMAREA`, else null), `linkage_layout` (`[{record, items: [{name, level, offset, size, pic, usage}]}]`, at most 300 items per record) |
| `copybooks` | `[{name, path, file_index, loc, region, depth, via, missing, exact, source}]`. `loc` is where the `COPY` statement is (in the parent file). `region` is `file`, `working-storage`, `local-storage`, `linkage`, `procedure`, `environment`, `identification` or `unknown`. `via` is the copybook that contains this `COPY`, if nested. |
| `sql_includes` | `[{name, loc}]` for `EXEC SQL INCLUDE` |
| `data_items` | `[{id, level, name, parent, record, children, conditions, section, fd, pic, usage, effective_usage, values, occurs, redefines, redefines_id, size, occurs_count, total_size, offset, is_group, size_unknown, loc, file_index}]`. Sizes are in bytes, `offset` is relative to the start of the 01/77 record. `conditions` are the 88-level names of the item. `values` entries are `{from, thru, kind, value}` with kind `string`, `number`, `figurative`, `hex`, `all` or `other`. |
| `files_io` | one entry per `SELECT`: `select`, `dd`, `assign_is_literal`, `organization`, `access`, `record_key`, `file_status`, `records`, `open_modes`, `ops`, `access_summary` (`read`, `write`, `read_write`, `unknown`) |
| `procedure` | `sections` (`name, start, end, declaratives, paragraphs`) and `paragraphs` (see the example below) |
| `dead_paragraphs` | names of paragraphs that cannot be reached |
| `decisions` | `[{id, kind (if/evaluate/search), paragraph, loc, end, depth, stmt_id, ...}]` with `condition` (if), `subjects` / `whens` / `has_other` (evaluate) or `table` / `whens` (search) |
| `transfers` | `[{id, kind, target, resolved_targets, unresolved, commarea, length, using, paragraph, loc, guards, stmt_id, source}]`. Kinds: `CALL`, `LINK`, `XCTL`, `RETURN_TRANSID`, `RETURN`, `START_TRANSID`, `HANDLE_ABEND`, `GOBACK`, `STOP_RUN`, `EXIT_PROGRAM`. `target` is `{literal}` or `{var, text}`. `resolved_targets` is `[{value, how}]`, `how` is `literal`, `value_clause`, `move_literal`, `set_condition`, `value_table` or `move_var:<name>`. `guards` are the conditions that must hold for the statement to run, outermost first. |
| `resources` | `[{id, kind, name, name_resolved, mapset, mapset_resolved, op, command, extra, unresolved, paragraph, loc, guards, stmt_id, source}]`. Kinds: `cics_file`, `map`, `terminal`, `ts_queue`, `td_queue`, `container`, `db2_table`, `ims_call`, `mq_call`, `batch_file`. |
| `error_handling` | `[{id, kind, detail, paragraph, loc}]`. Kinds: `HANDLE_ABEND`, `HANDLE_CONDITION`, `HANDLE_AID`, `ABEND`, `RESP_CHECK`, `RESP_EVAL`, `FILE_STATUS_CHECK`, `SQLCODE_CHECK`, `SQL_WHENEVER`. |
| `unresolved_names` | `[{name, count, first_loc}]`: names used but defined nowhere (usually in a missing copybook) |
| `unused_data`, `write_only_data` | names of the program's own data items that are never used, or only written (at most 500 each) |

Entries copied from the text scan because the parser missed them have `source: "text_only"`.

## How later stages use the facts

| Later stage | Facts used |
|---|---|
| 3 Graph | `transfers` (with `resolved_targets`, `guards`), `copybooks`, `sql_includes`, `resources` (with `op`), `files_io.dd`, `interface` |
| 4 Modules and bundles | edges built from the above; `files_io.access_summary` and resource `op` for data ownership; `kind` and `flags`; `copybooks` (all depths) for bundle completeness |
| 5 Chunking | paragraph `start` / `end` (real lines), `est_tokens`, `reads` / `writes` (data definitions to include), `outline` (compact view of oversized paragraphs), `data_items` with `loc` |
| 6 LLM extraction | `decisions` (anchors and coverage check), `data_items` conditions (88-level names), valid names and lines for the hallucination guard |
| 7 IR | everything, excerpted by `ir_query` within a token budget |
| 8 Documents | `interface.linkage_layout`, `data_items` layouts, `files_io`, `transfers` + `guards` (screen flow), `outline` (activity diagrams), `error_handling`, `dead_paragraphs`, `metrics` |

## Examples (from `COMEN01C` of the AWS CardDemo)

A transfer. The program name comes from a value table in a copybook; `resolved_targets` is shortened here.

```json
{
 "id": "T2",
 "kind": "XCTL",
 "target": {"var": "CDEMO-MENU-OPT-PGMNAME", "text": "CDEMO-MENU-OPT-PGMNAME(WS-OPTION)"},
 "resolved_targets": [
  {"value": "COACTVWC", "how": "value_table"},
  {"value": "COACTUPC", "how": "value_table"},
  {"value": "...", "how": "value_table"}
 ],
 "unresolved": false,
 "commarea": "CARDDEMO-COMMAREA",
 "length": null,
 "using": [],
 "paragraph": "PROCESS-ENTER-KEY",
 "loc": [0, 152],
 "guards": ["NOT ERR-FLG-ON", "CDEMO-MENU-OPT-PGMNAME(WS-OPTION)(1:5) NOT = 'DUMMY'"],
 "stmt_id": 39,
 "source": "proleap"
}
```

A resource (a BMS map sent to the terminal):

```json
{
 "id": "R1",
 "kind": "map",
 "name": {"literal": "COMEN1A"},
 "name_resolved": [{"value": "COMEN1A", "how": "literal"}],
 "mapset": {"literal": "COMEN01"},
 "mapset_resolved": [{"value": "COMEN01", "how": "literal"}],
 "op": "send",
 "command": "SEND MAP",
 "extra": {},
 "unresolved": false,
 "paragraph": "SEND-MENU-SCREEN",
 "loc": [0, 189],
 "guards": [],
 "stmt_id": 50,
 "source": "proleap"
}
```

A paragraph (lists shortened):

```json
{
 "name": "PROCESS-ENTER-KEY",
 "section": null,
 "declaratives": false,
 "start": [0, 115],
 "end": [0, 165],
 "statements": 24,
 "complexity": 9,
 "est_tokens": 607,
 "reachable": true,
 "reads": ["CARDDEMO-COMMAREA", "CDEMO-MENU-OPT-COUNT", "..."],
 "writes": ["CDEMO-FROM-PROGRAM", "CDEMO-FROM-TRANID", "..."],
 "performs": ["SEND-MENU-SCREEN"],
 "performed_by": ["MAIN-PARA"],
 "transfers": ["T2"],
 "resources": [],
 "outline": [
  {"type": "if", "depth": 0, "loc": [0, 127],
   "summary": "IF WS-OPTION IS NOT NUMERIC OR WS-OPTION > CDEMO-MENU-OPT-COUNT OR WS-OPTION = ZEROS"},
  {"type": "perform", "depth": 1, "loc": [0, 133], "summary": "PERFORM SEND-MENU-SCREEN"}
 ]
}
```
