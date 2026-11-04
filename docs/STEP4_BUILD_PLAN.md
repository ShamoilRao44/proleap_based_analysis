# Step 4 build plan: dependency graph (resolution, entry points, reports)

This document is a complete build instruction. Follow it exactly, in order. Every design decision has already been made. When something is not specified, choose the simplest option that satisfies the text and list it in the final report (section 13). If a test expectation contradicts the algorithm text, follow the algorithm text and report the difference.

The graph joins the facts of step 2 (COBOL) and step 3 (CSD, JCL, BMS, DDL, IMS, control cards) into one typed graph: what runs what, what reads and writes which data, and how execution starts. It is the input of step 5 (modules, bundles, conversion order).

---

## 0. Rules for the implementer

1. **Test only on the AWS repo** (`analysis_out/aws-carddemo`). Never run any tool from this step on `CardDemo-Cobol-main` or CBSA, and do not open their files. The user tests those manually.
2. **Do not modify** anything outside the new folder `graph/` and the docs named in section 11.
3. **Python:** standard library only, Python 3.8. No type hints with generics, no `match`, no walrus operator, no third-party packages (no networkx in this step).
4. JSON: `json.dump(obj, f, indent=1, ensure_ascii=False)`, UTF-8, `newline="\n"`. Names in upper case.
5. Never commit.
6. **Prerequisites** (stop and report if they are missing): `analysis_out/aws-carddemo/inventory.json`, `analysis_out/aws-carddemo/facts/cobol/*.json` (26 files) and the step-3 folders `facts/csd`, `facts/jcl`, `facts/proc`, `facts/bms`, `facts/control`. Do not re-run steps 1–3 yourself unless a file is missing.
7. **Stop conditions:** stop and report if a check in section 10 fails and the cause is not in code you wrote.
8. Write temporary scripts only to the scratchpad directory of your session.

---

## 1. What gets built

```
graph/
├── build_graph.py          CLI
├── README.md
├── graph_lib/
│   ├── __init__.py         (empty)
│   ├── common.py           read/write helpers
│   ├── model.py            Graph class (nodes, edges, merge rules)
│   ├── loaders.py          load inventory and all facts
│   ├── names.py            name resolution (programs, copybooks, mapsets, files, tables, datasets)
│   ├── access.py           access rules (read / write / read_write / delete / unknown)
│   ├── online.py           edges from COBOL facts and CSD
│   ├── batch.py            edges from JCL, PROC, control cards, IDCAMS, IMS
│   ├── analysis.py         entry points, reachability, cycles, fan-in/out, data stores, missing, unused
│   ├── mermaid.py          diagrams
│   └── report.py           graph_report.md
└── tests/
    ├── __init__.py
    ├── helpers.py          builders for synthetic facts (section 9)
    ├── test_model.py
    ├── test_access.py
    ├── test_online.py
    ├── test_batch.py
    └── test_analysis.py
docs/GRAPH_SCHEMA.md
```

Output in `<out>/graph/`:

| File | Content |
|---|---|
| `graph.json` | the graph (schema `cobol-graph/1`, section 7) |
| `graph_report.md` | readable report (section 8) |
| `entry_points.json` | the COBOL entry-point programs and how each one is started (schema `entry-points/1`, section 8.8) |
| `nodes.csv`, `edges.csv` | flat tables for spreadsheets |
| `diagrams/online_flow.mmd`, `diagrams/batch_flow.mmd`, `diagrams/data_access.mmd` | Mermaid diagrams |

CLI:
```
python3 graph/build_graph.py --out <analysis_dir> [--inventory <analysis_dir>/inventory.json]
```
`--inventory` defaults to `<out>/inventory.json`. Prints `[graph] N nodes, M edges, E entry points` and exits 0.

---

## 2. Inputs actually read

`loaders.load_all(out_dir, inventory_path)` returns:

```python
{"root": inventory meta.codebase_root,
 "inventory": [file records],
 "cobol": {member_name: cobol facts},          # facts/cobol/*.json except names starting with "_"
 "csd": [...], "jcl": [...], "proc": [...], "bms": [...], "ddl": [...], "ims": [...], "control": [...]}
```
Missing folders give empty lists. Files are read in sorted path order.

Keys used (nothing else may be relied on):

- **COBOL facts:** `name`, `program_id`, `path`, `kind`, `flags`, `metrics.lines`, `metrics.est_tokens_program`, `source`, `files[].path`, `transfers[]` (`kind`, `target`, `resolved_targets[].value/how`, `unresolved`, `paragraph`, `loc`, `commarea`, `guards`), `resources[]` (`kind`, `name`, `name_resolved[].value`, `mapset`, `mapset_resolved[].value`, `op`, `command`, `unresolved`, `paragraph`, `loc`, `extra`), `files_io[]` (`select`, `dd`, `access_summary`), `copybooks[]` (`name`, `path`, `depth`, `via`, `missing`, `loc`), `sql_includes[]` (`name`, `loc`).
- **CSD facts:** `name`, `path`, `definitions[]` (`type`, `name`, `program`, `dsname`, `queue_type`, `attrs`, `line`).
- **JCL / PROC facts:** `name`, `path`, `kind`, `declared_name`, `flat_steps[]` (`index`, `name`, `kind`, `program`, `proc`, `proc_found`, `utility`, `build`, `cond`, `if_context`, `expanded_from`, `line`, `dds[]`, `invokes[]`, `utility_data`), `procs_used[]`.
- **BMS facts:** `name`, `path`, `mapsets[]` (`name`, `maps[].name`, `symbolic_copybook`).
- **DDL facts:** `path`, `tables[]` (`qualified`, `name`). Inline SQL: `flat_steps[].utility_data.inline_sql.tables[]`.
- **IMS facts:** `kind`, `declared_name`, `path`, `psb.pcbs[]` (`dbdname`, `procopt`, `access_hint`).
- **Control facts:** `name`, `path`, `kind`.
- **Inventory:** `path`, `name`, `type`, `subtype`, `declared_name`, `encoding`.

---

## 3. `model.py`

```python
STRENGTH = {
 "CALL": "hard", "LINK": "hard", "HANDLE_ABEND": "hard",
 "XCTL": "navigation", "RETURN_TRANSID": "navigation", "START_TRANSID": "navigation",
 "TRANSACTION_RUNS": "entry", "JOB_STEP": "entry", "STEP_RUNS": "entry", "STEP_PSB": "entry",
 "COPY": "build", "SQL_INCLUDE": "build", "USES_MAP": "build", "SYMBOLIC_MAP": "build",
 "PROGRAM_CICS_FILE": "data", "CICS_FILE_DATASET": "data", "PROGRAM_DATASET": "data", "STEP_DATASET": "data",
 "IDCAMS_DEFINE": "data", "IDCAMS_DELETE": "data", "DATASET_RELATE": "data", "PROGRAM_DB2_TABLE": "data",
 "PROGRAM_TS_QUEUE": "data", "PROGRAM_TD_QUEUE": "data", "PSB_DBD": "data", "PROGRAM_PSB": "data",
 "JOB_USES_PROC": "config", "STEP_CONTROL_CARD": "config", "CSD_DEFINES": "config",
 "JOB_CICS_COMMAND": "operational",
}

def node_id(type_, name): return type_ + ":" + name

class Graph(object):
    def add_node(self, type_, name, in_codebase=None, **attrs) -> node dict
    def add_edge(self, type_, source_id, target_id, access=None, detail=None) -> edge dict
    def get(self, node_id) -> node dict or None
    def out_edges(self, node_id, types=None) / in_edges(self, node_id, types=None) -> lists
    def to_dict(self) -> {"nodes": [...], "edges": [...]}
```

Node: `{"id", "type", "name", "in_codebase", "attrs": {}}`.
- `add_node` on an existing id merges: `in_codebase` becomes `True` if either value is `True`, else `False` if either is `False`, else `None`; each attribute whose new value is not `None` overwrites, except list values, which are extended with items not yet present.
- `add_edge` requires both nodes to exist (raise `KeyError` otherwise). Edge identity is `(type, source, target)`. A new edge: `{"id": None, "type", "strength": STRENGTH[type], "source", "target", "access", "count": 1, "details": [detail] if detail else []}`. Merging into an existing edge: `count += 1`; `access = access.combine(old, new)`; append `detail` to `details` if it is not `None` and fewer than 50 details exist.
- `to_dict`: nodes sorted by `id`; edges sorted by `(type, source, target)` and then given ids `E1`, `E2`, …

Node types: `program`, `copybook`, `mapset`, `transaction`, `job`, `step`, `proc`, `control_card`, `csd`, `cics_file`, `dataset`, `db2_table`, `ts_queue`, `td_queue`, `psb`, `ims_db`.

Node ids: `program:COSGN00C`, `transaction:CC00`, `job:POSTTRAN` (member name), `step:POSTTRAN#1` (job member + `#` + flat step index), `dataset:AWS.M2.CARDDEMO.ACCTDATA.VSAM.KSDS`, temporary datasets `dataset:&&TEMP@POSTTRAN` (name + `@` + job member), `db2_table:CARDDEMO.AUTHFRDS`, others `type:NAME`.

---

## 4. `access.py`

```python
ORDER = ["read", "write", "read_write", "delete", "unknown"]

def combine(a, b):
    """None + x = x; equal -> same; {read, write} or anything with read_write -> read_write;
    delete + read -> read_write; delete + write -> write; unknown + x -> x (x not None)."""

def from_cics_op(op):   # read, browse -> read; write -> write; update, read_update, delete -> read_write; unlock -> read; else unknown
def from_sql_op(op):    # read -> read; insert -> write; update, delete -> read_write; declare -> None; else unknown
def from_queue_op(op):  # read -> read; write -> write; delete -> delete; else unknown
def from_mode_hint(m):  # create, append -> write; read -> read; old -> read_write; delete -> delete; else unknown
def dd_access(step, dd_name, cobol_by_program):
    """Access of one DD of a flat step. Rules in order:
    1. step program P has COBOL facts and P's files_io has an entry with dd == dd_name -> its access_summary
       (unknown stays unknown);
    2. P == IDCAMS: over utility_data.idcams_commands of verb REPRO/PRINT: dd_name == infile -> read,
       == outfile -> write (both -> read_write); if neither matches fall through;
    3. P in SORT ICEMAN DFSORT SYNCSORT: dd_name starts with SORTIN -> read; dd_name == SORTOUT or starts with SORTOF -> write;
    4. P == IEBGENER: SYSUT1 -> read, SYSUT2 -> write;
    5. otherwise from_mode_hint(dd.mode_hint)."""
```
`dd_access` receives the DD dict (for `mode_hint`), use `dd_access(step, dd, cobol_by_program)` with `dd["name"]` inside.

---

## 5. `names.py` (resolver)

`Resolver(data)` builds these indexes once:

- `program_index`: upper name → member name, from every COBOL facts `name` and `program_id`, and every inventory record of type `assembler` (`name`, `declared_name`).
- `copybook_index`: upper member name → inventory record, for types `copybook` and `dclgen`.
- `bms_index`: upper mapset name → BMS facts file name (from `mapsets[].name`).
- `csd_files`: CICS file name → list of DSNs (all CSD FILE definitions in CSD files and inline CSDs of JCL steps).
- `transactions`: transaction name → `{"program", "defined_in": [...]}` (see 6.1).
- `tables`: upper qualified name → qualified name, and upper short name → qualified name (first wins, sorted by path), from DDL facts and inline SQL tables.
- `control_cards`: upper member name → control facts.
- `procs`: upper member name → proc facts; also upper declared name → proc facts if not taken.

Functions:

```python
SYSTEM_PREFIXES = ("CEE", "DFH", "DSN", "IGZ", "ILBO", "IEF", "IKJ", "CSQ")
SYSTEM_NAMES = {"CBLTDLI", "AIBTDLI", "CEETDLI", "SQLCA", "SQLDA", "MQCONN", "MQCONNX", "MQOPEN", "MQPUT",
                "MQPUT1", "MQGET", "MQCLOSE", "MQDISC", "MQINQ", "MQSET", "MQBEGIN", "MQCMIT", "MQBACK"}
UTILITIES = <copy of scanners jcl.UTILITIES>  # IDCAMS, SORT, ..., as in the step-3 jcl.py

def is_system(name)   # name in SYSTEM_NAMES or name.startswith(SYSTEM_PREFIXES) and name not in program_index
def program(self, g, name)    # add/return program node id; see below
def copybook(self, g, name)
def mapset(self, g, name)
def transaction(self, g, name)
def cics_file(self, g, name)
def table(self, g, name)
def dataset(self, g, dsn, job_member, temp)
```

Each function **adds the node** (with `add_node`) and returns its id:
- `program(name)`: member = `program_index.get(name, name)`; `in_codebase` = name in `program_index`; attrs `system` = `is_system(name)`, `utility` = `name in UTILITIES`.
- `copybook(name)`: `in_codebase` = name in `copybook_index`; attrs `path` (inventory path or null), `subtype` (inventory subtype or null), `kind` (`dclgen` if the inventory type is dclgen else `copybook`), `system` = `is_system(name)` or name starts with `DFH`.
- `mapset(name)`: `in_codebase` = name in `bms_index`; attr `bms` = BMS facts name or null.
- `transaction(name)`: `in_codebase` = name in `transactions` (meaning: defined in a CSD of the codebase).
- `cics_file(name)`: `in_codebase` = name in `csd_files`; attr `dsnames` = the list.
- `table(name)`: canonical = `tables.get(name, name)`; id `db2_table:<canonical>`; `in_codebase` = name in `tables`.
- `dataset(dsn, job_member, temp)`: id `dataset:<dsn>` or, when `temp`, `dataset:<dsn>@<job_member>`; `in_codebase` = None; attrs `temp`, `unresolved` (= `"&" in dsn and not temp`).

---

## 6. Edges

### 6.1 `online.py`: `add_online(g, r, data)`

1. **CSD nodes and definitions.** For every CSD facts file F: node `csd:<F.name>` (in_codebase True, attr `path`). For every inline CSD (every flat step of every JCL facts that has `utility_data.inline_csd`): the defining node is the job node `job:<J.name>` (create it with in_codebase True, attr `path`). For each definition D:
   - `TRANSACTION`: node `transaction:<D.name>` (in_codebase True, attrs `program` = D.program, `defined_in` = [defining node id]); edge `CSD_DEFINES` defining node → transaction, detail `{"line": D.line}`; if `D.program`: `TRANSACTION_RUNS` transaction → `r.program(D.program)`, detail `{"source": defining node id}`.
   - `PROGRAM`: program node via `r.program(D.name)` plus attr `csd_defined` = True; edge `CSD_DEFINES`.
   - `MAPSET`: `r.mapset(D.name)` plus attr `csd_defined` = True; edge `CSD_DEFINES`.
   - `FILE`: `r.cics_file(D.name)`; edge `CSD_DEFINES`; if `D.dsname`: `CICS_FILE_DATASET` cics_file → `r.dataset(D.dsname, None, False)`, detail `{"source": defining node id}`.
   - `TDQUEUE`: node `td_queue:<D.name>` (in_codebase True, attrs `queue_type` = D.queue_type, `ddname` = `D.attrs.get("DDNAME")`, `internal_reader` = (`str(D.attrs.get("DDNAME", "")).upper() == "INREADER"`)); edge `CSD_DEFINES`.
   - other types: ignored.
2. **BMS.** For each BMS facts file, each mapset M: `r.mapset(M.name)` with attrs `maps` = list of map names, `path`; if `M.symbolic_copybook`: `SYMBOLIC_MAP` mapset → `r.copybook(<member name of that path>)`.
3. **Programs.** For each COBOL facts C (sorted by name): node `program:<C.name>` with in_codebase True and attrs `path`, `kind` (C.kind), `program_id`, `lines` (metrics.lines), `est_tokens` (metrics.est_tokens_program), `source` (C.source), `uses_cics`, `uses_db2`, `uses_ims`, `uses_mq` (from flags). Evidence helper: `ev(C, loc)` = `{"file": C.files[loc[0]].path if loc[0] < len(C.files) else None, "line": loc[1]}`.
4. **Transfers** of C (skip `GOBACK`, `STOP_RUN`, `EXIT_PROGRAM`, `RETURN`): for each value V in `resolved_targets`:
   - kinds `CALL`, `LINK`, `XCTL`, `HANDLE_ABEND`: edge of that type C → `r.program(V)`;
   - kinds `RETURN_TRANSID`, `START_TRANSID`: edge C → `r.transaction(V)`;
   - detail: `{"how": value's how, "paragraph", "file", "line", "commarea", "guards": first 2 guards}`.
   Transfers with `unresolved` true are not edges; they go to the `unresolved` list (8.9).
5. **Resources** of C:
   - `cics_file`: for each value V in `name_resolved`: `PROGRAM_CICS_FILE` C → `r.cics_file(V)`, access `from_cics_op(op)`, detail `{"op", "command", "paragraph", "file", "line"}`.
   - `map`: for each V in `mapset_resolved`: `USES_MAP` C → `r.mapset(V)`, detail `{"map": name literal or var text, "op", "paragraph", "file", "line"}`.
   - `db2_table`: skip when `op == "declare"`; for each V in `name_resolved`: `PROGRAM_DB2_TABLE` C → `r.table(V)`, access `from_sql_op(op)`, detail `{"op", "command", "paragraph", "file", "line"}`.
   - `ts_queue` / `td_queue`: for each V in `name_resolved`: `PROGRAM_TS_QUEUE` / `PROGRAM_TD_QUEUE` to node `ts_queue:V` / `td_queue:V` (create with in_codebase None if not defined), access `from_queue_op(op)`.
   - `ims_call`, `mq_call`, `terminal`, `container`, `batch_file`: no edges (batch files are handled in 6.2). Count them in program attrs `ims_calls`, `mq_calls`.
   - resources with `unresolved` true go to the `unresolved` list.
6. **Copybooks** of C: for each entry E: target `r.copybook(E.name)`; source = C if `E.via` is null else `r.copybook(E.via)`; edge `COPY`, detail `{"file", "line": E.loc[1], "depth": E.depth}`.
7. **SQL includes** of C: `SQL_INCLUDE` C → `r.copybook(name)`.

### 6.2 `batch.py`: `add_batch(g, r, data)`

`cobol_by_program` = dict from upper COBOL member name and program_id → facts.

1. **Proc nodes:** for every PROC facts P: node `proc:<P.name>` (in_codebase True, attrs `path`, `declared_name`). **Control cards:** for every control facts K: node `control_card:<K.name>` (in_codebase True, attrs `path`, `kind`).
2. For every JCL facts J with `kind` in (`job`, `fragment`): node `job:<J.name>` (in_codebase True, attrs `path`, `declared_name`, `kind`).
   - For each `procs_used` entry U with `found` true: `JOB_USES_PROC` job → `proc:<member>` where member = `r.procs[U.name].name` (the member name the resolver found; this gives the member `REPROC` for name `REPROC`).
   - For each flat step S (in order): node `step:<J.name>#<S.index>` (in_codebase True, attrs `job` = J.name, `name` = S.name, `index`, `program`, `kind`, `expanded_from`, `cond`, `if_context`, `utility`, `line`); edge `JOB_STEP` job → step, detail `{"index": S.index}`.
   - **Programs:** if `S.kind == "program"` and `S.program`: `STEP_RUNS` step → `r.program(S.program)`. For each `invokes` entry whose program differs from `S.program`: `STEP_RUNS` step → `r.program(entry.program)` with detail `{"via": entry.via, "plan": entry.get("plan")}`. If an invokes entry has `psb`: `STEP_PSB` step → `psb:<psb>` (create node, in_codebase None) and `PROGRAM_PSB` `r.program(entry.program)` → `psb:<psb>`.
   - **DDs:** for each DD D of S: skip if `D.dsn` is null, or `D.dummy`, `D.sysout`, `D.null_file`, `D.inline` is not null, or `D.mode_hint == "library"`. Otherwise dataset id `r.dataset(D.dsn, J.name, D.temp)`; set dataset attr `gdg` = True when `D.generation` is not null; access `a = dd_access(S, D, cobol_by_program)`; edge `STEP_DATASET` step → dataset, access `a`, detail `{"dd": D.name, "member": D.member, "generation": D.generation, "disp": D.disp.raw or null, "mode_hint": D.mode_hint}`.
     - If `D.member` is not null and `D.member` is in `r.control_cards`: `STEP_CONTROL_CARD` step → `control_card:<member>`, detail `{"dd": D.name, "dsn": D.dsn}`.
     - If the step program has COBOL facts and its `files_io` has an entry with `dd == D.name`: `PROGRAM_DATASET` `r.program(S.program)` → dataset, access = that entry's `access_summary`, detail `{"job": J.name, "step": S.name, "dd": D.name}`.
   - **Expected but missing DDs:** for a step whose program has COBOL facts, every `files_io[].dd` that is not the name of any DD of the step goes to the `unresolved` list as `{"kind": "dd_missing", "job", "step", "program", "dd"}`.
   - **IDCAMS commands** (`utility_data.idcams_commands`): for each command C:
     - `DEFINE` with `name`: dataset `r.dataset(C.name, J.name, C.name.startswith("&&"))`; `IDCAMS_DEFINE` step → dataset, access `write`, detail `{"subtype": C.subtype, "line": C.line}`; if `subtype == "GDG"` set dataset attr `gdg` = True. If `C.attrs.RELATE`: `DATASET_RELATE` dataset → `r.dataset(RELATE, ...)`, detail `{"kind": "AIX"}`. If `subtype == "PATH"`: find `PATHENTRY\s*\(\s*([^)\s]+)` in `C.text` (case-insensitive); if found: `DATASET_RELATE` dataset → that dataset, detail `{"kind": "PATH"}`.
     - `DELETE`: for each name in `C.names`: `IDCAMS_DELETE` step → dataset, access `delete`, detail `{"object_type": C.object_type, "line": C.line}`.
     - `REPRO` / `PRINT` with `indataset` / `outdataset`: `STEP_DATASET` step → dataset with access `read` / `write`, detail `{"dd": null, "via": "IDCAMS " + verb}`.
   - **SDSF commands** (`utility_data.sdsf_commands`): for each command with `resource_type == "FILE"`: `JOB_CICS_COMMAND` job → `r.cics_file(resource)`, detail `{"action", "region", "step": S.name}`.
3. **IMS:** for every IMS facts with `kind == "psb"`: node `psb:<declared_name>` (in_codebase True, attr `path`); for each PCB with `dbdname`: `PSB_DBD` psb → `ims_db:<dbdname>` (create; in_codebase True if a DBD facts with that declared name exists, else False), access `"read_write"` if `access_hint == "update"` else `"read"`, detail `{"procopt", "pcb": index}`. For every DBD facts: node `ims_db:<declared_name>` (in_codebase True, attr `path`).
4. **Tables:** for every table found in DDL facts and inline SQL: node via `r.table(qualified)` with attr `defined_in` = list of paths (DDL file path, or `"<jcl path> (inline SQL)"`).

---

## 7. Graph JSON (`cobol-graph/1`)

`build_graph.py` order: `load_all` → `Resolver` → `add_online` → `add_batch` → `analysis.run(g, data)` (adds node attrs and returns the analysis dict) → write files.

```json
{"schema": "cobol-graph/1", "generated": "<iso time>", "codebase_root": "...",
 "inputs": {"cobol": 26, "csd": 1, "jcl": 28, "proc": 2, "bms": 17, "ddl": 0, "ims": 0, "control": 1},
 "stats": {"nodes_by_type": {...}, "edges_by_type": {...}},
 "nodes": [...], "edges": [...],
 "entry_points": [...], "unresolved": [...], "analysis": {...}}
```

- `entry_points` (from analysis): `[{"type": "transaction", "id", "program"}]` for each transaction node with an outgoing `TRANSACTION_RUNS` edge; `[{"type": "job", "id", "programs": [...]}]` for each job node (`programs` = targets of `STEP_RUNS` from its steps, sorted, as program names); `[{"type": "candidate_program", "id", "reason": "no caller, no transaction, no job"}]` for candidate entry programs (8.7).
- `unresolved`: list of objects `{"kind", ...}` with kinds `dynamic_transfer` (`program`, `transfer_kind`, `target_text`, `file`, `line`), `dynamic_resource` (`program`, `resource_kind`, `name_text`, `file`, `line`), `dd_missing` (6.2), `proc_not_found` (`job`, `step`, `proc`), `unresolved_symbols` (`job`, `names`). Sorted by `(kind, json.dumps(item, sort_keys=True))`.
- `analysis`: the dict returned by `analysis.run` (section 8).

`nodes.csv`: header `id,type,name,in_codebase`; `edges.csv`: header `id,type,strength,source,target,access,count`. Use the `csv` module.

---

## 8. `analysis.py`

`run(g, data)` computes and returns `{"reach": ..., "candidates": [...], "orphans": [...], "sccs_hard": [...], "sccs_navigation": [...], "fan": [...], "data_stores": [...], "missing": {...}, "unused": {...}, "batch_submitters": [...]}` and sets program node attrs `role`.

### 8.1 Program-level views

- `prog(id)`: node type `program` and `in_codebase` True and attr `system` not True and attr `utility` not True ("application program").
- **Hard graph:** program → program for `CALL`, `LINK`, `HANDLE_ABEND`.
- **Navigation graph:** program → program for `XCTL`; plus for `RETURN_TRANSID` / `START_TRANSID` edges P → transaction T, add P → Q for each `TRANSACTION_RUNS` T → Q.
- Self edges are kept in the graph but ignored for SCCs.

### 8.2 Reachability and roles

- Online seeds: programs targeted by `TRANSACTION_RUNS`. Batch seeds: programs targeted by `STEP_RUNS`.
- `reach_online` = closure over hard + navigation graph from online seeds; `reach_batch` = closure over hard graph from batch seeds (navigation edges are not followed from batch).
- Program attr `role`: `online` (only in reach_online), `batch` (only in reach_batch), `both`, or `unreached`. Set it for every program node.

### 8.3 Candidates and orphans

- **Candidate entry programs:** application programs with no incoming edge of type `CALL`, `LINK`, `XCTL`, `HANDLE_ABEND`, `TRANSACTION_RUNS`, `STEP_RUNS`. Sorted names.
- **Orphans:** application programs with role `unreached`. Sorted names.

### 8.4 Cycles

Iterative Tarjan SCC (no recursion) over application programs, separately for the hard graph and the navigation graph. Keep components with more than one member; each component is a sorted list of names; components sorted by (−size, first name).

### 8.5 Fan-in / fan-out

For each application program: `hard_in`, `hard_out`, `nav_in`, `nav_out` = number of distinct other programs; `data` = number of distinct nodes reached by `PROGRAM_CICS_FILE`, `PROGRAM_DATASET`, `PROGRAM_DB2_TABLE`, `PROGRAM_TS_QUEUE`, `PROGRAM_TD_QUEUE`. List sorted by (−hard_in, −nav_in, name).

### 8.6 Data stores

For each `dataset` node D (not temp):
- `online_programs`: programs P with `PROGRAM_CICS_FILE` P → F and `CICS_FILE_DATASET` F → D; with their combined access.
- `batch_programs`: programs with `PROGRAM_DATASET` → D, with access.
- `batch_steps`: `job:step` names with `STEP_DATASET`, `IDCAMS_DEFINE` or `IDCAMS_DELETE` → D, with access.
- `cics_files`: the files F.
- `writers`: names (programs and steps) whose access is `write` or `read_write` (and `IDCAMS_DEFINE`); `readers`: access `read` or `read_write`.
- `shared` = `online_programs` non-empty and (`batch_programs` or `batch_steps`) non-empty.
Entry `{"id", "dsn", "gdg", "cics_files", "online_programs": [{"name", "access"}], "batch_programs": [...], "batch_steps": [...], "writers", "readers", "shared"}`, sorted by dsn.

### 8.7 Missing, unused, batch submitters

- `missing.programs`: program nodes with `in_codebase` False, not system, not utility, with `referenced_by` = sorted source names of incoming `CALL`/`LINK`/`XCTL`/`HANDLE_ABEND`/`TRANSACTION_RUNS`/`STEP_RUNS`/`CSD_DEFINES` edges (strip the `type:` prefix).
- `missing.copybooks`: copybook nodes with in_codebase False, split into `ibm` (attr system True) and `other`.
- `missing.mapsets`: mapset nodes with in_codebase False that have an incoming `USES_MAP` edge (mapsets only defined in a CSD are not missing).
- `missing.cics_files`: cics_file nodes with in_codebase False.
- `missing.transactions`: transaction nodes with in_codebase False.
- `missing.datasets_unresolved`: dataset nodes with attr `unresolved` True.
- `unused.copybooks`: inventory files of type `copybook`/`dclgen` whose copybook node has no incoming `COPY`, `SQL_INCLUDE` or `SYMBOLIC_MAP` edge (or no node).
- `unused.procs`: proc nodes without incoming `JOB_USES_PROC`.
- `unused.mapsets`: BMS mapsets (in_codebase True) without incoming `USES_MAP`.
- `unused.control_cards`: control_card nodes without incoming `STEP_CONTROL_CARD`.
- `batch_submitters`: programs with a `PROGRAM_TD_QUEUE` edge with access `write` or `read_write` to a td_queue whose attr `internal_reader` is True: `{"program", "queue"}`.

### 8.8 Entry-point programs (`entry_points.json`)

Definition: an entry point is an application program (8.1) that **starts a unit of work**. "Depends on" means the hard edges only (`CALL`, `LINK`, `HANDLE_ABEND`); `XCTL` and `RETURN_TRANSID` are screen navigation and do **not** make a program dependent (otherwise CICS menus, which XCTL to every screen and back, would leave no online entry points). Copybooks play no role in the decision.

For every application program P compute:
- `transactions`: sorted names of transactions with `TRANSACTION_RUNS` → P;
- `jobs`: sorted list of `{"job", "step"}` (job member, flat step name) for `STEP_RUNS` → P;
- `hard_callers`: sorted names of application programs with a hard edge → P (self edges ignored);
- `nav_callers`: sorted names of application programs with `XCTL` → P, or with `RETURN_TRANSID`/`START_TRANSID` to a transaction that runs P (self ignored);
- `calls`: sorted names of programs P reaches with a hard edge (including system programs, marked by suffix ` (system)`); `xctl_to`: sorted `XCTL` targets;
- `copybooks`: number of distinct copybooks with `COPY` from P.

Classification (first rule that applies):
1. `transactions` and `jobs` both non-empty → `entry_type = "both"`, `confidence = "confirmed"`.
2. `transactions` non-empty → `"cics_transaction"`, `"confirmed"`.
3. `jobs` non-empty → `"jcl_job"`, `"confirmed"`.
4. `hard_callers` empty and `nav_callers` empty → `"candidate"`, `"heuristic"`, with note `"no caller, no transaction and no job in the codebase: dead code or started from outside (scheduler, other system)"`.
5. otherwise P is **not** an entry point: it goes to `not_entry_points` with `reason = "called"` if `hard_callers` is non-empty (a subroutine), else `reason = "navigation target"` (a screen reached only by XCTL / RETURN TRANSID from other programs).

Entries of rules 1–3 that also have `hard_callers` get the note `"also called by other programs"` and `also_called = true` (else false).

File:
```json
{"schema": "entry-points/1", "generated": "<iso time>", "codebase_root": "...",
 "rule": "entry point = application program started by a CICS transaction or a JCL step, or with no CALL/LINK caller; XCTL is navigation and is not counted as a dependency",
 "summary": {"entry_points": n, "cics_transaction": n, "jcl_job": n, "both": n, "candidate": n,
             "not_entry_points": n, "unresolved_dynamic_calls": n},
 "entry_points": [{"name", "kind", "path", "entry_type", "confidence", "transactions", "jobs", "hard_callers",
                   "also_called", "nav_callers", "calls", "xctl_to", "copybooks", "notes"}],
 "not_entry_points": [{"name", "kind", "path", "reason", "hard_callers", "nav_callers"}]}
```
`kind` and `path` come from the program node attrs. Both lists are sorted by name. `unresolved_dynamic_calls` = number of `unresolved` items of kind `dynamic_transfer` with `transfer_kind` in (`CALL`, `LINK`); if it is greater than 0, every `candidate` entry gets the extra note `"<n> dynamic CALL/LINK targets are unresolved in the codebase; this program may be one of them"`.

Also add a report section **Entry-point programs** (after section 3 of 8b): table `| Program | Entry type | Confidence | Transactions | Jobs | Also called |` and the `not_entry_points` list.

---

## 8a. `mermaid.py`

Write three files, each starting with the line `flowchart LR`. Mermaid node ids: the graph id with every character not in `[A-Za-z0-9_]` replaced by `_`. Labels in double quotes; replace `"` in labels by `'`. At most 300 edges per diagram; if more, write the first 300 (in graph edge order) and a final line `%% truncated: N more edges`.

- `online_flow.mmd`: nodes = transactions with `TRANSACTION_RUNS` edges, programs with role `online` or `both`, mapsets used by them; edges `TRANSACTION_RUNS` (`-->`), `XCTL` (`-.->|XCTL|`), `LINK` (`-->|LINK|`), `CALL` (`-->|CALL|`), `RETURN_TRANSID` (`-.->|RETURN|`), `USES_MAP` (`---`). Program labels: name; transaction labels: `TRAN <name>`; mapset labels: `MAP <name>`.
- `batch_flow.mmd`: for each job: a `subgraph` named after the job containing its steps (label `<step name>: <program>`); edges `STEP_DATASET` / `IDCAMS_DEFINE` with access write or read_write drawn step → dataset, access read drawn dataset → step, delete drawn step → dataset with label `|delete|`; dataset labels are the DSN.
- `data_access.mmd`: application programs and data nodes (dataset, cics_file, db2_table, ts_queue, td_queue); edges `PROGRAM_CICS_FILE`, `CICS_FILE_DATASET`, `PROGRAM_DATASET`, `PROGRAM_DB2_TABLE`, `PROGRAM_TS_QUEUE`, `PROGRAM_TD_QUEUE` with the access as the edge label.

---

## 8b. `report.py`: `graph_report.md`

Sections in this order (write `none` for empty lists):

1. `# Dependency graph: <codebase_root>`; a line with generation time, node and edge counts.
2. **Counts:** table nodes by type; table edges by type with strength.
3. **Entry points:** (a) transactions: `| Transaction | Program | Program in codebase | Defined in |`; (b) jobs: `| Job | Steps | Programs run |`; (c) candidate entry programs.
4. **Online flow:** per transaction: program, the programs reachable from it over hard + navigation edges (sorted), mapsets used by those programs.
5. **Batch jobs:** per job: one line per flat step `step name: program — reads: DSNs; writes: DSNs` (access per `STEP_DATASET`/IDCAMS edge).
6. **Data stores:** table `| Dataset | CICS files | Online programs | Batch programs | Batch steps | Shared |` (names with access in brackets, for example `CBTRN02C (read_write)`).
7. **Online programs that submit batch jobs** (`batch_submitters`).
8. **Fan-in / fan-out:** top 20 rows of 8.5.
9. **Cycles:** hard SCCs and navigation SCCs.
10. **Orphans** (8.3).
11. **Missing:** each list of 8.7 `missing` as a sub-section.
12. **Unused:** each list of 8.7 `unused`.
13. **Unresolved:** grouped by kind; at most 100 rows per kind.

---

## 9. Unit tests (`graph/tests/`)

`helpers.py` provides builders that create minimal facts dicts with only the keys listed in section 2 (all other keys absent):

```python
def cobol(name, kind="cics_online", transfers=(), resources=(), files_io=(), copybooks=(), sql_includes=(), program_id=None)
def transfer(kind, values, how="literal", unresolved=False, target_text=None)  # loc [0, 10], paragraph "P1"
def resource(kind, values=(), op="read", mapset_values=(), unresolved=False)
def csd_file(name, definitions)          # definitions: list of dicts with type, name and optional program/dsname/attrs
def jcl_file(name, steps, procs_used=())  # steps: list of flat step dicts
def step(index, name, program, dds=(), invokes=None, utility=None, utility_data=None, kind="program")
def dd(name, dsn, mode_hint="read", member=None, generation=None, temp=False)
def data(cobol=(), csd=(), jcl=(), proc=(), bms=(), ddl=(), ims=(), control=(), inventory=())  # the load_all dict
```
`step(...)` sets `utility` to `program in UTILITIES` when not given and `invokes` to `[{"program": program, "via": "EXEC PGM"}]` for non-utility programs when not given. `cobol(...)` gives `files = [{"index": 0, "path": name + ".cbl"}]`, `metrics = {"lines": 10, "est_tokens_program": 5}`, `flags` all false except `uses_cics` for kind `cics_online`, `path = name + ".cbl"`, `source = "proleap"`.

Tests (exact assertions):

`test_model.py`
- adding the same edge twice gives `count == 2`, access `read` + `write` → `read_write`, two details; `to_dict` sorts edges and assigns `E1`…
- `add_node` merge: `in_codebase` None then True → True; list attr extended without duplicates.
- `add_edge` with an unknown node raises `KeyError`.

`test_access.py`
- `combine`: `(None, "read") → "read"`, `("read", "write") → "read_write"`, `("delete", "read") → "read_write"`, `("delete", "write") → "write"`, `("unknown", "read") → "read"`.
- `dd_access`: program with facts `files_io=[{"select": "F", "dd": "TRANFILE", "access_summary": "write"}]`, DD TRANFILE → `write`; IDCAMS with `idcams_commands=[{"verb": "REPRO", "infile": "IN", "outfile": "OUT"}]`: DD IN → `read`, DD OUT → `write`; SORT: SORTIN → `read`, SORTOUT → `write`; IEBGENER: SYSUT1 → `read`, SYSUT2 → `write`; IEFBR14 with mode_hint `delete` → `delete`; unknown program with mode_hint `create` → `write`.

`test_online.py`
- CSD with `TRANSACTION CC00 program COSGN00C`, `FILE ACCTDAT dsname AWS.ACCT`, `TDQUEUE JOBS attrs {"DDNAME": "INREADER", "TYPE": "EXTRA"}`; COBOL `COSGN00C` with transfer `XCTL ["COMEN01C"]`, `RETURN_TRANSID ["CC00"]`, resource `cics_file ["ACCTDAT"] op read`; COBOL `COMEN01C` with resource `map` mapset `["COMEN01"]` op send and `td_queue ["JOBS"] op write`; →
  edges: `TRANSACTION_RUNS transaction:CC00 → program:COSGN00C`, `XCTL program:COSGN00C → program:COMEN01C`, `RETURN_TRANSID program:COSGN00C → transaction:CC00`, `PROGRAM_CICS_FILE program:COSGN00C → cics_file:ACCTDAT` (access read), `CICS_FILE_DATASET cics_file:ACCTDAT → dataset:AWS.ACCT`, `USES_MAP program:COMEN01C → mapset:COMEN01`, `PROGRAM_TD_QUEUE program:COMEN01C → td_queue:JOBS` (access write); node `td_queue:JOBS` attr `internal_reader` True; node `mapset:COMEN01` in_codebase False.
- Unresolved transfer (`unresolved=True`, values empty) → no edge, one `unresolved` entry of kind `dynamic_transfer`.
- `CALL ["CEE3ABD"]` → node `program:CEE3ABD` with in_codebase False and attr `system` True.
- copybooks `[{"name": "A", "depth": 1, "via": None}, {"name": "B", "depth": 2, "via": "A"}]` → `COPY program:X → copybook:A` and `COPY copybook:A → copybook:B`.

`test_batch.py`
- JCL `J` with step 1 `S1` program `CBTRN02C`, DDs `TRANFILE` (dsn `AWS.TRAN`, mode read) and `DALYREJS` (dsn `AWS.REJ`, generation `+1`, mode create); COBOL `CBTRN02C` (kind batch_main) with `files_io` `TRANFILE write`, `DALYREJS write`, `XREFFILE read` →
  `JOB_STEP job:J → step:J#1`, `STEP_RUNS step:J#1 → program:CBTRN02C`, `STEP_DATASET step:J#1 → dataset:AWS.TRAN` access write, `PROGRAM_DATASET program:CBTRN02C → dataset:AWS.TRAN` access write, dataset `AWS.REJ` attr `gdg` True, and one `unresolved` item `{"kind": "dd_missing", "dd": "XREFFILE", ...}`.
- IDCAMS step with `idcams_commands` `[{"verb": "DEFINE", "subtype": "CLUSTER", "name": "AWS.K", "names": ["AWS.K"], "attrs": {}, "text": "", "line": 5}, {"verb": "DELETE", "subtype": "CLUSTER", "object_type": "CLUSTER", "name": "AWS.K", "names": ["AWS.K"], "attrs": {}, "text": "", "line": 3}, {"verb": "DEFINE", "subtype": "AIX", "name": "AWS.K.AIX", "names": ["AWS.K.AIX"], "attrs": {"RELATE": "AWS.K"}, "text": "", "line": 7}]` → `IDCAMS_DEFINE step → dataset:AWS.K` (write), `IDCAMS_DELETE step → dataset:AWS.K` (delete), `DATASET_RELATE dataset:AWS.K.AIX → dataset:AWS.K`.
- Temp dataset DD (`&&TEMP`, temp True) in job `J` → node `dataset:&&TEMP@J`.
- DD with `member == "REPROCT"` and a control facts `REPROCT` → `STEP_CONTROL_CARD step → control_card:REPROCT`.
- SDSF step with `sdsf_commands` `[{"resource_type": "FILE", "resource": "ACCTDAT", "action": "CLOSE", "region": "R"}]` → `JOB_CICS_COMMAND job:J → cics_file:ACCTDAT`.
- `invokes` with `{"program": "PAUTB01", "psb": "PSBX", "via": "DFSRRC00 PARM"}` on a `DFSRRC00` step → `STEP_RUNS step → program:PAUTB01`, `STEP_PSB step → psb:PSBX`, `PROGRAM_PSB program:PAUTB01 → psb:PSBX`.

`test_analysis.py`
- Programs A, B, C, D (all in codebase): transaction T → A; A XCTL B; B XCTL A; job J step runs C; C CALL D; program E with no edges →
  roles A, B `online`; C, D `batch`; E `unreached`; candidates `["E"]`; orphans `["E"]`; navigation SCCs `[["A", "B"]]`; hard SCCs `[]`.
- RETURN_TRANSID composition: A RETURN_TRANSID T2, T2 → B, B XCTL A → navigation SCC `[["A", "B"]]`.
- Data store shared: online program with `PROGRAM_CICS_FILE` → file F → dataset D, and a step with `STEP_DATASET` → D → `shared` True.
- Tarjan on a 1000-node chain does not hit the recursion limit.
- Entry points on the first graph of this file: A `cics_transaction` (confirmed, `nav_callers == ["B"]`); B (reached only by `XCTL` from A, no transaction, no job) → `not_entry_points` with `reason == "navigation target"` and `nav_callers == ["A"]`; C `jcl_job`; D in `not_entry_points` with `reason == "called"` and `hard_callers == ["C"]`; E `candidate`. Add a variant where D is also run by a job step → D `jcl_job` with `also_called == true`.

---

## 10. Acceptance checks on AWS (`analysis_out/aws-carddemo`)

Run `python graph/build_graph.py --out analysis_out/aws-carddemo`. Load `graph/graph.json` in a scratch script.

| # | Check | Pass criteria |
|---|---|---|
| G1 | Run | exit 0; `graph.json`, `graph_report.md`, `nodes.csv`, `edges.csv` and the 3 `.mmd` files exist; `inputs == {"cobol": 26, "csd": 1, "jcl": 28, "proc": 2, "bms": 17, "ddl": 0, "ims": 0, "control": 1}` |
| G2 | Node counts | program nodes with in_codebase True: 26; transaction nodes: 23 (18 from `CARDDEMO.CSD`, 5 from the inline CSD of `CBADMCDJ`), each with exactly one outgoing `TRANSACTION_RUNS`; job nodes: 28; mapset nodes with in_codebase True: 17; `csd:CARDDEMO` exists |
| G3 | README online inventory | for each row (transaction → program → mapset): CC00 COSGN00C COSGN00; CM00 COMEN01C COMEN01; CAVW COACTVWC COACTVW; CAUP COACTUPC COACTUP; CCLI COCRDLIC COCRDLI; CCDL COCRDSLC COCRDSL; CCUP COCRDUPC COCRDUP; CT00 COTRN00C COTRN00; CT01 COTRN01C COTRN01; CT02 COTRN02C COTRN02; CR00 CORPT00C CORPT00; CB00 COBIL00C COBIL00; CA00 COADM01C COADM01; CU00 COUSR00C COUSR00; CU01 COUSR01C COUSR01; CU02 COUSR02C COUSR02; CU03 COUSR03C COUSR03 — edges `TRANSACTION_RUNS transaction:T → program:P` and `USES_MAP program:P → mapset:M` exist |
| G4 | README batch inventory | `job:POSTTRAN` runs `CBTRN02C`; `job:INTCALC` runs `CBACT04C`; `job:COMBTRAN` runs `SORT`; `ACCTFILE`, `CARDFILE`, `XREFFILE`, `TCATBALF`, `TRANBKP`, `TRANIDX` each run `IDCAMS` ("runs" = some step of the job has `STEP_RUNS` to that program); `job:CLOSEFIL` and `job:OPENFIL` run `SDSF` (the README says IEFBR14; list this difference in the final report); there is no `job:CBTRNLDJ` and no `job:CBTRNRPJ` (listed in the README, not in the repo) |
| G5 | XCTL | `XCTL` targets of `program:COMEN01C` are exactly COACTUPC, COACTVWC, COBIL00C, COCRDLIC, COCRDSLC, COCRDUPC, CORPT00C, COSGN00C, COTRN00C, COTRN01C, COTRN02C; of `COADM01C` exactly COSGN00C, COUSR00C, COUSR01C, COUSR02C, COUSR03C; of `COSGN00C` exactly COADM01C, COMEN01C |
| G6 | CALL | callers (`CALL` sources) of `program:CSUTLDTC` are exactly COACTUPC, CORPT00C, COTRN02C; `program:CEE3ABD` has in_codebase False and `system` True |
| G7 | Data | 8 `CICS_FILE_DATASET` edges (one per CSD FILE); `PROGRAM_DATASET program:CBTRN02C → dataset:AWS.M2.CARDDEMO.TRANSACT.VSAM.KSDS` access `write`, `→ dataset:AWS.M2.CARDDEMO.ACCTDATA.VSAM.KSDS` access `read_write`; in job `ACCTFILE`, the step named `STEP15` has `STEP_DATASET` to `AWS.M2.CARDDEMO.ACCTDATA.VSAM.KSDS` with access `write` (REPRO OUTFILE) and to `AWS.M2.CARDDEMO.ACCTDATA.PS` with access `read`; step `STEP10` has `IDCAMS_DEFINE` to `AWS.M2.CARDDEMO.ACCTDATA.VSAM.KSDS`; step `STEP05` has `IDCAMS_DELETE` to it. Data stores with `shared` True include at least: ACCTDATA.VSAM.KSDS, CARDDATA.VSAM.KSDS, CARDXREF.VSAM.KSDS, CUSTDATA.VSAM.KSDS, TRANSACT.VSAM.KSDS, USRSEC.VSAM.KSDS, CARDXREF.VSAM.AIX.PATH (all with prefix `AWS.M2.CARDDEMO.`); list any further shared ones in the final report |
| G8 | Batch submitter | `PROGRAM_TD_QUEUE program:CORPT00C → td_queue:JOBS` access `write`; `td_queue:JOBS` attr `internal_reader` True; `analysis.batch_submitters == [{"program": "CORPT00C", "queue": "JOBS"}]` |
| G9 | SDSF | `JOB_CICS_COMMAND` edges from `job:CLOSEFIL` go to exactly `cics_file:` ACCTDAT, CCXREF, CXACAIX, TRANSACT, USRSEC, each with a detail `action == "CLOSE"`; same five from `job:OPENFIL` with `OPEN` |
| G10 | Procs and control cards | `JOB_USES_PROC` from `job:TRANREPT`, `job:TRANBKP` and `job:PRTCATBL` to `proc:REPROC`; their step named `STEP05R.PRC001` has `STEP_CONTROL_CARD` to `control_card:REPROCT`; `analysis.unused.procs == ["TRANREPT"]` (the PROC member `TRANREPT.prc`); `analysis.unused.control_cards == []` |
| G11 | Entry and orphans | `analysis.candidates == ["CBTRN01C"]` and `analysis.orphans == ["CBTRN01C"]`; roles: the 17 online programs of G3 are `online`; CBACT01C, CBACT02C, CBACT03C, CBACT04C, CBCUS01C, CBTRN02C, CBTRN03C are `batch`; CSUTLDTC is `online` (called only by online programs) |
| G12 | Cycles | `analysis.sccs_hard == []`; `analysis.sccs_navigation` has exactly one component, and it equals the sorted 17 online program names of G3 |
| G13 | Missing | `analysis.missing.programs` names include COCRDSEC (referenced by `csd:CARDDEMO`) and the 10 programs of the inline CSD of CBADMCDJ that have no source (COACT00C, COACTDEC, COADM00C, COTRNATC, COTRNVDC, COTRNVWC, COTSTP1C, COTSTP2C, COTSTP3C, COTSTP4C), and nothing else; `analysis.missing.copybooks.ibm` contains DFHAID and DFHBMSCA; `missing.copybooks.other == []`; `missing.mapsets == []`; `missing.cics_files == []`; `missing.transactions == []` |
| G14 | Unresolved | there is no `dynamic_transfer` or `dynamic_resource` item; `dd_missing` items: none |
| G15 | Determinism | running the CLI twice gives identical `graph.json` except the `generated` value |
| G16 | Mermaid | each `.mmd` starts with `flowchart LR`; every node id used matches `^[A-Za-z0-9_]+$` |
| G17 | `entry_points.json` | 25 entry points: the 17 online programs of G3 with `entry_type == "cics_transaction"` and `confidence == "confirmed"` (for example `COSGN00C` with `transactions == ["CC00"]`, `COMEN01C` with `["CM00"]` and `nav_callers` containing `COSGN00C`); CBACT01C, CBACT02C, CBACT03C, CBACT04C, CBCUS01C, CBTRN02C, CBTRN03C with `"jcl_job"` (for example `CBTRN02C` with `jobs == [{"job": "POSTTRAN", "step": "STEP15"}]`; note that CBACT04C is a `batch_subroutine` by kind but is run by `INTCALC`, so it is an entry point); `CBTRN01C` with `"candidate"` / `"heuristic"`; `not_entry_points` has exactly one entry: `CSUTLDTC` with `reason == "called"` and `hard_callers == ["COACTUPC", "CORPT00C", "COTRN02C"]`; no entry has `also_called == true`; `summary.unresolved_dynamic_calls == 0` |

Unit tests: `python -m unittest discover -s graph/tests -t graph`.

---

## 11. Documentation

1. `graph/README.md` for the offline VM: purpose; inputs (steps 1–3 must have run; list the folders); the command; outputs table; how to read `graph_report.md` (each section in one or two lines, including what "shared" data stores, candidate entry programs, orphans and navigation cycles mean and what to do about them); how to view `.mmd` files (any Mermaid viewer, for example a Markdown preview that supports Mermaid, or paste into mermaid.live on a machine with internet); troubleshooting (missing facts folders, empty graph sections because a step was skipped).
2. `docs/GRAPH_SCHEMA.md`: node types with id format and attributes; edge types with strength, direction, access and detail keys (a table); `entry_points`, `unresolved`, `analysis` keys; one real example each from the AWS output for: a `TRANSACTION_RUNS` edge, a `PROGRAM_DATASET` edge, a `STEP_DATASET` edge and a data store entry; a section "How step 5 uses the graph": hard and navigation edges for clustering, data edges for ownership, utilities and system programs excluded, `role` for online/batch, entry points as module seeds, build edges (COPY, USES_MAP, SYMBOLIC_MAP, SQL_INCLUDE) and config edges (JOB_USES_PROC, STEP_CONTROL_CARD, CSD_DEFINES) for bundle contents.
3. In `docs/MODULARIZATION_PLAN.md`, at the top of `## Stage 3: Dependency graph`, add: `Detailed build plan: [STEP4_BUILD_PLAN.md](STEP4_BUILD_PLAN.md). Output schema: [GRAPH_SCHEMA.md](GRAPH_SCHEMA.md).`

---

## 12. Things not to do

- No module detection, clustering or conversion order (that is step 5).
- No LLM calls, no new dependencies, no networkx.
- Do not change the facts of steps 2 and 3; if they are wrong, report it.
- Do not add README parsing to the tool (README checks belong to the acceptance script only).
- Do not run anything on `CardDemo-Cobol-main` or CBSA.

---

## 13. Final report to the user

1. Files created and edited.
2. G1–G17 and unit tests: pass/fail, actual output for failures.
3. Numbers from the AWS run: nodes and edges by type, entry points, shared data stores (full list), batch submitters, orphans, cycles, missing and unused lists, run time.
4. Documentation differences found (README vs graph: at least CLOSEFIL/OPENFIL program, CBTRNLDJ/CBTRNRPJ not in repo).
5. Every place where this plan was unclear and what you chose.
6. The commands the user runs on the other two repos (`build_graph.py --out analysis_out/carddemo-main` and `--out analysis_out/cbsa`, after steps 1–3) and what to check first in each `graph_report.md` (missing programs, unresolved items, data stores, orphans).
