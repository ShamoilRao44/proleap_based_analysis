# Scanner facts schemas (step 3)

Written by `scanners/run_scanners.py` into `<analysis_dir>/facts/<kind>/<NAME>.json`. All names (programs, DDs, datasets, tables, mapsets, transactions) are upper case; free text keeps its case.

## `csd-facts/1`

`{schema, name, path, source ("file"), definitions, commands, summary, warnings}`

- `definitions`: `[{type, name, group, description, line, end_line, attrs, ...}]`. `attrs` holds every attribute as written (`True` for a word without value). Extra keys by type: `TRANSACTION` has `program`; `PROGRAM` has `language`, `transid`; `FILE` has `dsname`; `LIBRARY` has `dsnames`; `TDQUEUE` has `queue_type`.
- `commands`: statements that are not `DEFINE` (`DELETE GROUP(...)`, `LIST`, ...): `[{verb, text, line}]`.
- `summary`: `{by_type: {TYPE: n}, groups: [...]}`.

Example (AWS CardDemo, `CM00`; attributes shortened):

```json
{"type": "TRANSACTION", "name": "CM00", "group": "CARDDEMO", "description": null, "line": 399, "end_line": 408,
 "attrs": {"GROUP": "CARDDEMO", "PROGRAM": "COMEN01C", "TWASIZE": "0", "PROFILE": "DFHCICST", "STATUS": "ENABLED"},
 "program": "COMEN01C"}
```

## `bms-facts/1`

`{schema, name, path, mapsets, summary: {mapsets, maps, fields}, warnings}`

- `mapsets`: `[{name, line, attrs, symbolic_copybook, maps}]`; `symbolic_copybook` is the path of the symbolic map copybook with the same name, or null.
- `maps`: `[{name, line, size: [rows, cols], attrs, fields, field_count, named_fields, input_fields, labels}]`.
- `fields`: `[{name (or null), line, pos: [row, col], length, attrb, initial, color, hilight, role, attrs}]`. `role` is `input` (UNPROT), `output` (named, not input), `label` (unnamed, has INITIAL text) or `filler`.

Example (`COMEN01`, field `TRNNAME`; `attrs` shortened):

```json
{"name": "TRNNAME", "line": 34, "pos": [1, 7], "length": 4, "attrb": ["ASKIP", "FSET", "NORM"],
 "initial": null, "color": "BLUE", "hilight": null, "role": "output",
 "attrs": {"ATTRB": "(ASKIP,FSET,NORM)", "COLOR": "BLUE", "LENGTH": "4"}}
```

## `jcl-facts/1` (jobs, fragments and PROCs)

`{schema, name, path, kind, declared_name, jobs, symbols, jcllib, includes, instream_procs, steps, flat_steps, job_dds, programs_run, procs_used, utilities_used, datasets, unresolved_symbols, summary, warnings}`; PROC members also have `defaults`.

- `kind`: `job` (has a JOB card), `proc` (has a PROC card, no JOB card) or `fragment`.
- `steps`: the steps as written. A step that calls a PROC has `proc_found` and `expanded` (the expanded steps), and its override DDs (`PRC001.FILEIN DD ...`) in `overrides`.
- `flat_steps`: the steps that really run: PROC calls replaced by the PROC's steps (named `STEP.PROCSTEP`) with symbols substituted and overrides applied; `null` for PROC members. **This is the list later stages use.**
- A step: `{index, name, line, job, kind, program, proc, parm, cond, region, params, if_context, utility, build, dds, overrides, invokes, utility_data, proc_found, expanded, expanded_from, via_step, warnings}`.
  - `invokes`: the application programs the step starts: `EXEC PGM=`, the `RUN PROGRAM(...)` of a TSO/DB2 batch step, or the program named in an IMS `DFSRRC00` PARM.
  - `utility_data`: parsed control data: `idcams_commands`, `sort_statements`, `sdsf_commands` (CICS `CEMT SET FIL(...) OPEN/CLOSE` issued through SDSF), `inline_csd` (CSD definitions inside a `DFHCSDUP` step), `tso_runs`, `inline_sql`.
- A DD: `{name, line, concat, dsn_raw, dsn, member, generation, temp, null_file, referback, disp, sysout, dummy, inline, mode_hint, dcb, unit, ddname_ref, override_of, added_by_override, unresolved_symbols}`. `generation` is `+1`, `0`, `-1` for generation data sets. `mode_hint` is `read` (SHR), `create` (NEW), `append` (MOD), `old`, `delete`, `library`, `sysout`, `inline`, `dummy` or `unknown`. Whether a program really reads or writes a `SHR` dataset follows from the program's own file access (`files_io` in the COBOL facts).
- `datasets`: `[{dsn, generation, refs: [{step, dd, member, mode_hint, disp}]}]`, over all DDs of the flat steps.

Example (`POSTTRAN`, step `STEP15`; DDs reduced to two):

```json
{"index": 1, "name": "STEP15", "line": 23, "kind": "program", "program": "CBTRN02C", "proc": null,
 "dds": [
  {"name": "STEPLIB", "dsn": "AWS.M2.CARDDEMO.LOADLIB", "mode_hint": "library", "disp": {"raw": "SHR", "status": "SHR", "normal": null, "abnormal": null}},
  {"name": "DALYREJS", "dsn_raw": "AWS.M2.CARDDEMO.DALYREJS(+1)", "dsn": "AWS.M2.CARDDEMO.DALYREJS", "generation": "+1",
   "mode_hint": "create", "disp": {"raw": "(NEW,CATLG,DELETE)", "status": "NEW", "normal": "CATLG", "abnormal": "DELETE"},
   "dcb": {"lrecl": 430, "recfm": "F", "blksize": 0, "dsorg": null, "ref": null}, "unit": "SYSDA"}],
 "invokes": [{"program": "CBTRN02C", "via": "EXEC PGM"}]}
```
(Keys with default values are left out of this example.)

A flat step from `TRANREPT`: the PROC step `PRC001` of PROC `REPROC`, called by job step `STEP05R`. The `FILEOUT` DD comes from the job's override and replaces the PROC's DD:

```json
{"name": "STEP05R.PRC001", "expanded_from": "REPROC", "via_step": "STEP05R", "program": "IDCAMS",
 "dds": [{"name": "FILEOUT", "dsn": "AWS.M2.CARDDEMO.TRANSACT.BKUP", "generation": "+1", "mode_hint": "create",
          "override_of": {"proc_step": "PRC001", "dd": "FILEOUT"}}]}
```
(Other keys left out.)

## `ddl-facts/1`

`{schema, name, path, kind ("ddl" | "dclgen"), tables, indexes, views, other, alters, drops, dml, summary, warnings}`. The same structure (without the envelope) is stored as `utility_data.inline_sql` for SQL found in a JCL `SYSIN`.

- `tables`: `[{schema, name, qualified, columns, primary_key, foreign_keys, unique, tablespace, line, host_structure}]`; `columns`: `[{name, type, length, scale, nullable, default}]`, plus `host_var` for DCLGEN. `host_structure` (DCLGEN only): `{name, fields: [{level, name, pic, usage}]}`.
- `indexes`: `[{name, table, unique, columns: [{name, order}], line}]`; `views`: `[{name, tables, line}]`; `other`: `[{kind, name, line}]` for database, tablespace, storage group, ...; `dml`: `[{kind, tables: [{name, op}], line}]`.

## `ims-facts/1`

`{schema, name, path, kind ("dbd" | "psb"), declared_name, dbd, psb, warnings}`.

- `dbd`: `{name, access, line, datasets, segments}`; `segments`: `[{name, parent, bytes, rules, pointer, line, fields, lchild}]` (`parent` is null for a root segment).
- `psb`: `{name, lang, cmpat, line, pcbs}`; `pcbs`: `[{index, label, type, dbdname, procopt, keylen, access_hint ("read" | "update"), line, segments: [{name, parent, procopt}]}]`.

## `control-facts/1`

`{schema, name, path, kind ("idcams" | "sort" | "unknown"), commands | statements | head, warnings}`. IDCAMS commands: `{verb, subtype, name, names, object_type, infile, outfile, indataset, outdataset, attrs, text, line}`.

## How later stages use the scanner facts

| Later stage | Facts used |
|---|---|
| 3 Graph (step 4) | CSD `TRANSACTION` → `program`; CSD `FILE` → `dsname`; JCL `flat_steps` (`program` / `invokes` → `dds` → `dsn`); `datasets`; `sdsf_commands` (job → CICS file); `inline_csd`; BMS `mapsets` linked to the symbolic map copybook |
| 4 Modules and bundles | JCL jobs and the datasets they create or write (`mode_hint` plus the program's `files_io.access_summary`); tables from DDL / DCLGEN / inline SQL; IMS PSB / DBD segments per program; JCL, CSD and BMS members to put into each bundle |
| 8 Documents | BMS maps and fields for screen descriptions; DDL columns for data dictionary tables; JCL job flow (steps, PARM, COND, `if_context`) for batch run books |
