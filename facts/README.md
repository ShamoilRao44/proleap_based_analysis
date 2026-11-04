# facts (pipeline step 2)

Reads every COBOL program of a codebase and writes one JSON file per program with its structure, data layouts, copybooks, calls to other programs, files, maps, tables, conditions and error handling. Later steps (dependency graph, modules, chunking, LLM extraction, documents) read only these files.

Output schema: `docs/FACTS_SCHEMA.md`. Build plan: `docs/STEP2_BUILD_PLAN.md`.

## Requirements

- Python 3.8 or newer (standard library only).
- Java 17.
- `cobol-ast-runner.jar`, built from the folder `cobol-ast-runner` (steps below).
- The output of step 1: `inventory.json` from `inventory/inventory.py`.

## Steps

1. Run the inventory once per codebase, if not done yet:
   ```
   python3 inventory/inventory.py ~/repos/CardDemo-Cobol-main --out ~/analysis/carddemo
   ```
2. Build the jar once. The ProLeap parser must already be installed in the local Maven repository (see `cobol-ast-runner/README.md`). The `pom.xml` needs your Nexus `<repositories>` and `<pluginRepositories>` sections.
   ```
   cd cobol-ast-runner
   mvn clean package
   cd ..
   ```
   Result: `cobol-ast-runner/target/cobol-ast-runner.jar`.
3. Run the facts extraction:
   ```
   python3 facts/run_facts.py \
       --inventory ~/analysis/carddemo/inventory.json \
       --out ~/analysis/carddemo \
       --jar cobol-ast-runner/target/cobol-ast-runner.jar
   ```

| Option | Meaning |
|---|---|
| `--inventory FILE` | `inventory.json` of step 1 (required). |
| `--out DIR` | Analysis folder, the same as in step 1 (required). Facts are written to `DIR/facts`. |
| `--jar FILE` | `cobol-ast-runner.jar`. Required unless `--no-proleap` is used. |
| `--codebase DIR` | Codebase root. Default: the root recorded in `inventory.json`. |
| `--jobs N` | Number of Java processes in parallel. Default 1. |
| `--timeout SEC` | Seconds allowed per program. Default 300. |
| `--xmx SIZE` | Java heap per process. Default `2g`. |
| `--only A,B` | Only these program names. Good for a quick test. |
| `--no-proleap` | Skip Java and use only the text scan. Less complete (copybooks are not expanded), but needs no jar. |
| `--java PATH` | Java executable. Default `java`. |

Programs with EBCDIC or binary content are skipped and listed in the report. Convert them to text first.

## Output (in `DIR/facts`)

| Path | Content |
|---|---|
| `cobol/NAME.json` | The facts of one program. This is what later steps read. |
| `_index.json` | One line per program: source (`proleap` or `text`), status, kind, facts file. |
| `facts_report.md` | Readable report, see below. |
| `raw/` | Raw parser output (`NAME.raw.json`) and preprocessed source (`NAME.pp.cbl`). Kept so a run can be resumed and checked. |
| `logs/` | Java logs, the list files, and `build_errors.log` if a program failed to build. |

A run can be repeated. Programs that already have a raw file are not parsed again; delete `raw/` (or single `NAME.raw.json` files) to force a new parse.

## Reading `facts_report.md`

- **Summary:** one row per program. Check that `Source` is `proleap`, `Syntax errors` is 0 or small, and `Line map exact` is above about 95 %.
- **Programs using the text fallback:** programs where the parser result could not be used, with the reason. Their facts are less complete.
- **Unresolved dynamic targets:** `CALL`, `XCTL`, `LINK` or file names held in a variable whose value could not be found. Look them up by hand and note them for the graph step.
- **Missing copybooks:** copybooks that were not found in the codebase. IBM copybooks such as `DFHAID` and `DFHBMSCA` are normally missing; they are not part of the application. For anything else, add the folder to the codebase and run again.
- **Parser vs text differences:** dependencies found by only one of the two methods. `proleap_only` is normal (the parser sees copybook contents). `text_only` entries are copied into the facts (marked `text_only`) and are worth a look.
- **Top unresolved data names:** data names used but not defined anywhere, usually defined in a missing copybook.

## Troubleshooting

| Problem | What to do |
|---|---|
| Status `timeout` for a program | Increase `--timeout` and `--xmx`. The program is retried only after you delete its `raw/NAME.raw.json`. |
| Status `parse_failed` or `preprocess_failed` | The text fallback is used automatically. See `logs/java_0.log` and the `error` field of `raw/NAME.raw.json`. |
| Many programs list the same missing copybook | The copybook is not in the codebase, or its file has a different name. Check `inventory_report.md`. |
| `OutOfMemoryError` in a Java log | Use `--xmx 4g` and `--jobs 1`. |
| `cannot start java` | Pass the full path with `--java`. |
| `build_errors.log` exists | A program could not be turned into facts. Send the log and the program name to whoever maintains the tool. |

## Tests

```
python3 -m unittest discover -s facts/tests -t facts
```
