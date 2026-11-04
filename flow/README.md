# flow (pipeline step 4b)

Finds the **main entry points** of a codebase and the order in which its programs and jobs belong to a process, from what the code needs to be true before it runs.

Think of a web application. Every page can be loaded by typing its address, but that does not make every page an entry point. The dashboard needs a logged-in session, and the login page creates it. The login page is the entry point. In CICS the same holds: any transaction can be typed, but a screen that needs data created by an earlier screen is not where the process starts.

Output schema: `docs/FLOW_SCHEMA.md`. Build plan: `docs/STEP4B_BUILD_PLAN.md`.

## Requirements

- Python 3.8 or newer (standard library only).
- Steps 1 to 4 must have run for the codebase in the same analysis folder:
  - `facts/cobol/*.json` and **`facts/raw/*.raw.json`** (step 2; the raw files hold the statements),
  - `graph/graph.json` (step 4).

## Run

```
python3 flow/build_flow.py --out ~/analysis/carddemo
```

It prints `[flow] N online programs, R roots, J jobs`. The run takes a few seconds, can be repeated, and gives identical results each time.

## Output (in `DIR/flow`)

| File | Content |
|---|---|
| `main_entry_points.json` | **Where the process starts**: the online roots with their evidence, programs that could not be placed (`unclear`), and the batch jobs that start the batch order. |
| `process_flow.json` | Every online program with its classification, prerequisites, level and first-entry behaviour; every navigation edge with its direction; the job order. |
| `state_dependencies.json` | The shared state (COMMAREA) record, its fields (cells), who sets and who needs each field. |
| `flow_report.md` | Readable report. |
| `diagrams/online_process.mmd`, `diagrams/batch_order.mmd` | Mermaid diagrams (levels as boxes; back edges dotted). |

`graph/entry_points.json` (step 4) keeps its meaning: programs that *can be started* (a transaction or job exists). `flow/main_entry_points.json` means programs where a process *begins*.

## How to read the result

For every online program the analysis checks:

1. **What happens when it is started without a COMMAREA** (`EIBCALEN = 0`): it shows its own first screen, hands off to another program, or resets its own state and continues. Paragraphs it performs are followed.
2. **Which shared fields it needs** but does not set itself, and which program sets them.

From that, each program gets one classification:

| Classification | Meaning |
|---|---|
| `starter` | Shows its own first screen and needs nothing from another program. |
| `needs_prior` | Hands off to another program when started without a COMMAREA, or needs state that another program sets. It cannot be the start. |
| `expects_caller` | Checks that it was called from a particular program (soft evidence). |
| `unclear` | No evidence either way. A person has to place it (see the `reason`). |

A `starter` that has a transaction is a **root**. It is `certain` if other programs depend on it, `probable` if none do. The **level** of a program is 0 for a root and 1 more than its latest prerequisite otherwise; a navigation edge to a lower level is a `back` edge (return to a menu or to sign-on), to a higher level `forward`.

Batch: a job that defines a dataset (IDCAMS `DEFINE`) comes before the jobs that use it. Datasets defined by more than one job (refresh jobs) give no order. Datasets nobody defines are listed as external inputs. The order between independent jobs is not in the code; it comes from a scheduler or a run book.

## Limits

- The first-entry test is recognised only as `EIBCALEN` compared to zero, in the first paragraph or one paragraph below it. Other conventions are reported as `unclear`.
- Programs without raw facts (the text fallback of step 2) are not analysed.
- Programs that share no state and show no first-entry evidence cannot be placed; they are listed as `unclear`.
- A field that a program reads before it writes it is not counted as required (fewer false dependencies, but some real ones are missed).
- Fields of the shared record are matched by storage position (offset and size), because programs label the same bytes differently. Overlaps that are not exact matches are only reported as warnings.

## Troubleshooting

| Problem | What to do |
|---|---|
| Error: `graph.json` not found | Run `graph/build_graph.py` first (step 4). |
| Warnings `no raw facts for NAME` | The program was analysed by the text fallback or `facts/raw` is missing. Re-run `facts/run_facts.py` with the jar. |
| No root found | No program starts without an earlier one. Look at the `unclear` list; the codebase may use another first-entry convention or may be a batch-only system. |
| Several roots | Several programs work standalone and others depend on them. Check the evidence of each. |
| Many `partial_overlap` warnings | Programs reuse the tail of the COMMAREA with different layouts. This is normal; only exact matches link programs. |

## Tests

```
python3 -m unittest discover -s flow/tests -t flow
```
