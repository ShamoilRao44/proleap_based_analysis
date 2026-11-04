# Step 4b build plan: state dependency analysis, main entry points and activity flow

This document is a complete build instruction. Follow it exactly, in order. Every design decision has already been made. When something is not specified, choose the simplest option that satisfies the text and list it in the final report (section 13). If a test expectation contradicts the algorithm text, follow the algorithm text and report the difference.

## Why this step exists

Step 4 (the graph) knows which program can start which other program. It cannot tell **which program must run first**, because CICS screens link to each other in loops (sign-on → menu → screen → menu → sign-on) and every transaction can be typed directly. The place of a program in a flow is fixed by what it **needs to be true before it runs**. This step extracts that from the code that was already analysed:

1. **Shared state:** the COMMAREA record that programs pass to each other. Which program creates each field (producer), which programs need it (consumer).
2. **First-entry behaviour:** what a program does when it is started with an empty COMMAREA (`EIBCALEN = 0`): shows its own first screen, hands off to another program, or resets its own state and continues.
3. **From these:** a prerequisite relation (A must run before B), the true start of each process (the **main entry point**), a level for every program, and the direction (forward / back) of every navigation edge.
4. **Batch:** the same idea for jobs: a job that defines a dataset comes before the jobs that use it.

Nothing in this step may contain a program name, a field name or a paragraph name of any particular project (no `COSGN00C`, no `CDEMO-...`). All rules work from the structure of the facts.

---

## 0. Rules for the implementer

1. **Test only on the AWS repo** (`analysis_out/aws-carddemo`). Never run any tool from this step on `CardDemo-Cobol-main` or CBSA, and do not open their files. The user tests those manually.
2. **Do not modify** anything outside the new folder `flow/` and the docs named in section 11. In particular do not change the facts of steps 2 and 3 or `graph/`.
3. **Python:** standard library only, Python 3.8. No type hints with generics (`list[str]`), no `match`, no walrus operator, no third-party packages.
4. JSON: `json.dump(obj, f, indent=1, ensure_ascii=False)`, UTF-8, `newline="\n"`. Names in upper case. Lists in the output files are sorted as stated; running the tool twice must give identical files (except `generated`).
5. Never commit.
6. **Prerequisites** (stop and report if missing): `analysis_out/aws-carddemo/graph/graph.json` (step 4), `facts/cobol/*.json` (26 files) and `facts/raw/*.raw.json` (26 files). Do not re-run earlier steps unless a file is missing.
7. **Stop conditions:** stop and report if a check in section 10 fails and the cause is not in code you wrote.
8. Write temporary scripts only to the scratchpad directory of your session.

---

## 1. What gets built

```
flow/
├── build_flow.py              CLI
├── README.md
├── flow_lib/
│   ├── __init__.py            (empty)
│   ├── common.py
│   ├── loaders.py
│   ├── state.py               state records, cells, effects, producers and consumers
│   ├── entry.py               first-entry analysis
│   ├── process.py             prerequisites, classification, roots, levels, edge direction
│   ├── batch_order.py         job order from datasets
│   ├── diagrams.py
│   └── report.py
└── tests/
    ├── __init__.py
    ├── helpers.py
    ├── test_state.py
    ├── test_entry.py
    ├── test_process.py
    └── test_batch_order.py
docs/FLOW_SCHEMA.md
```

CLI: `python3 flow/build_flow.py --out <analysis_dir>` → prints `[flow] N online programs, R roots, J jobs` and exits 0.

Output in `<out>/flow/`:

| File | Content |
|---|---|
| `main_entry_points.json` | **The answer to "where does the process start"**: online roots and batch starts, each with evidence (schema `main-entry-points/1`) |
| `process_flow.json` | all programs with classification, prerequisites, levels, navigation edges with direction; the job order (schema `process-flow/1`) |
| `state_dependencies.json` | state records, cells, producers, consumers, per-program requirements (schema `state-deps/1`) |
| `flow_report.md` | readable report |
| `diagrams/online_process.mmd`, `diagrams/batch_order.mmd` | Mermaid diagrams |

`graph/entry_points.json` (step 4) keeps its meaning "programs that can be started" (a trigger exists). `flow/main_entry_points.json` means "programs where a process begins".

---

## 2. `loaders.py`

`load(out_dir)` returns:

```python
{"root": <graph codebase_root>,
 "final": {name: facts},         # facts/cobol/*.json, files starting with "_" skipped, keyed by facts "name"
 "raw":   {name: raw facts},     # facts/raw/*.raw.json, keyed by raw "name" (statements, paragraphs)
 "graph": <parsed graph/graph.json>,
 "online": [names with final kind == "cics_online", sorted],
 "warnings": []}
```
A program that has final facts but no raw facts gets the warning `no raw facts for NAME: statement-level analysis skipped`.

Keys used (nothing else may be relied on):
- **final:** `name`, `kind`, `path`, `files[]` (`index`, `name`, `path`), `data_items[]` (`id`, `level`, `name`, `parent`, `record`, `children`, `conditions`, `offset`, `size`, `total_size`, `is_group`, `values` (entries with `kind`, `value`), `file_index`, `loc`), `transfers[]` (`kind`, `stmt_id`, `target`, `resolved_targets`, `commarea`, `paragraph`, `loc`), `decisions[]` (`stmt_id`, `loc`).
- **raw:** `paragraphs[]` (`name`, `declaratives`), `statements[]` (`id`, `type`, `paragraph`, `parent`, `branch`, `pline`, `text`, `reads`, `writes`, and per type: `condition` (if), `subjects` and `whens` (evaluate), `until` (perform), `target`, `thru`, `inline` (perform), `from_literal`, `from_var`, `to`, `corresponding` (move), `exec_text` (execCics)).
- **graph:** `nodes[]`, `edges[]` (`type`, `source`, `target`, `access`, `details`), `analysis.data_stores`.

Statement ids of raw and `stmt_id` of final transfers and decisions are the same numbers.

---

## 3. `state.py`

`build_state(data)` returns the body of `state_dependencies.json` (3.7) and keeps lookup tables for the later modules.

### 3.1 State records

For every online program P: `names` = the set of non-null `commarea` values of its transfers of kind `XCTL`, `LINK`, `RETURN_TRANSID`, `START_TRANSID`. For each name N: the record item of P is the first `data_items` entry with `level == 1` and `name == N`. If there is none: warning `state record N not defined in P` and N is skipped for P. The state record is identified across programs by its **name** N.

### 3.2 Leaves and name tables

For program P and record item R:
- **Leaf:** an item with `record == R.id`, no children, `level` not in (66, 88), `total_size > 0` and name not null and not `FILLER`. Interval of a leaf: `[offset, offset + total_size)`.
- `leaf_by_name`: leaf name → leaf. `cond_to_leaf`: for every leaf, each name in `conditions` (88-level names) → that leaf's name. `group_leaves`: for every non-leaf item with `record == R.id` and level not in (66, 88): item name → list of the leaf names below it (recursively via `children`); also `R.name` → all leaves.
- When P has several records, the tables are merged; a name that already exists keeps its first entry.

### 3.3 Cells (storage identity)

The COMMAREA is a block of memory that each program labels differently. Identity is therefore the **byte range**, not the name.

For every state record name N: group the leaves of all programs by their **exact byte range** `(offset, total_size)`. Each group is a **cell**: `id = "N@<offset>+<size>"`. Leaves with the same range but different names (the same storage labelled differently by two programs) are in the same cell. Ranges are **not** merged when they only overlap: programs reuse the tail of the COMMAREA for unrelated purposes, and merging overlapping ranges would chain such unrelated layouts into one huge cell. Cell attributes:
- `names`: sorted unique leaf names;
- `shared`: true if at least one of its leaves is defined in a copybook (`file_index != 0`), else false (a **local** cell: defined only inside programs);
- `defined_in`: `[{"program", "name", "source"}]` sorted, where `source` is the copybook name (`files[file_index].name`) or `"program"`.

Warnings: `alias_mismatch NAME` if the same leaf name has a different `(offset, size)` in two programs; `partial_overlap A<->B` (cell ids) when a cell from one program overlaps a cell of another program without being equal (at most 50 such warnings, then one line `n more partial_overlap warnings`).

### 3.4 Effects of statements

For every program with raw facts and every statement `s` of type other than `execCics`, `goback`, `stop`, `exit`, `goTo`, `open`, `close`:

1. **Bulk copy exemption.** If `s.type == "move"` and either some name in `s.to` is a group (a key of `group_leaves`) or `s.from_var` is a group: the statement is a **copy** (state moved as a block, for example `MOVE DFHCOMMAREA TO the record`). Record its id in the program's `copies` and produce no reads or writes.
2. **Reads.** `names = s.reads` plus, for statements of type `if` (text `condition`), `evaluate` (all `subjects` and all `whens[].conditions`/`whens[].condition`) and `perform` (text `until`): every token of the upper-cased text matching `[A-Z0-9][A-Z0-9-]*` that is a key of `cond_to_leaf` (step 2 does not list bare 88-level names as reads). Each name resolves to cells: a leaf name → its cell; an 88-level name → the cell of its parent leaf; a group name → the cells of all its leaves. Names that resolve to nothing are ignored.
3. **Writes.** The names in `s.writes` resolve the same way. The **kind** of the write:
   - `reset`: `s.type == "initialize"`;
   - `constant`: `s.type == "set"`, or `s.type == "move"` with `from_literal` not null;
   - `copy`: `s.type == "move"` and `from_var` is a leaf name of the record (state to state);
   - `origin`: everything else (a value from outside the state: screen input, file field, computation).
4. Each effect keeps evidence `{"stmt": id, "paragraph", "text": first 80 characters of s.text}`, at most 3 per (program, cell, kind) or (program, cell) for reads.

### 3.5 Aggregation

Per cell: `origin_producers`, `constant_writers`, `reset_by`, `copy_writers`, `consumers` (all sorted program names), and `single_origin` = exactly one origin producer.

Per program P:
- `provides(P)` = cells with an `origin` write by P.
- `requires(P)` = cells that P reads and does **not** write with any kind.

### 3.6 Requirement resolution

`direct_senders(C)` = programs X ≠ C with a graph edge of type `XCTL` or `LINK` from `program:X` to `program:C`, or `RETURN_TRANSID` / `START_TRANSID` from `program:X` to a transaction T and `TRANSACTION_RUNS` from T to `program:C`.

For each cell `c` in `requires(C)`:
- if `c.shared`: `producers` = `origin_producers` minus C (any program: shared fields travel along the whole chain of transfers);
- else (local cell): `producers` = programs in `origin_producers` that are also in `direct_senders(C)` (a local field is a hand-over to the next screen, so only the sender can supply it).
- `status` = `produced` if `producers` is not empty, else `unproduced` (nobody in the codebase supplies it, or it comes from outside).

Per program output: `requirements = [{"cell", "kind": "shared"|"local", "producers", "status"}]` sorted by cell id.

### 3.7 `state_dependencies.json`

```json
{"schema": "state-deps/1", "generated": "...", "codebase_root": "...",
 "records": [{"name": "...", "programs": [...], "size": <max total_size over programs>}],
 "cells": [{"id", "record", "offset", "size", "names", "shared", "defined_in",
            "origin_producers", "constant_writers", "reset_by", "copy_writers", "consumers", "single_origin"}],
 "programs": {"NAME": {"records": [...], "requires": [cell ids], "provides": [cell ids],
                       "requirements": [...], "reads": {cell: [evidence]}, "writes": {cell: {kind: [evidence]}},
                       "copies": [stmt ids]}},
 "warnings": [...]}
```
Records and cells sorted by name / id; `programs` keys sorted.

---

## 4. `entry.py`

`first_entry(final, raw, known_programs)` returns, for one online program:

```json
{"found": true, "paragraph": "MAIN-PARA", "statement_id": 3, "loc": [0, 80], "condition": "EIBCALEN = 0",
 "outcome": "handoff", "handoff_targets": ["SIGNON"], "path_resolved": true,
 "events": ["assign", "assign", "transfer"], "expected_callers": []}
```
or `{"found": false, "outcome": "none"}` (also when there are no raw facts: `outcome: "unknown"`).

### 4.1 Finding the first-entry test

```python
FIRST = re.compile(r"\bEIBCALEN\b\s*(=|EQUAL(\s+TO)?|IS\s+EQUAL(\s+TO)?)\s*(0|ZERO|ZEROS|ZEROES)\b", re.I)
```
- **Main paragraph** = first paragraph of the raw `paragraphs` whose `declaratives` is false.
- Candidates: statements of `type == "if"` whose `condition` matches `FIRST`, with `paragraph == main`; if there is none, the same kind of statement in the paragraphs targeted by the non-inline `perform` statements of the main paragraph (direct, one level).
- The test is the candidate with the lowest `id`. No candidate: `found = false`, `outcome = "none"`.
- `loc` = `loc` of the final `decisions` entry with the same `stmt_id` (or null).

### 4.2 Walking the "then" branch

- `then_ids` = ids of the statements whose `parent` is the test statement and `branch == "then"`, plus all their descendants (by `parent`), sorted ascending.
- Walk the statements of `then_ids` in id order and produce **events**:
  - `move` with `from_literal` not null → `("assign", variable, literal)` for each name in `to`; the literal has its quotes removed and is stripped and upper-cased;
  - `initialize` → `("init",)`;
  - `execCics` whose `exec_text` matches `\bSEND\s+(MAP|TEXT)\b` (case-insensitive) → `("send",)`;
  - `execCics` whose id is the `stmt_id` of a final transfer of kind `XCTL` or `LINK` → `("transfer", stmt_id)`;
  - `perform` that is not inline, with a `target`, at depth < 4, whose target paragraph has not been expanded yet in this walk: add the target to the visited set and walk **all statements of that paragraph** (any `parent`) in id order at that point (for `thru`, all paragraphs from `target` to `thru` in raw paragraph order). Depth counts nested expansions.
- `path_resolved` starts true.

### 4.3 Targets and outcome

Keep a dict `last` (variable → literal) updated by `assign` events in order. For each `transfer` event with final transfer `t`:
- if `t.target.var` is in `last` → the target is `last[var]`;
- else the targets are all `resolved_targets[].value` of `t`, and `path_resolved` becomes false.

`handoff_targets` = sorted unique targets. `outcome`:
- `handoff` if any target differs from the program's own name;
- else `own_screen` if a `send` event exists;
- else `self_initialising` if an `init` event exists;
- else `other`.

`events` is the list of event names (first element of each event tuple).

### 4.4 Expected callers (soft evidence)

Tokenise the upper-cased test `condition` with `[A-Z0-9][A-Z0-9-]*`. For every token that is the name of a non-88 item in `data_items` of the program and whose `values` contain an entry with `kind == "string"` and a `value` (stripped, upper-cased) that is a key of `known_programs` (all program names with final facts) and differs from the program's own name: that value is an **expected caller**. `expected_callers` = sorted unique values. (A program that compares "who called me" with a constant holding another program's name expects to be reached from it.)

---

## 5. `process.py`

`build_process(data, state, entries)` where `entries` is `{name: first_entry result}` for the online programs.

### 5.1 Prerequisites

For every online program B, **hard** prerequisites (A must run before B):
- `handoff`: for each target A in `entries[B].handoff_targets` with A ≠ B and A an online program with final facts: `{"program": A, "kind": "handoff", "evidence": "<B> hands off to <A> when started without a COMMAREA (<paragraph> line <n>)"}`;
- `state`: for each requirement of B with `status == "produced"` and each producer A: `{"program": A, "kind": "state", "evidence": "<B> needs <cell names> that <A> sets (shared|local)"}`.

**Soft** prerequisites: `expected_caller`: for each A in `entries[B].expected_callers` that is an online program: `{"program": A, "kind": "expected_caller", "evidence": "<B> checks it was called from <A>"}`.

Duplicates (same program and kind) are merged, evidence of the first kept. Prerequisites are sorted by `(program, kind)`.

### 5.2 Classification

First rule that applies:
1. `needs_prior`: B has at least one hard prerequisite.
2. `expects_caller`: B has soft prerequisites.
3. `starter`: `entries[B].outcome == "own_screen"`.
4. `unclear`: everything else (`self_initialising`, `other`, `none`, `unknown`).

### 5.3 Roots and certainty

A **root** is a program with classification `starter` and at least one transaction (the graph has `TRANSACTION_RUNS` from a transaction to it). `dependents(A)` = online programs that list A as a hard prerequisite. Certainty:
- `certain`: root with at least one dependent;
- `probable`: root without dependents.

Programs classified `unclear` are listed with a `reason`: `"starts with its own state reset, no evidence of a predecessor"` (`self_initialising`), `"no first-entry test found"` (`none`/`unknown`), `"first-entry branch does neither hand off nor show a screen"` (`other`).

### 5.4 Levels

Prerequisite graph: an edge A → B for every hard or soft prerequisite of B. Tarjan SCC (iterative, no recursion) over the online programs that have at least one incident edge. Level of an SCC = 0 if it has no predecessor SCC, else 1 + maximum level of its predecessor SCCs. Every program gets `level_source = "state"` and the level of its SCC; `cyclic_prerequisites` = true for SCCs with more than one program.

Programs with no incident prerequisite edge: roots get level 0 (`level_source = "state"`); every other program gets the shortest navigation distance from any root (edges: `XCTL`, `LINK` and the composite `RETURN_TRANSID`/`START_TRANSID` via a transaction, forward direction only) with `level_source = "navigation"`; if no root reaches it the level is null.

### 5.5 Navigation edges

For every graph edge between online programs of type `XCTL`, `LINK`, or the composite via a transaction (source program → transaction by `RETURN_TRANSID`/`START_TRANSID`, then `TRANSACTION_RUNS` to the target program), excluding self edges: `direction` = `forward` if `level(target) > level(source)`, `back` if `<`, `lateral` if equal, `unknown` if either level is null. Record `{"source", "target", "type", "direction", "how": details[0].how, "guards": details[0].guards}`; sorted by `(source, target, type)`.

### 5.6 `process_flow.json` (online part)

```json
{"schema": "process-flow/1", "generated": "...", "codebase_root": "...",
 "online": {
   "roots": [names], "programs": {NAME: {"transactions", "first_entry": {...}, "requires": [...], "provides": [...],
              "prerequisites": [...], "classification", "certainty": "certain|probable|null", "level", "level_source",
              "cyclic_prerequisites", "dependents": [...]}},
   "levels": [{"level": 0, "programs": [...]}, ...],
   "navigation_edges": [...], "unclear": [{"name", "reason"}]},
 "batch": {...}}
```
`levels` lists levels in ascending order; programs with a null level are listed under `{"level": null, ...}` last.

---

## 6. `batch_order.py`

`build_batch(data)` uses `graph.json` only.

- **Jobs:** nodes of type `job` that have at least one outgoing `JOB_STEP` edge. A step belongs to the job in its node attr `job`.
- **Definer:** a job with an `IDCAMS_DEFINE` edge from one of its steps to the dataset.
- **User:** a job with a step that has a `STEP_DATASET` or `IDCAMS_DELETE` edge (any access) to the dataset, and that is not a definer of that dataset. (Jobs that write a new generation of a GDG through a DD are users; only the job that defines the GDG base is its definer.)
- Temporary datasets (`attrs.temp`) and datasets with unresolved symbols are ignored.

For each dataset D:
- exactly one definer job A → order edge A → B for every user job B ≠ A, with `datasets` listing D (edges for the same pair are merged, `datasets` sorted);
- two or more definers → D goes to `multi_definer` as `{"dataset", "definers": [...], "users": [...]}`; no order edge;
- no definer and at least one user → D goes to `external_inputs` as `{"dataset", "users": [...]}` (loaded or provided from outside).

**Job levels:** Tarjan SCC over the order edges, then levels exactly as in 5.4 (0 for jobs without predecessors). Each job record: `{"job", "level", "predecessors": [{"job", "datasets"}], "successors": [...], "defines": [datasets it defines, sorted], "runs_programs": [program names of its STEP_RUNS targets that are not utility nodes (node attr utility false) and not system, sorted]}`. Jobs sorted by `(level, job)`.

**Online prerequisites:** for every dataset used by online programs (`analysis.data_stores` entries with non-empty `online_programs`): one definer → `{"job": A, "datasets": [D...]}` in `required_jobs` (merged per job); two or more definers → `{"jobs": [...], "datasets": [D]}` in `one_of`; no definer → `external` list of datasets.

`process_flow.json` `batch` part:
```json
{"jobs": [...], "order_edges": [{"from", "to", "datasets"}], "multi_definer": [...],
 "external_inputs": [...], "online_prerequisites": {"required_jobs": [...], "one_of": [...], "external": [...]}}
```

---

## 7. `main_entry_points.json`

```json
{"schema": "main-entry-points/1", "generated": "...", "codebase_root": "...",
 "rule": "A main entry point is a program that works with no earlier program (it shows its own first screen when started without a COMMAREA and needs no state set by another program) and that other programs depend on. Programs that hand off to another program when started without a COMMAREA, or need state another program sets, are not entry points. Navigation links between screens (XCTL) do not make a program an entry point.",
 "online": {"roots": [{"name", "transactions", "certainty", "dependents", "evidence": [strings]}],
            "unclear": [{"name", "reason"}]},
 "batch": {"starts": [{"job", "runs_programs", "defines"}], "note": "Jobs with no predecessor by dataset definition. The order between independent jobs is not in the code (scheduler or run book)."}}
```
`evidence` of a root (in this order): `"first entry (<paragraph> line <n>): shows its own screen"`, `"<k> programs hand off to it when started without a COMMAREA: <names>"`, `"no state required from other programs"` (when `requires` is empty), and for each cell it is the only origin producer of: `"only program that sets <cell names>"`. `batch.starts` = job records of level 0 that have a non-empty `defines`. If no program qualifies as a root, `roots` is empty and the report says so.

---

## 8. `diagrams.py` and `report.py`

**Diagrams** (`diagrams/*.mmd`, first line `flowchart TD`, at most 300 edges, final line `%% truncated: N more edges` if cut; node ids = original name with every character outside `[A-Za-z0-9_]` replaced by `_`, labels in double quotes with `"` replaced by `'`):
- `online_process.mmd`: one `subgraph L<n>["Level <n>"]` per level (programs with null level in `subgraph LX["Level unknown"]`), program nodes labelled with the name; roots labelled `NAME (entry)`; edges: `forward` as `-->`, `lateral` as `---`, `back` as `-.->|back|`; `unknown` edges omitted.
- `batch_order.mmd`: one subgraph per job level with job nodes; edges `-->|<first dataset, last two dot-parts>|` for each order edge.

**`flow_report.md`** sections in this order (write `none` for empty lists):
1. `# Activity flow: <codebase_root>`, generation time, counts.
2. **Main entry points:** online roots with their evidence; unclear programs; batch starts.
3. **How the classification works:** four lines explaining `starter`, `needs_prior`, `expects_caller`, `unclear` and what `certain` means.
4. **Online programs:** table `| Program | Classification | Level | Prerequisites | First entry |` (prerequisites as `NAME (kind)`).
5. **Levels:** one line per level.
6. **Back and lateral navigation:** counts, then the back edges grouped by target.
7. **State fields:** table of cells with an `origin` producer: `| Cell | Names | Shared | Origin producers | Consumers |` (consumers capped at 8 names, then `+n`).
8. **Unproduced requirements:** program, cell, kind.
9. **Batch job order:** jobs by level with predecessors; `multi_definer`; `external_inputs`; online prerequisite jobs.
10. **Warnings.**

---

## 9. Unit tests (`flow/tests/`)

`helpers.py` provides builders (all other keys absent):

```python
def item(id_, name, level, offset, size, record, parent=None, children=(), conditions=(), file_index=0, values=None)
def final(name, items, transfers=(), decisions=(), kind="cics_online")      # files = [{"index":0,"path":name+".cbl","name":name},{"index":1,"path":"COMM.cpy","name":"COMM"}]
def xfer(stmt_id, kind, values, var=None, commarea="COMM")                   # target {"var":var,"text":var} if var else {"literal":values[0]}
def stmt(id_, type_, paragraph, parent=None, branch=None, **kw)             # reads=[], writes=[] by default
def rawf(name, paragraphs, statements)                                       # paragraphs: names; all non-declaratives
def graph(transactions=None, edges=())                                       # transactions {"T1": "PROG"}; edges (type, "A", "B")
```
Item sets for the mini application "SHOP" (record `COMM`, level 1, id 1, size 48, copybook-defined leaves `file_index=1`):
`COMM` (1, offset 0, size 48) with children `USER-ID` (offset 0, size 8), `USER-TYPE` (offset 8, size 1, conditions `["IS-ADMIN"]`), `PAD` (offset 9, size 31) and a program-local leaf (file_index 0) at offset 40 size 8: `LIST-SEL` in LIST, `DET-SEL` in DETAIL.

Programs of SHOP (`final` + `rawf`; `known_programs` = all five names):
- **SIGN:** paragraph `MAIN`: id1 `if` condition `EIBCALEN = 0`; id2 `execCics` (parent 1, branch then) `exec_text` `EXEC CICS SEND MAP('M') MAPSET('S') END-EXEC`; id3 `move` (parent 1, branch else) `from_var UID-IN`, `to ["USER-ID"]`, `writes ["USER-ID"]`; id4 `move` (parent 1, branch else) `from_var UTYPE-IN`, `to ["USER-TYPE"]`, `writes ["USER-TYPE"]`.
- **MENU:** paragraph `MAIN`: id1 `if` condition `EIBCALEN = 0`; id2 `move` (parent 1, then) `from_literal "'SIGN'"`, `to ["TARGET"]`, `writes ["TARGET"]`; id3 `perform` (parent 1, then) `target "BACK"`; id4 `if` (parent 1, else) condition `IS-ADMIN`. Paragraph `BACK`: id5 `execCics` `exec_text` `EXEC CICS XCTL PROGRAM(TARGET) END-EXEC`. Transfer: `xfer(5, "XCTL", ["SIGN", "LIST"], var="TARGET")`.
- **LIST:** paragraph `MAIN`: id1 `move` `from_var ROW-IN`, `to ["LIST-SEL"]`, `writes ["LIST-SEL"]`; id2 `execCics` XCTL; transfer `xfer(2, "XCTL", ["DETAIL"])`.
- **DETAIL:** paragraph `MAIN`: id1 `move` `from_var DET-SEL`, `to ["WS-X"]`, `reads ["DET-SEL"]`, `writes ["WS-X"]`.
- **CARD:** has an extra item `LIT-MENU` (level 77, not in the record, `values [{"from": "'MENU'", "kind": "string", "value": "MENU"}]`); paragraph `MAIN`: id1 `if` condition `EIBCALEN = 0 OR FROM-PGM = LIT-MENU`; id2 `initialize` (parent 1, then); `writes ["USER-TYPE"]` on id2.
- Graph: transactions `T-SIGN → SIGN`, `T-MENU → MENU`, `T-LIST → LIST`, `T-CARD → CARD`; edges `("XCTL", "MENU", "SIGN")`, `("XCTL", "MENU", "LIST")`, `("XCTL", "LIST", "DETAIL")`, `("XCTL", "SIGN", "MENU")`.

`test_entry.py`
- SIGN → `outcome == "own_screen"`, `events == ["send"]`, `condition == "EIBCALEN = 0"`.
- MENU → `outcome == "handoff"`, `handoff_targets == ["SIGN"]` (the assignment before the perform wins over the candidates `SIGN`, `LIST`), `path_resolved` true, `events == ["assign", "transfer"]`.
- Same MENU but without the `MOVE 'SIGN'` statement → `handoff_targets == ["LIST", "SIGN"]`, `path_resolved` false.
- CARD → `outcome == "self_initialising"`, `expected_callers == ["MENU"]`.
- A program whose test is `EIBCALEN IS EQUAL TO 0` is found; a program without any `EIBCALEN` condition → `found` false, `outcome == "none"`.
- Perform expansion stops at depth 4 and on a recursive paragraph without hanging (paragraph A performs B, B performs A).

`test_state.py`
- Cells: `COMM@0+8` (USER-ID) and `COMM@8+1` have `shared` true; `COMM@40+8` has `names == ["DET-SEL", "LIST-SEL"]` and `shared` false (same byte range, different names, one cell).
- A leaf `(offset 40, size 4)` in a third program creates its own cell `COMM@40+4` (no merging) and the warning `partial_overlap`.
- SIGN is the only `origin` producer of `COMM@0+8` and of `COMM@8+1`; CARD is in `reset_by` of `COMM@8+1` (INITIALIZE counts as `reset`, not `origin`).
- MENU `requires` contains `COMM@8+1` although `IS-ADMIN` is only in the condition text (the 88-level name is recovered); `requirements` for it: `kind "shared"`, `producers ["SIGN"]`, `status "produced"`.
- DETAIL requires `COMM@40+8`; with the graph edge `LIST → DETAIL` present: `producers ["LIST"]`; with that edge removed: `status "unproduced"`.
- A `move` whose `from_var` is the group `COMM` is a copy: it appears in `copies` and creates no read or write.
- `alias_mismatch` warning when a name has different offsets in two programs.

`test_process.py` (SHOP, edge `LIST → DETAIL` present)
- SIGN: `starter`, `certain`, `dependents == ["MENU"]`; roots `== ["SIGN"]`. MENU: `needs_prior` (handoff SIGN and state SIGN merged into two prerequisites of different kinds). DETAIL: `needs_prior` (state, LIST). CARD: `expects_caller` (soft, MENU). LIST: `unclear` with reason `"no first-entry test found"`.
- Levels: SIGN 0; MENU 1; CARD 2; LIST 0 (`level_source "state"`, source of a prerequisite edge); DETAIL 1.
- Navigation edge directions: `SIGN → MENU` forward; `MENU → SIGN` back; `MENU → LIST`: `lateral`? MENU level 1, LIST level 0 → `back`; `LIST → DETAIL` forward.
- Cycle in prerequisites (two programs requiring each other's state) → one SCC, same level, `cyclic_prerequisites` true, no hang.
- No program qualifies as a root → `roots == []`, no exception.

`test_batch_order.py` (small graph built with node/edge dicts like `graph.json`)
- Job A has `IDCAMS_DEFINE` of D1; jobs B and C read D1 → order edges A→B, A→C, levels A 0, B 1, C 1.
- D2 defined by A and by E → `multi_definer`, no edge between them for D2.
- D3 read by B and defined by nobody → `external_inputs`.
- A temporary dataset is ignored.
- Online program with a CICS file on D1 → `online_prerequisites.required_jobs == [{"job": "A", "datasets": ["D1"]}]`; on D2 → `one_of == [{"jobs": ["A", "E"], "datasets": ["D2"]}]`.
- Cycle between two jobs does not hang (same level).

---

## 10. Acceptance checks on AWS (`analysis_out/aws-carddemo`)

Run `python flow/build_flow.py --out analysis_out/aws-carddemo`; load the JSON files in a scratch script.

| # | Check | Pass criteria |
|---|---|---|
| F1 | Run | exit 0; the 3 JSON files, `flow_report.md` and both `.mmd` files exist; `online` has 17 programs |
| F2 | First entry | `outcome == "own_screen"` for `COSGN00C` only; `handoff` with `handoff_targets == ["COSGN00C"]` and `path_resolved` true for exactly `COADM01C`, `COBIL00C`, `COMEN01C`, `CORPT00C`, `COTRN00C`, `COTRN01C`, `COTRN02C`, `COUSR00C`, `COUSR01C`, `COUSR02C`, `COUSR03C`; `self_initialising` for exactly `COACTUPC`, `COACTVWC`, `COCRDLIC`, `COCRDSLC`, `COCRDUPC` |
| F3 | Expected callers | `expected_callers == ["COMEN01C"]` for `COACTUPC`, `COACTVWC`, `COCRDSLC`, `COCRDUPC`; `[]` for `COCRDLIC` |
| F4 | Shared state | the cells of `CARDDEMO-COMMAREA` containing `CDEMO-USER-ID` and `CDEMO-USER-TYPE` are `shared` with `origin_producers == ["COSGN00C"]`; `COMEN01C.requires` contains the `CDEMO-USER-TYPE` cell and its requirement is `produced` by `["COSGN00C"]`; `COMEN01C` is in the `consumers` of that cell (the 88-level `CDEMO-USRTYP-USER` read is recovered from the condition) |
| F5 | Local channels | `COTRN01C` has a `local` requirement on the cell containing `CDEMO-CT01-TRN-SELECTED` (offset 202, size 16) produced by `["COTRN00C"]`; `COUSR02C` and `COUSR03C` have a `local` requirement on the cell containing `CDEMO-CU02-USR-SELECTED` / `CDEMO-CU03-USR-SELECTED` (offset 186, size 8) produced by `["COUSR00C"]`; `COBIL00C` and `COTRN02C` each have an `unproduced` local requirement; the cell `CARDDEMO-COMMAREA@202+16` exists, is not shared, and its `names` are exactly `CDEMO-CB00-TRN-SELECTED`, `CDEMO-CT00-TRN-SELECTED`, `CDEMO-CT01-TRN-SELECTED`, `CDEMO-CT02-TRN-SELECTED`; the cell `CARDDEMO-COMMAREA@186+8` exists and its `names` are exactly `CDEMO-CU00-USR-SELECTED`, `CDEMO-CU02-USR-SELECTED`, `CDEMO-CU03-USR-SELECTED` |
| F6 | Classification | `starter`: `COSGN00C` only; `needs_prior`: exactly the 11 hand-off programs of F2; `expects_caller`: `COACTUPC`, `COACTVWC`, `COCRDSLC`, `COCRDUPC`; `unclear`: `COCRDLIC` (reason `starts with its own state reset, no evidence of a predecessor`) |
| F7 | Roots | `roots == ["COSGN00C"]`, certainty `certain`, `dependents` = the 11 hand-off programs; `main_entry_points.online.roots` has exactly one entry with at least 3 evidence strings; `unclear == [{"name": "COCRDLIC", ...}]` |
| F8 | Levels | `COSGN00C` 0; level 1: `COADM01C`, `COBIL00C`, `COMEN01C`, `CORPT00C`, `COTRN00C`, `COTRN02C`, `COUSR00C`, `COUSR01C`; level 2: `COTRN01C`, `COUSR02C`, `COUSR03C`, `COACTUPC`, `COACTVWC`, `COCRDSLC`, `COCRDUPC`; `COCRDLIC` has `level_source == "navigation"` and a non-null level |
| F9 | Directions | every `XCTL` edge whose target is `COSGN00C` and whose source is not `COCRDLIC` has `direction == "back"`; `COSGN00C → COMEN01C` and `COSGN00C → COADM01C` are `forward`; `COMEN01C → COACTVWC` is `forward` and `COACTVWC → COMEN01C` is `back`; `COTRN00C → COTRN01C` is `forward` |
| F10 | Batch order edges | `order_edges` contain (from → to): ACCTFILE → INTCALC, POSTTRAN, READACCT; CARDFILE → READCARD; CUSTFILE → READCUST; XREFFILE → INTCALC, POSTTRAN, READXREF, TRANREPT; TCATBALF → INTCALC, POSTTRAN, PRTCATBL; DISCGRP → INTCALC; TRANCATG → TRANREPT; TRANTYPE → TRANREPT; DEFGDGB → COMBTRAN, INTCALC, PRTCATBL, TRANBKP, TRANREPT; DALYREJS → POSTTRAN; no edge lists dataset `AWS.M2.CARDDEMO.TRANSACT.VSAM.KSDS` |
| F11 | Multi-definer and externals | `multi_definer` contains `AWS.M2.CARDDEMO.TRANSACT.VSAM.KSDS` with definers `["TRANBKP", "TRANFILE"]`; `external_inputs` contain `AWS.M2.CARDDEMO.DALYTRAN.PS`, `AWS.M2.CARDDEMO.DATEPARM` and `AWS.M2.CARDDEMO.ACCTDATA.PS` |
| F12 | Job levels | level 1 jobs are exactly COMBTRAN, INTCALC, POSTTRAN, PRTCATBL, READACCT, READCARD, READCUST, READXREF, TRANBKP, TRANREPT; all other jobs are level 0; `batch.starts` includes ACCTFILE, CARDFILE, CUSTFILE, XREFFILE, TCATBALF, DEFGDGB and contains no level-1 job |
| F13 | Online prerequisites | `required_jobs` contain ACCTFILE (ACCTDATA.VSAM.KSDS), CARDFILE (CARDDATA.VSAM.KSDS), CUSTFILE (CUSTDATA.VSAM.KSDS), XREFFILE (CARDXREF.VSAM.KSDS), DUSRSECJ (USRSEC.VSAM.KSDS); `one_of` contains `{"jobs": ["TRANBKP", "TRANFILE"], "datasets": ["AWS.M2.CARDDEMO.TRANSACT.VSAM.KSDS"]}` |
| F14 | Determinism and isolation | two runs give identical JSON files apart from `generated`; the files in `graph/`, `facts/` and `inventory.json` are unchanged (compare hashes before and after) |
| F15 | Diagrams | each `.mmd` starts with `flowchart TD`; node ids match `^[A-Za-z0-9_]+$` |

Unit tests: `python -m unittest discover -s flow/tests -t flow`.

---

## 11. Documentation

1. `flow/README.md` for the offline VM: purpose and the idea in plain words (the web-page analogy: login before dashboard); inputs (steps 1–4 must have run, with `facts/raw`); the command; outputs table; how to read `main_entry_points.json` and `flow_report.md` (what `starter`, `needs_prior`, `expects_caller`, `unclear`, `certain`, `probable` mean and what to do with `unclear`); limits (below); troubleshooting (no raw facts: re-run step 2; no roots: the codebase has no program that starts without a prior one, check `unclear`).
2. `docs/FLOW_SCHEMA.md`: the schemas of sections 3.7, 5.6, 6 and 7 with one real example each from the AWS output: the `COSGN00C` root entry, a `needs_prior` program with its prerequisites, a state cell, a job record with predecessors.
3. In `docs/MODULARIZATION_PLAN.md`, under `## Stage 4: Module detection, bundles and conversion order` add: `Input from the activity flow: [STEP4B_BUILD_PLAN.md](STEP4B_BUILD_PLAN.md), [FLOW_SCHEMA.md](FLOW_SCHEMA.md). Process roots (main_entry_points.json) are the module seeds; levels give the order within a process.`

Limits to state in the README:
- The first-entry test is recognised only as `EIBCALEN` compared to zero in the main paragraph (or one level below). Other conventions are reported as `unclear`.
- Programs without raw facts (text fallback) are not analysed.
- Programs that share no state and have no first-entry evidence cannot be placed; they are listed as `unclear`.
- A field read before it is written in the same program is not counted as required (conservative: fewer false dependencies).

---

## 12. Things not to do

- No project-specific names in the code or in the tests of the generic rules (the SHOP fixtures use made-up names).
- No module detection or conversion order (step 5).
- No LLM calls, no new dependencies.
- Do not change the earlier steps, even if a fact looks wrong; report it.
- Do not run anything on `CardDemo-Cobol-main` or CBSA.

---

## 13. Final report to the user

1. Files created and edited.
2. F1–F15 and unit tests: pass/fail, actual output for failures.
3. Numbers from the AWS run: first-entry outcomes, classification counts, roots with evidence, levels, shared cells with a single origin producer, unproduced requirements, back/forward/lateral edge counts, batch levels, multi-definer datasets, external inputs, run time.
4. Differences from the prototype expectations of this plan (if any), and anything in the AWS code that contradicts the idea (for example a program that starts standalone).
5. Every place where this plan was unclear and what you chose.
6. The commands for the other two repos (`build_flow.py --out analysis_out/carddemo-main` and `--out analysis_out/cbsa`, after steps 1–4) and what to look at first in each `flow_report.md` (roots, `unclear` list, programs without raw facts, unproduced requirements).
