# Plan: splitting a large COBOL codebase into modules

Goal: take a mainframe codebase of up to about 14,000 files and produce:
- a dependency model of the whole system, as a consolidated IR in JSON;
- business rules extracted by an LLM;
- a recommended conversion order;
- documentation (PUD, TSD, flow diagrams);
- self-contained module bundles.

Constraints (target VM): offline Ubuntu; Python with pip, Java 17 with Maven through Nexus; local Qwen3 Coder Next with a **64k-token** context (Grok API for local testing, same OpenAI-compatible client, only URL, model and key change). No Claude on the VM, so every stage must be a plain command with a README.

Test repositories:

| Repo | Why it is useful |
|---|---|
| `aws-mainframe-modernization-carddemo` | Small CICS/VSAM/batch app, 26 programs |
| `CardDemo-Cobol-main` | Superset of the above plus 3 optional sub-apps (IMS/DB2/MQ authorization, DB2 transaction types, VSAM/MQ). The sub-apps are natural modules, so they serve as **ground truth** for module detection. Its README has an application inventory (transactions, programs, functions) to check against. |
| `cics-banking-sample-application-cbsa` | CICS/DB2, 31 programs, heavy `EXEC CICS LINK` (140), a shared abend handler LINKed 122 times, CSD in `etc/install/base/installjcl/BANK.csd`. A good test for "shared utility" handling. |

---

## Principles

1. **Facts before LLM.** Everything the parser and scanners can determine (who calls whom, which files, tables, maps and copybooks are used) is extracted deterministically. The LLM only explains business meaning, and its output must cite source lines that are checked against the facts.
2. **Every stage writes files and can be resumed.** Each stage reads the previous stage's output folder and writes its own. Results are cached by file hash, so a re-run on 14,000 files only redoes what changed.
3. **Degrade gracefully.** If ProLeap reports syntax errors on a file (as with CUCO003), a text-scanner fallback still extracts the dependencies, and the file is marked `parse_quality: partial | text_only`. One bad file never stops the pipeline.
4. **Content over extensions.** Files are classified by content, not by name. The test repos alone contain `.cbl`, `.CBL`, `.cpy`, `.CPY` and 47 files with no extension.
5. **Shared items are copied, not moved.** A copybook or utility program used by several modules is included in every bundle that needs it. The IR records it once, with a list of all its owners, so it is converted once.

---

## Pipeline overview

```
 codebase
    |
 [1] Inventory & classification ------------------------> inventory.json
    |
 [2] Per-file static analysis (no LLM)
    |    COBOL: ProLeap ASG + text fallback
    |    JCL/PROC, CSD, BMS, DDL/DCLGEN, IMS PSB/DBD -------> facts/<file>.json
    |
 [3] Dependency graph: nodes + typed edges, resolution,
    |    entry points --------------------------------------> graph.json, reports
    |
 [4] Module detection + bundles + conversion order -------> modules.json, bundles/
    |    (human review via overrides.yaml)
    |
 [5] Chunking within the 64k budget ----------------------> chunks/
    |
 [6] LLM business rule extraction (map-reduce, cached) ---> rules/<program>.json
    |
 [7] Consolidated IR ------------------------------------> ir/
    |
 [8] Documents: PUD, TSD, flow diagrams per module -------> docs/<module>/
```

Stages 1-4 use no LLM. They are useful on their own and can be checked against the ground truth before any LLM time is spent.

---

## Stage 1: Inventory and classification

**Input:** codebase root. **Output:** `inventory.json`.

Walk every file and classify it by content heuristics:

| Type | Signals |
|---|---|
| COBOL program | `IDENTIFICATION DIVISION` / `PROGRAM-ID` |
| Copybook | COBOL data or procedure lines without `PROGRAM-ID` |
| BMS mapset | `DFHMSD`, `DFHMDI`, `DFHMDF` |
| JCL | `//name JOB` |
| PROC | `//name PROC` without JOB |
| CSD | `DEFINE TRANSACTION / PROGRAM / FILE` |
| DB2 DDL | `CREATE TABLE / INDEX` |
| DCLGEN | `EXEC SQL DECLARE ... TABLE` plus a COBOL host structure |
| IMS | `DBD` / `PSB` macros |
| Assembler | `CSECT`, `DS`, `DC` |
| Control card, data, docs, Java, web, other | everything else, ignored for COBOL analysis |

Per file, record:
- path, type, confidence and SHA-256 hash;
- line count and detected source format (fixed / variable / free);
- logical name: the member name, upper case, without extension.

Also report names that collide (two files with the same member name).

## Stage 2: Per-file static analysis

**Output:** `facts/<type>/<NAME>.json`, one per file, with a versioned schema.

### 2a. COBOL programs (Java, extends `cobol-ast-runner`)

Batch mode: one JVM, a thread pool, a timeout per file, and one JSON per program. Extracted with the ProLeap ASG:

- **Identity:** program-id, source format, parse quality, syntax errors, LOC.
- **Structure:** sections and paragraphs with line ranges; the PERFORM graph (paragraph to paragraph); GO TO.
- **Data:** data items with level, PIC, USAGE, VALUE, REDEFINES, OCCURS and line; LINKAGE and COMMAREA layout; FD and `SELECT ... ASSIGN TO ddname`.
- **Copybooks:** COPY list, with where each copybook is expanded (data or procedure division).
- **Control transfer:**
  - `CALL 'X'` (static);
  - `CALL ws-var` (dynamic);
  - `EXEC CICS XCTL / LINK PROGRAM(...)`;
  - `START TRANSID`, `RETURN TRANSID`.
- **Resources:**
  - CICS `READ / WRITE / REWRITE / DELETE / STARTBR ... FILE(...)`;
  - `SEND / RECEIVE MAP / MAPSET`;
  - TS and TD queues;
  - `EXEC SQL` tables with their operation (SELECT, INSERT, UPDATE, DELETE, cursor);
  - `EXEC SQL INCLUDE`;
  - IMS DL/I calls;
  - MQ calls (`MQOPEN`, `MQPUT`, ...).
- **Dynamic target resolution** (important for CICS). Program names held in variables are resolved through:
  - `VALUE` clauses;
  - `MOVE 'LIT' TO var` and `MOVE CONSTANT TO var`;
  - VALUE tables in copybooks, for example the CardDemo menu table `COMEN02Y`, which drives `XCTL PROGRAM(CDEMO-MENU-OPT-PGMNAME(WS-OPTION))`.

  Anything that cannot be resolved is recorded as `unresolved` with its variable name. It is never dropped.
- **Text fallback.** The same dependency scanners also run on raw source. They are used when ProLeap fails or reports partial parsing, and the two results are compared.

### 2b. Other artefacts (Python)

| Artefact | Facts |
|---|---|
| JCL / PROC | jobs, steps, `EXEC PGM=` / `EXEC proc`, PROC expansion with symbolic substitution; DD name to DSN; DISP (read / write / new); utilities (IDCAMS, SORT, IEBGENER, DFHCSDUP) and their control cards |
| CSD | transaction to program; FILE to DSN; program and mapset definitions; groups |
| BMS | mapset, maps, fields (name, length, attributes) |
| DDL / DCLGEN | tables, columns, keys; DCLGEN to table |
| Copybooks | defined data names (used later to explain unresolved names), nested COPY, whether it holds data or procedure code |
| IMS PSB / DBD | databases and segments a program can access |

## Stage 3: Dependency graph

**Output:** `graph.json` (nodes and edges), plus `graph_report.md` and Mermaid diagrams.

**Node types:** `transaction`, `job`, `step`, `program`, `copybook`, `mapset`, `cics_file`, `ddname`, `dataset`, `db2_table`, `ims_db`, `mq_queue`, `ts_queue`, `td_queue`, `external` (referenced but not present in the codebase).

**Edge types**, each with a strength used later for ordering and clustering:

| Edge | Strength | Meaning |
|---|---|---|
| `CALL`, `LINK` | hard | Caller needs the callee to work, and control returns. |
| `XCTL`, `RETURN_TRANSID`, `START_TRANSID` | navigation | Control passes from one screen to the next. These often form cycles (screen to menu to screen). |
| `COPY` | build | Program cannot compile without the copybook. |
| `USES_MAP` | build | Program uses the BMS symbolic map. |
| `READS`, `WRITES`, `UPDATES` on file, dataset or table | data | Shared data, the main coupling between batch and online. |
| `TRANSACTION_RUNS`, `JOB_RUNS_STEP`, `STEP_RUNS_PROGRAM` | entry | How execution starts. |

**Resolution:**
- CICS `FILE(ACCTDAT)` resolves through the CSD to DSN `...ACCTDATA.VSAM.KSDS`.
- Batch `ASSIGN TO ACCTFILE` resolves through the JCL DD to the same DSN.

Online and batch programs therefore meet at the same dataset node. That is how hidden coupling between them is found.

**Entry points:**
- CSD transactions;
- JCL jobs;
- programs no other program calls (candidate entry points, flagged for review).

**Reports:**
- missing items: copybooks, programs, maps, unresolved dynamic calls;
- fan-in / fan-out tables;
- orphan programs (never called, no transaction or job);
- cycles.

## Stage 4: Module detection, bundles and conversion order

This is the core of the plan. Simply following every edge from an entry point does not work: in CardDemo the main menu XCTLs to almost every screen, so one closure would contain the whole application. The plan instead separates **what a module is** from **what a bundle contains**.

### 4a. Classify special programs before clustering

- **Utility:** high fan-in through `CALL` or `LINK` and low fan-out, for example the CBSA abend handler (LINKed 122 times) or the CardDemo date routine `CSUTLDTC`. These go to a `shared` module and are copied into each bundle that uses them.
- **Navigation hub:** high fan-out through `XCTL` to other entry-like programs, for example menus (`COMEN01C`, `COADM01C`, `BNKMENU`) and sign-on. Clustering does not traverse through hubs. Each hub forms its own small "shell" module.
- **Common copybooks:** used by more than N modules, or generic (for example `DFHAID`, `DFHBMSCA`, common work areas). These go to the shared library.

Thresholds are configurable, and every classification can be overridden in `overrides.yaml`.

### 4b. Cluster programs into modules

Build a weighted, undirected graph of programs, leaving out utilities and hubs:

| Relationship | Weight |
|---|---|
| CALL / LINK | 3 |
| XCTL between non-hub programs | 2 |
| Both write the same dataset or table | 2 |
| Read / write the same dataset or table | 1 |
| Share a non-common copybook | 0.5 |
| Same name prefix (for example `COACT*`, `COCRD*`, `BNK1*`) | 0.5, as a tie-breaker only |

Run community detection on this graph (Louvain, via `networkx`, installable with pip). Then apply `overrides.yaml`, which lets you pin a program to a module, merge or split modules, and rename them.

Batch jobs are attached to the module that owns most of the data their steps write.

### 4c. Data ownership

Each dataset or table is owned by the module that writes it most. Access from other modules is listed as that module's **interface**. A module with many foreign writes signals a poor boundary and is flagged in the report.

### 4d. Bundles (your requirement: shared items go into every bundle)

A bundle for module M contains:
- M's programs;
- the **transitive closure** of their `COPY`, `CALL`, `LINK` and `USES_MAP` dependencies. Shared copybooks and utilities are **copied** into every bundle that needs them;
- the JCL / PROC and control cards of M's jobs;
- CSD definitions for M's transactions, programs and files;
- DDL / DCLGEN for the tables M uses;
- `manifest.json`, which lists each item as `own` or `shared` (with all its owner modules), plus external dependencies such as XCTL to another module's screen or datasets owned elsewhere.

**Self-check:** run `cobol-ast-runner` on every program in the bundle, using only the bundle's own copybook folder. Zero missing copybooks is required, which proves the bundle is complete.

### 4e. Conversion order

- **Within a module:**
  - topological sort over hard edges (`CALL`, `LINK`, `COPY`), least-dependent first;
  - cycles (strongly connected components) are collapsed and converted as one unit;
  - navigation edges (`XCTL`) do not constrain order, because screen-to-menu cycles are normal in CICS.
- **Across modules:** order by the inter-module dependency graph. First shared library, then modules that own core data, then modules that only consume data, then shells and menus.
- **Output:** a ranked list with a reason for each position (for example "level 0: no dependencies", "level 3: depends on X, Y").

## Stage 5: Chunking (64k budget)

**Budget per LLM call:** about 64k tokens in total. The plan allows about 40k for the prompt and 12k for output, and keeps about 12k as headroom for the system prompt and token-estimation error. Tokens are estimated as characters / 3, which is conservative for COBOL.

Per program:
1. If the program, plus the copybook data it actually references, fits, send it whole.
2. Otherwise split on **section and paragraph boundaries** taken from the stage-2 line ranges, grouping consecutive paragraphs up to the budget. A paragraph is never split unless it alone exceeds the budget; then it is split on statement boundaries.
3. Each chunk gets a context header built from the facts, not from raw source:
   - program purpose (once known);
   - the **definitions of only the data items used in the chunk**, rather than whole copybooks;
   - one-line summaries of PERFORM targets defined in other chunks, filled in hierarchically as chunks are processed in PERFORM order;
   - the resources the chunk touches.

## Stage 6: LLM business rule extraction

The OpenAI-compatible client is configured only by `base_url`, `model` and `api_key` in `.env` (Grok locally, Qwen on the VM).

- **Map step, per chunk:** returns JSON validated against a schema, with retry on invalid output:
  ```json
  {"rules":[{"id":"...","type":"validation|calculation|decision|data-transformation|navigation|error-handling",
     "description":"...","condition":"...","action":"...","data_items":["..."],
     "source":{"paragraph":"...","lines":[120,134]}}],
   "paragraph_summaries":{"PARA-NAME":"..."}}
  ```
- **Reduce step, per program:** merge chunk results into a program summary and a de-duplicated rule list.
- **Reduce step, per module:** combine program summaries into module capabilities.
- **Hallucination guard:** every rule must cite lines and data items that exist in the stage-2 facts. Rules that fail the check are dropped or re-asked.
- **Cache:** results are keyed by (file hash, prompt version, model), so re-runs are cheap.

## Stage 7: Consolidated IR

**Output:** `ir/`. This is not one huge file, because that could not be fed to a 64k model.

| File | Content |
|---|---|
| `ir/index.json` | metadata, inventory summary, entry points, modules (members, shared items, owned data, interfaces), conversion order, missing / unresolved items |
| `ir/graph.json` | all nodes and edges |
| `ir/programs/<NAME>.json` | facts, business rules and summary for one program |
| `ir/modules/<MODULE>.json` | module view: members, internal and external edges, data, rules roll-up |

`ir_query.py` returns **excerpts** within a token budget, for example "module X with its interfaces and top rules, under 30k tokens". Stage 8 and any later conversion step use it.

## Stage 8: Documents and diagrams

Per module, built **mostly from the IR deterministically**, with the LLM writing only the narrative sections:

| Document | Deterministic parts | LLM parts |
|---|---|---|
| PUD (program understanding) | inventory, structure, PERFORM tree, data used, resources | purpose, walkthrough, business rules in plain language |
| TSD (technical specification) | interfaces, COMMAREA / records, files and tables, transactions and jobs, dependencies, conversion order | design notes, target mapping suggestions |
| Activity / flow diagrams | Mermaid from the PERFORM graph and the CICS screen flow (`XCTL`, `RETURN TRANSID`) | node labels from paragraph summaries |
| Context diagram | Mermaid of module to data stores to other modules | none |

Output is Markdown with Mermaid. It can be converted to DOCX or PDF later; the target format is to be decided.

---

## Implementation steps

Each step ends with something you can run and check.

| # | Step | Language | Check against |
|---|---|---|---|
| 1 | Inventory and classifier | Python | File counts per type in the 3 repos |
| 2 | COBOL facts extractor, batch JSON mode in `cobol-ast-runner`, with text fallback | Java + Python | Hand-checked facts for a few CardDemo / CBSA programs |
| 3 | Scanners for CSD, JCL/PROC, BMS, DDL/DCLGEN | Python | CardDemo CSD, `POSTTRAN.jcl`, CBSA `BANK.csd` |
| 4 | Graph builder with resolution, entry points and reports | Python | CardDemo README application inventory |
| 5 | Utilities and hubs, clustering, data ownership, bundles with self-check, conversion order | Python | The CardDemo optional sub-apps should come out as separate modules |
| 6 | Chunker and token estimator | Python | No chunk over budget; chunks follow paragraph boundaries |
| 7 | LLM rule extraction (map-reduce, cache, guard) | Python | Spot-check rules for 2-3 programs, using Grok |
| 8 | IR assembly and `ir_query.py` | Python | Excerpts stay within budget |
| 9 | PUD, TSD and diagram generation | Python | Review one module end to end |

## Open decisions (defaults used until changed)

- **XCTL is treated as navigation, not a hard dependency.** It does not affect conversion order and is not followed through hubs when clustering.
- **Threshold for a "common" copybook:** used by 3 or more modules, or a known IBM copybook (`DFH*`).
- **Document format:** Markdown with Mermaid first; DOCX later if needed.
- **Python packages needed on the VM:** `networkx`, `pyyaml`, `openai` (or `requests`), `jsonschema`. Everything else uses the standard library.
