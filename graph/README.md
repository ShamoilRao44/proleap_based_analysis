# graph (pipeline step 4)

Joins the COBOL facts (step 2) and the CSD / JCL / BMS / DDL / IMS facts (step 3) into one typed dependency graph: which program calls, links or navigates to which program, which program runs under which transaction or job step, and which programs and steps read or write which data. It also finds the entry-point programs and writes diagrams. Step 5 (modules, bundles, conversion order) reads the graph.

Output schema: `docs/GRAPH_SCHEMA.md`. Build plan: `docs/STEP4_BUILD_PLAN.md`.

## Requirements

- Python 3.8 or newer (standard library only). No Java, no pip packages.
- Steps 1 to 3 must have run for the codebase, in the same analysis folder. The builder reads:
  - `inventory.json`
  - `facts/cobol/*.json` (step 2)
  - `facts/csd`, `facts/jcl`, `facts/proc`, `facts/bms`, `facts/ddl`, `facts/ims`, `facts/control` (step 3; folders that do not exist are treated as empty)

## Run

```
python3 graph/build_graph.py --out ~/analysis/carddemo
```

`--inventory FILE` is optional; the default is `<out>/inventory.json`. The run takes a few seconds, can be repeated, and gives identical results each time. It prints `[graph] N nodes, M edges, E entry points`.

## Output (in `DIR/graph`)

| File | Content |
|---|---|
| `graph.json` | The graph: nodes, edges, entry points, unresolved items and the analysis. This is what step 5 reads. |
| `entry_points.json` | The COBOL entry-point programs and how each one is started. |
| `graph_report.md` | Readable report, see below. |
| `nodes.csv`, `edges.csv` | Flat tables for a spreadsheet. |
| `diagrams/online_flow.mmd` | Transactions, programs and screens (Mermaid). |
| `diagrams/batch_flow.mmd` | Jobs, steps and the datasets they read and write (Mermaid). |
| `diagrams/data_access.mmd` | Programs and the files, tables and queues they use (Mermaid). |

## Reading `graph_report.md`

- **Counts:** nodes and edges by type. Edge strength: `hard` (CALL, LINK), `navigation` (XCTL, RETURN TRANSID), `entry` (what starts what), `build` (COPY, maps), `data`, `config`, `operational`.
- **Entry points:** transactions (CICS entry), jobs (batch entry) and *candidate entry programs*. A candidate has no caller, no transaction and no job in the codebase; it is dead code, or it is started from outside (a scheduler or another system).
- **Entry-point programs:** an entry point is an application program started by a CICS transaction or a JCL step, or one that nobody calls. `XCTL` (screen navigation) does not count as "calls". Programs that are only called by others, or only reached by screen navigation, are listed as not entry points.
- **Online flow / Batch jobs:** which programs a transaction reaches, and for each job step which datasets it reads and writes.
- **Data stores:** datasets with their CICS files, the online and batch programs that use them (with access), and whether online and batch share them (**Shared = yes** means a change on one side affects the other; keep both in the same module or define an interface).
- **Online programs that submit batch jobs:** programs that write to a CICS queue that is wired to the internal reader.
- **Fan-in / fan-out:** the most called programs (shared subroutines).
- **Cycles:** hard cycles are real mutual dependencies. Navigation cycles are normal in CICS (menu to screen and back).
- **Orphans:** application programs that no transaction, job or program reaches.
- **Missing:** programs, copybooks, maps, files and transactions that are referenced but not in the codebase. IBM copybooks (`DFH...`) and system programs (`CEE...`) are expected to be missing.
- **Unused:** copybooks, PROCs, maps and control cards nothing refers to.
- **Unresolved:** dynamic `CALL` / `XCTL` targets whose value could not be found, resources whose name could not be resolved, DDs a program expects but its job step lacks, PROCs that were not found, JCL symbols without a value.

## Viewing the diagrams

The `.mmd` files are Mermaid text. Open them in any editor or Markdown preview that supports Mermaid; on a machine with internet access you can also paste them into mermaid.live. Diagrams show at most 300 edges; a final comment line tells how many were left out.

## Troubleshooting

| Problem | What to do |
|---|---|
| Error `No such file ... facts/cobol` or an empty graph | Run steps 1 to 3 first (`inventory.py`, `facts/run_facts.py`, `scanners/run_scanners.py`) with the same `--out` folder. |
| No transactions or jobs in the graph | The CSD or JCL files were not found by step 1, or step 3 was not run. Check `inventory_report.md` and `facts/scan_report.md`. |
| Many "Missing programs" | Programs are called but not in the codebase (other systems, IBM or vendor modules). Check the list; real application programs should be added to the codebase. |
| Many unresolved dynamic calls | A `CALL` or `XCTL` target is held in a variable the facts could not resolve (see `facts/facts_report.md`). |

## Tests

```
python3 -m unittest discover -s graph/tests -t graph
```
