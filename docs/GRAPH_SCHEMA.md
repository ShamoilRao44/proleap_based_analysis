# Graph schema `cobol-graph/1` (step 4)

Written by `graph/build_graph.py` into `<analysis_dir>/graph/`. All names are upper case.

## `graph.json`

```json
{"schema": "cobol-graph/1", "generated": "<iso time>", "codebase_root": "...",
 "inputs": {"cobol": 26, "csd": 1, "jcl": 28, "proc": 2, "bms": 17, "ddl": 0, "ims": 0, "control": 1},
 "stats": {"nodes_by_type": {...}, "edges_by_type": {...}},
 "nodes": [...], "edges": [...], "entry_points": [...], "unresolved": [...], "analysis": {...}}
```

### Nodes

`{"id", "type", "name", "in_codebase", "attrs"}`. `in_codebase` is `true` (the codebase contains it), `false` (referenced but not present) or `null` (not applicable or unknown).

| Type | Id | In-codebase means | Main attributes |
|---|---|---|---|
| `program` | `program:NAME` | COBOL or assembler source exists | `path`, `kind` (cics_online, batch_main, batch_subroutine), `lines`, `est_tokens`, `uses_cics/db2/ims/mq`, `system`, `utility`, `csd_defined`, `role` (online, batch, both, unreached) |
| `copybook` | `copybook:NAME` | file exists | `path`, `subtype`, `kind`, `system` |
| `mapset` | `mapset:NAME` | BMS source exists | `maps`, `path`, `bms`, `csd_defined` |
| `transaction` | `transaction:NAME` | defined in a CSD | `program`, `defined_in` |
| `job` | `job:MEMBER` | JCL member exists | `path`, `declared_name`, `kind` |
| `step` | `step:MEMBER#INDEX` | always true | `job`, `step_name`, `index`, `program`, `kind`, `expanded_from`, `cond`, `if_context`, `utility`, `line` |
| `proc`, `control_card`, `csd` | `type:MEMBER` | file exists | `path`, ... |
| `cics_file` | `cics_file:NAME` | defined in a CSD FILE | `dsnames` |
| `dataset` | `dataset:DSN` (temporary: `dataset:&&TEMP@JOBMEMBER`) | null | `temp`, `gdg`, `unresolved` |
| `db2_table` | `db2_table:QUALIFIED` | defined in DDL, DCLGEN or inline SQL | `defined_in` |
| `ts_queue`, `td_queue` | `type:NAME` | td_queue: defined in a CSD | `queue_type`, `ddname`, `internal_reader` |
| `psb`, `ims_db` | `type:NAME` | file exists | `path` |

`step` ids use the flat step index of the job (after PROC expansion), so a PROC step has its own node.

### Edges

`{"id", "type", "strength", "source", "target", "access", "count", "details"}`. Repeated edges with the same type, source and target are merged: `count` grows, `access` is combined (`read` + `write` = `read_write`) and `details` keeps the first 50 occurrences. `access` is `read`, `write`, `read_write`, `delete`, `unknown` or `null`.

| Type | Strength | From → to | Detail keys |
|---|---|---|---|
| `CALL`, `LINK`, `HANDLE_ABEND` | hard | program → program | `how`, `paragraph`, `file`, `line`, `commarea`, `guards` |
| `XCTL` | navigation | program → program | same |
| `RETURN_TRANSID`, `START_TRANSID` | navigation | program → transaction | same |
| `TRANSACTION_RUNS` | entry | transaction → program | `source` (csd or job that defines it) |
| `JOB_STEP` | entry | job → step | `index` |
| `STEP_RUNS` | entry | step → program | `via`, `plan` for programs started through a utility |
| `STEP_PSB` | entry | step → psb | |
| `COPY` | build | program or copybook → copybook | `file`, `line`, `depth` |
| `SQL_INCLUDE` | build | program → copybook | `line` |
| `USES_MAP` | build | program → mapset | `map`, `op`, `paragraph`, `file`, `line` |
| `SYMBOLIC_MAP` | build | mapset → copybook | |
| `PROGRAM_CICS_FILE` | data | program → cics_file | `op`, `command`, `paragraph`, `file`, `line` |
| `CICS_FILE_DATASET` | data | cics_file → dataset | `source` |
| `PROGRAM_DATASET` | data | program → dataset (through a JCL DD) | `job`, `step`, `dd` |
| `STEP_DATASET` | data | step → dataset | `dd`, `member`, `generation`, `disp`, `mode_hint`, `via` |
| `IDCAMS_DEFINE`, `IDCAMS_DELETE` | data | step → dataset | `subtype` / `object_type`, `line` |
| `DATASET_RELATE` | data | dataset → dataset (AIX or PATH to its base) | `kind` |
| `PROGRAM_DB2_TABLE` | data | program → db2_table | `op`, `command`, ... |
| `PROGRAM_TS_QUEUE`, `PROGRAM_TD_QUEUE` | data | program → queue | `op`, ... |
| `PSB_DBD`, `PROGRAM_PSB` | data | psb → ims_db, program → psb | `procopt`, `pcb` |
| `JOB_USES_PROC` | config | job → proc | |
| `STEP_CONTROL_CARD` | config | step → control_card | `dd`, `dsn` |
| `CSD_DEFINES` | config | csd or job → program, mapset, transaction, cics_file, td_queue | `line` |
| `JOB_CICS_COMMAND` | operational | job → cics_file (a `CEMT SET FIL` run through SDSF) | `action`, `region`, `step` |

How the access of a DD is decided: first the program's own file access (`files_io.access_summary` of the COBOL facts, matched by DD name); then, for utilities, IDCAMS `REPRO INFILE/OUTFILE`, SORT `SORTIN/SORTOUT` and IEBGENER `SYSUT1/SYSUT2`; otherwise the DD's disposition (NEW or MOD = `write`, SHR = `read`, OLD = `read_write`, a delete disposition = `delete`).

### `entry_points`, `unresolved`, `analysis`

- `entry_points`: `{"type": "transaction", "id", "program"}`, `{"type": "job", "id", "programs"}` and `{"type": "candidate_program", "id", "reason"}`.
- `unresolved`: items with `kind` `dynamic_transfer` (`program`, `transfer_kind`, `target_text`, `file`, `line`), `dynamic_resource`, `dd_missing` (`job`, `step`, `program`, `dd`), `proc_not_found`, `unresolved_symbols`.
- `analysis`: `reach` (online and batch closures), `candidates`, `orphans`, `sccs_hard`, `sccs_navigation` (cycles), `fan` (fan-in / fan-out), `data_stores`, `missing`, `unused`, `batch_submitters`.

## `entry_points.json` (`entry-points/1`)

An entry point is an application program started by a CICS transaction or a JCL step, or with no `CALL` / `LINK` caller. `XCTL` is screen navigation and does not make a program dependent. Copybooks play no role.

```json
{"schema": "entry-points/1", "generated": "...", "codebase_root": "...", "rule": "...",
 "summary": {"entry_points": 25, "cics_transaction": 17, "jcl_job": 7, "both": 0, "candidate": 1,
             "not_entry_points": 1, "unresolved_dynamic_calls": 0},
 "entry_points": [{"name", "kind", "path", "entry_type", "confidence", "transactions", "jobs", "hard_callers",
                   "also_called", "nav_callers", "calls", "xctl_to", "copybooks", "notes"}],
 "not_entry_points": [{"name", "kind", "path", "reason", "hard_callers", "nav_callers"}]}
```

`entry_type`: `cics_transaction`, `jcl_job`, `both` (all `confirmed`) or `candidate` (`heuristic`). `not_entry_points` have `reason` `called` (a subroutine) or `navigation target` (reached only by XCTL / RETURN TRANSID). `also_called` is true when a confirmed entry point is also called by another program.

## Examples (AWS CardDemo)

A transaction starts a program (`details.source` tells which CSD defines it):

```json
{"type": "TRANSACTION_RUNS", "strength": "entry", "source": "transaction:CM00", "target": "program:COMEN01C",
 "access": null, "count": 1, "details": [{"source": "csd:CARDDEMO"}]}
```

A batch program writes a dataset through a DD of a job step:

```json
{"type": "PROGRAM_DATASET", "strength": "data", "source": "program:CBTRN02C",
 "target": "dataset:AWS.M2.CARDDEMO.TRANSACT.VSAM.KSDS", "access": "write", "count": 1,
 "details": [{"job": "POSTTRAN", "step": "STEP15", "dd": "TRANFILE"}]}
```

An IDCAMS step writes a VSAM cluster (REPRO `OUTFILE`); note that the DD says `DISP=SHR` but the access is `write`:

```json
{"type": "STEP_DATASET", "strength": "data", "source": "step:ACCTFILE#3",
 "target": "dataset:AWS.M2.CARDDEMO.ACCTDATA.VSAM.KSDS", "access": "write", "count": 1,
 "details": [{"dd": "ACCTVSAM", "member": null, "generation": null, "disp": "SHR", "mode_hint": "read"}]}
```

A data store entry (`analysis.data_stores`, shortened) shared by online and batch:

```json
{"id": "dataset:AWS.M2.CARDDEMO.TRANSACT.VSAM.KSDS", "dsn": "AWS.M2.CARDDEMO.TRANSACT.VSAM.KSDS", "gdg": false,
 "cics_files": ["TRANSACT"],
 "online_programs": [{"name": "COBIL00C", "access": "read_write"}, {"name": "COTRN00C", "access": "read"}],
 "batch_programs": [{"name": "CBTRN02C", "access": "write"}],
 "batch_steps": [{"name": "POSTTRAN:STEP15", "access": "write"}, {"name": "TRANBKP:STEP05", "access": "delete"}],
 "writers": ["CBTRN02C", "COBIL00C", "POSTTRAN:STEP15"], "readers": ["COBIL00C", "COTRN00C"], "shared": true}
```

## How step 5 uses the graph

| Need | Graph data |
|---|---|
| Clustering weights | hard edges (`CALL`, `LINK`) strongest, navigation edges (`XCTL`, `RETURN_TRANSID`) weaker; shared data stores (`data_stores`, edges to the same dataset, file or table) |
| Which programs to leave out of clustering | `attrs.system`, `attrs.utility`, subroutines with high fan-in (`analysis.fan`), screens that only navigate (menus, sign-on) |
| Online or batch | `attrs.role` of every program |
| Module seeds | `entry_points.json` (transactions and jobs are confirmed entry points; candidates need a decision) |
| Data ownership | `data` edges with `access` per program and step, `data_stores.writers` |
| Interfaces between modules | edges that cross module boundaries: calls, shared datasets, transactions started by `RETURN_TRANSID` |
| Bundle contents | build edges (`COPY`, `USES_MAP`, `SYMBOLIC_MAP`, `SQL_INCLUDE`) and config edges (`JOB_USES_PROC`, `STEP_CONTROL_CARD`, `CSD_DEFINES`) of the module's programs, jobs and transactions |
| Conversion order | hard edges and build edges (navigation edges do not constrain the order) |
