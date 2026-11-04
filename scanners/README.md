# scanners (pipeline step 3)

Reads the non-COBOL files of a codebase and writes one JSON file per source file: CICS CSD definitions, JCL jobs and PROCs (with PROC expansion), BMS mapsets, DDL and DCLGEN (also SQL found inside JCL), IMS DBD and PSB, and IDCAMS / SORT control cards. Later steps (dependency graph, modules, documents) read these files together with the COBOL facts of step 2.

Output schema: `docs/SCANNERS_SCHEMA.md`. Build plan: `docs/STEP3_BUILD_PLAN.md`.

## Requirements

- Python 3.8 or newer (standard library only). **No Java is needed.**
- The output of step 1: `inventory.json` from `inventory/inventory.py`.
- Optional: the COBOL facts of step 2 (`facts/cobol/*.json` in the same analysis folder). With them the report also compares COBOL names against the CSD, JCL, BMS and DDL facts (checks C6 to C9).

## Run

```
python3 scanners/run_scanners.py \
    --inventory ~/analysis/carddemo/inventory.json \
    --out ~/analysis/carddemo
```

| Option | Meaning |
|---|---|
| `--inventory FILE` | `inventory.json` of step 1 (required). |
| `--out DIR` | Analysis folder, the same as in steps 1 and 2 (required). Results go to `DIR/facts`. |
| `--codebase DIR` | Codebase root. Default: the root recorded in `inventory.json`. |
| `--only A,B` | Only scan the files with these member names (PROC members are always read, because JCL needs them). Good for a quick test. |

The run takes a few seconds. It can be repeated; the results are identical each time.

## Output (in `DIR/facts`)

| Path | Content |
|---|---|
| `csd/NAME.json` | CSD definitions: transactions, programs, files, mapsets, libraries, queues. |
| `jcl/NAME.json` | One JCL member: jobs, steps, DDs with dataset names, the PROC expansion (`flat_steps`), datasets, utility control data (IDCAMS, SORT, SDSF, inline CSD, inline SQL). |
| `proc/NAME.json` | One PROC member (not expanded). |
| `bms/NAME.json` | Mapsets, maps and fields. |
| `ddl/NAME.json` | Tables, columns, indexes and views from DDL and DCLGEN files. |
| `ims/NAME.json` | IMS databases (DBD) and program specification blocks (PSB). |
| `control/NAME.json` | Control card files (IDCAMS or SORT). |
| `scan_index.json` | One line per scanned file with its status. |
| `scan_report.md` | Readable report, see below. |
| `logs/scan_errors.log` | Only exists if a file could not be scanned. |

If two files of the same kind have the same member name, the second one is written as `NAME~2.json`. The real path is always stored inside the file.

Assembler sources and macro libraries are not scanned in this step.

## Reading `scan_report.md`

- **Summary by kind:** number of files per kind, errors and skipped files. Files that are EBCDIC or binary are skipped; convert them to text first.
- **CSD / JCL:** a short overview per file.
- **C1 CSD programs without source:** programs defined in the CSD for which the codebase has no COBOL or assembler source. Check whether the source is missing from the codebase or the definition is old. The second list is for CSD definitions that sit inside a JCL job (for example a `DFHCSDUP` job).
- **C2 CSD transactions whose program has no PROGRAM definition in the same CSD file:** often harmless (autoinstall), listed for completeness.
- **C3 Mapsets:** (a) CSD mapsets without BMS source, (b) the same for inline CSDs (informational), (c) BMS sources that no CSD defines.
- **C4 JCL programs not in the codebase:** programs run by a job step (not a utility) that the codebase does not contain.
- **C5 Procs not found:** PROCs a job calls that are not in the codebase. Their steps cannot be expanded. IBM-supplied PROCs are normally in this list.
- **C6 CICS files used by COBOL but not defined in any CSD FILE**, **C7 Batch DD names** (DDs a program expects but its step lacks, and DDs in the step that the program does not use), **C8 mapsets** and **C9 DB2 tables** need the COBOL facts of step 2.
- **Unresolved JCL symbols:** names such as `&CNTLLIB` that no `SET` statement or PROC default defines.
- **Warnings:** for example duplicate step names inside a job.

## Troubleshooting

| Problem | What to do |
|---|---|
| `scan_errors.log` exists | A file could not be scanned. The log shows the file and the error. The other files are not affected. |
| A PROC is "not found" although its file exists | The file may be classified as something other than `proc` by step 1. Check `inventory_report.md`. PROCs are found by file name first, then by the name on their `PROC` statement. |
| Many unresolved symbols | They come from `SET` statements or PROC defaults outside the codebase (site-specific). The affected dataset names stay as written, for example `&HLQ..LOADLIB`. |
| Files listed as skipped | They are EBCDIC or binary in the inventory. |

## Tests

```
python3 -m unittest discover -s scanners/tests -t scanners
```
