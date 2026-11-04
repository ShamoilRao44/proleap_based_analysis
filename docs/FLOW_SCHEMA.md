# Flow schemas (step 4b)

Written by `flow/build_flow.py` into `<analysis_dir>/flow/`.

## `main_entry_points.json` (`main-entry-points/1`)

```json
{"schema": "main-entry-points/1", "generated": "...", "codebase_root": "...", "rule": "...",
 "online": {"roots": [{"name", "transactions", "certainty", "dependents", "evidence"}],
            "unclear": [{"name", "reason"}]},
 "batch": {"starts": [{"job", "runs_programs", "defines"}], "note": "..."}}
```

A root is an online program that works with no earlier program and that has a transaction. `certainty` is `certain` when other programs depend on it, `probable` otherwise. `batch.starts` are the jobs of level 0 that define datasets. Example (AWS CardDemo, shortened):

```json
{"name": "COSGN00C", "transactions": ["CC00"], "certainty": "certain",
 "dependents": ["COADM01C", "COBIL00C", "COMEN01C", "..."],
 "evidence": [
  "first entry (MAIN-PARA line 80): shows its own screen",
  "11 programs hand off to it when started without a COMMAREA: COADM01C, COBIL00C, COMEN01C, ...",
  "no state required from other programs",
  "only program that sets CDEMO-USER-ID",
  "only program that sets CDEMO-USER-TYPE"]}
```

## `process_flow.json` (`process-flow/1`)

`{"schema", "generated", "codebase_root", "online": {...}, "batch": {...}}`.

### `online`

- `roots`: names, sorted.
- `programs`: per program `{transactions, first_entry, requires, provides, prerequisites, classification, certainty, level, level_source, cyclic_prerequisites, dependents}`.
  - `first_entry`: `{found, paragraph, statement_id, loc, condition, outcome, handoff_targets, path_resolved, events, expected_callers}`. `outcome` is `own_screen`, `handoff`, `self_initialising`, `other`, `none` (no test found) or `unknown` (no raw facts). `handoff_targets` are the programs it hands off to when started without a COMMAREA; `path_resolved` is false if a variable target could not be narrowed down to one value on that path. `expected_callers` are programs whose name the first-entry condition compares against.
  - `requires` / `provides`: cell ids (see state dependencies).
  - `prerequisites`: `[{program, kind, evidence}]`, kind `handoff` or `state` (hard) or `expected_caller` (soft). A prerequisite means "that program has to run before this one".
  - `classification`: `starter`, `needs_prior`, `expects_caller`, `unclear`.
  - `level`: 0 for the start; `level_source` is `state` (from prerequisites) or `navigation` (shortest path from a root; weaker).
- `levels`: `[{level, programs}]`, ascending; programs without a level are last under `level: null`.
- `navigation_edges`: `[{source, target, type, direction, how, guards}]`. `type` is `XCTL`, `LINK`, `RETURN_TRANSID` or `START_TRANSID` (the last two are resolved to the program the transaction starts). `direction`: `forward` (target has a higher level), `back` (lower: a return to a menu or to sign-on), `lateral`, `unknown`.
- `unclear`: `[{name, reason}]`.

Example (AWS CardDemo, `COTRN01C`; first-entry details shortened):

```json
{"transactions": ["CT01"],
 "first_entry": {"outcome": "handoff", "handoff_targets": ["COSGN00C"], "path_resolved": true, "expected_callers": []},
 "requires": ["CARDDEMO-COMMAREA@202+16"],
 "prerequisites": [
  {"program": "COSGN00C", "kind": "handoff",
   "evidence": "COTRN01C hands off to COSGN00C when started without a COMMAREA (MAIN-PARA line 94)"},
  {"program": "COTRN00C", "kind": "state",
   "evidence": "COTRN01C needs CDEMO-CB00-TRN-SELECTED, CDEMO-CT00-TRN-SELECTED, CDEMO-CT01-TRN-SELECTED, CDEMO-CT02-TRN-SELECTED that COTRN00C sets (local)"}],
 "classification": "needs_prior", "certainty": null, "level": 2, "level_source": "state",
 "cyclic_prerequisites": false, "dependents": []}
```

### `batch`

- `jobs`: `[{job, level, predecessors: [{job, datasets}], successors, defines, runs_programs}]`, sorted by level and name. `predecessors` are jobs that define a dataset this job uses.
- `order_edges`: `[{from, to, datasets}]`.
- `multi_definer`: datasets defined by two or more jobs: `[{dataset, definers, users}]`. No order is derived for them.
- `external_inputs`: datasets that no job defines: `[{dataset, users}]`.
- `online_prerequisites`: `required_jobs` (`[{job, datasets}]`: the job that defines a dataset the online programs use), `one_of` (`[{jobs, datasets}]`: any one of these jobs defines it), `external` (datasets nobody defines).

Example (`POSTTRAN`):

```json
{"job": "POSTTRAN", "level": 1,
 "predecessors": [{"job": "ACCTFILE", "datasets": ["AWS.M2.CARDDEMO.ACCTDATA.VSAM.KSDS"]},
                  {"job": "DALYREJS", "datasets": ["AWS.M2.CARDDEMO.DALYREJS"]},
                  {"job": "TCATBALF", "datasets": ["AWS.M2.CARDDEMO.TCATBALF.VSAM.KSDS"]},
                  {"job": "XREFFILE", "datasets": ["AWS.M2.CARDDEMO.CARDXREF.VSAM.KSDS"]}],
 "successors": [], "defines": [], "runs_programs": ["CBTRN02C"]}
```

## `state_dependencies.json` (`state-deps/1`)

```json
{"schema": "state-deps/1", "generated": "...", "codebase_root": "...",
 "records": [{"name", "programs", "size"}],
 "cells": [{"id", "record", "offset", "size", "names", "shared", "defined_in",
            "origin_producers", "constant_writers", "reset_by", "copy_writers", "consumers", "single_origin"}],
 "programs": {"NAME": {"records", "requires", "provides", "requirements", "reads", "writes", "copies", "analysed"}},
 "warnings": []}
```

- A **state record** is a level-01 item that programs pass as `COMMAREA` in `XCTL`, `LINK`, `RETURN TRANSID` or `START`.
- A **cell** is a byte range `(offset, size)` of that record. Programs label the same bytes differently, so cells are matched by position, not by name. `shared` is true when at least one program defines the field in a copybook; a non-shared cell is a hand-over area defined inside the programs.
- Write kinds: `origin` (a value from outside the state: screen input, file field), `constant` (a literal or `SET ... TO TRUE`), `reset` (`INITIALIZE`), `copy` (state to state). Only `origin` writers count as producers.
- `requirements`: `[{cell, kind (shared | local), producers, status (produced | unproduced)}]`. A shared field can be set by any program earlier in the chain; a local field only by a program that transfers directly to the consumer.
- A move of a whole group (for example `MOVE DFHCOMMAREA TO the record`) is a block copy; its statement id is listed in `copies` and it is not a read or write.

Example (the cell of the user type, shortened):

```json
{"id": "CARDDEMO-COMMAREA@32+1", "record": "CARDDEMO-COMMAREA", "offset": 32, "size": 1,
 "names": ["CDEMO-USER-TYPE"], "shared": true,
 "defined_in": [{"program": "COACTUPC", "name": "CDEMO-USER-TYPE", "source": "COCOM01Y"}, "..."],
 "origin_producers": ["COSGN00C"], "constant_writers": ["COACTUPC", "COACTVWC", "..."],
 "reset_by": ["COACTUPC", "COACTVWC", "..."], "copy_writers": [],
 "consumers": ["COACTUPC", "COACTVWC", "COCRDLIC", "..."], "single_origin": true}
```

## How step 5 uses the flow

| Need | Flow data |
|---|---|
| Module seeds | `main_entry_points.json` online roots and batch starts |
| Which programs belong to one process | the programs reachable from a root over forward navigation edges, and their prerequisites |
| Order inside a process | `level` (lower first); `back` edges do not constrain the order |
| Order of batch jobs | `batch.jobs[].level` and `order_edges` |
| What must exist before the online system works | `batch.online_prerequisites` |
| Where the module boundary would cut shared state | `cells` with several producers or consumers across candidate modules |
