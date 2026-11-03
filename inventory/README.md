# inventory (pipeline step 1)

Classifies every file of a mainframe codebase **by content**, not by extension, and records the name each file declares. The output is the input for the later pipeline steps. Uses only the Python standard library (3.8+).

## Usage

```
python3 inventory.py <codebase_root> --out <analysis_dir>
```

Example:

```
python3 ~/proleap_based_analysis/inventory/inventory.py ~/repos/CardDemo-Cobol-main --out ~/analysis/carddemo
```

Run it once per codebase, each with its own output folder.

## Output

| File | Content |
|---|---|
| `inventory.json` | One record per file, plus summary, duplicates and name mismatches. Used by the next steps. |
| `inventory_report.md` | Readable summary: counts per type, duplicate member names, files whose declared name differs from the file name, extension/content mismatches, and files to review. |

Each record in `inventory.json` looks like this:

```json
{
  "path": "app/cbl/CBACT01C.cbl",
  "name": "CBACT01C",
  "type": "cobol_program",
  "declared_name": "CBACT01C",
  "confidence": "high",
  "reason": "IDENTIFICATION DIVISION + PROGRAM-ID",
  "source_format": "fixed",
  "encoding": "ascii",
  "lines": 193,
  "size": 15504,
  "sha256": "..."
}
```

- `name` is the member name: the file name in upper case, without extension.
- `declared_name` is the name inside the file: PROGRAM-ID, JOB or PROC name, mapset label, DBD / PSB name, or CSECT.
- `subtype` (copybooks only) is one of `data`, `procedure` or `bms_symbolic_map`.

## Types

| Type | Recognised by |
|---|---|
| `cobol_program` | `PROGRAM-ID` (plus `IDENTIFICATION DIVISION`) |
| `copybook` | COBOL data or procedure lines without `PROGRAM-ID` |
| `dclgen` | `EXEC SQL DECLARE ... TABLE` |
| `bms` | `DFHMSD` macro |
| `jcl` | `//name JOB` |
| `proc` | `//name PROC`, or EXEC/DD statements without a JOB card |
| `csd` | CICS `DEFINE TRANSACTION / PROGRAM / FILE ...` |
| `ddl` | `CREATE TABLE / INDEX / VIEW ...` |
| `ims_dbd`, `ims_psb` | `DBD NAME=`, `PSBGEN` / `PCB TYPE=` |
| `assembler`, `asm_macro` | `CSECT` / assembler instructions, `MACRO` |
| `control_card` | IDCAMS, SORT, DB2 utility statements |
| `data` | EBCDIC data sets, or fixed-length text records |
| `document`, `other_source`, `binary`, `empty`, `unknown` | not part of the mainframe analysis |

Documentation files (`.md`, `.pdf`, images, and `LICENSE`, `NOTICE` and the like) are recognised by name first, because they often quote JCL, CSD or COBOL as examples.

## What to check in the report

- **Duplicate member names.** Two programs or two copybooks with the same name. Later steps need to know which one is real. Names only collide within the same kind of library, so a BMS mapset and its symbolic-map copybook with the same name are not reported.
- **Declared name differs from member name.** For example a PROC file whose PROC statement uses another name. Later steps resolve references by the member name, not the declared one.
- **To review.** Files classified with low or medium confidence, and `unknown` files.
