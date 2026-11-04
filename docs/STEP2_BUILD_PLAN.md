# Step 2 build plan: COBOL facts extractor

This document is a complete build instruction. Follow it exactly, in order. Every design decision has already been made; when something is not specified, choose the simplest option that satisfies the text and note it in the final report (section 12).

---

## 0. Rules for the implementer

1. **Test only on the AWS repo:** `C:\My Folder\TCS\aws-mainframe-modernization-carddemo`. Never run any tool from this step on `CardDemo-Cobol-main` or `cics-banking-sample-application-cbsa-July2024Refresh`. The user tests those manually.
2. **Do not modify** `proleap-cobol-parser`, `inventory/`, `fetch_copybooks/`, or the existing files `AstRunner.java`, `AstPrinter.java`, `AsgSummary.java`, `CollectingParserRunner.java`. Add new files only, except where section 1 says to edit an existing file.
3. **Python:** standard library only, must run on Python 3.8. No type hints with generics (`list[str]`), no `match`, no f-string `=` specifier, no third-party packages.
4. **Java:** JDK 17. No new Maven dependencies. The jar must stay buildable offline from the existing `pom.xml`.
5. **Local Maven** (for building on this Windows machine only):
   `C:\Users\53sra\AppData\Local\Temp\claude\c--My-Folder-TCS-proleap-cobol\3e1344f8-ff1c-49a6-80cb-00f892abb974\scratchpad\apache-maven-3.9.6\bin\mvn.cmd`
   The ProLeap parser 4.0.0 is already installed in `~/.m2`.
6. **Stop conditions.** Stop and report to the user (do not work around) if:
   - the marker check in task 2.1 fails (section 9, check C1);
   - the jar does not build after fixing obvious compile errors (wrong import, typo, generated accessor name);
   - any acceptance check in section 9 fails and the cause is not a bug in the code you wrote.
7. All paths in this document are relative to `C:\My Folder\TCS\proleap_based_analysis` unless they start with a drive letter.
8. Never commit to git. The user commits.

---

## 1. What gets built

```
proleap_based_analysis/
├── cobol-ast-runner/src/main/java/local/cobol/facts/   (NEW Java package, same jar)
│   ├── MarkingPreprocessor.java
│   ├── MarkingDocumentParser.java
│   ├── MarkingDocumentParserListener.java
│   ├── Json.java
│   ├── Ctx.java                  (parse-tree helper functions)
│   ├── FactsExtractor.java       (parse tree -> raw facts map)
│   └── FactsRunner.java          (batch main class)
├── cobol-ast-runner/README.md    (EDIT: add section "Batch facts mode")
├── facts/                        (NEW Python tool)
│   ├── run_facts.py              (driver CLI)
│   ├── README.md
│   ├── facts_lib/
│   │   ├── __init__.py           (empty)
│   │   ├── common.py
│   │   ├── linemap.py
│   │   ├── textscan.py
│   │   ├── cics.py
│   │   ├── sql.py
│   │   ├── layout.py
│   │   ├── dynamic.py
│   │   ├── flow.py
│   │   ├── build.py
│   │   ├── compare.py
│   │   └── report.py
│   └── tests/
│       ├── __init__.py           (empty)
│       ├── test_cics.py
│       ├── test_sql.py
│       ├── test_layout.py
│       └── test_linemap.py
└── docs/FACTS_SCHEMA.md          (NEW: copy of section 7 + section 8 of this document)
```

Data flow:

```
inventory.json ──► run_facts.py ──► list_<n>.tsv ──► java FactsRunner ──► facts/raw/<NAME>.raw.json + <NAME>.pp.cbl
                         │                                                        │
                         ├── textscan.py (always, every program) ──► text raw ────┤
                         │                                                        ▼
                         └──────────────────────────────────────────► build.py ──► facts/cobol/<NAME>.json
                                                                      compare.py ─► merged text-only deps
                                                                      report.py ──► facts/facts_report.md, facts/_index.json
```

Two layers:
- **Raw facts** (`cobol-raw-facts/1`, section 5): what the parser saw, with line numbers in the *preprocessed* text ("plines"). Produced by Java, or by `textscan.py` as a fallback with the same schema.
- **Final facts** (`cobol-facts/1`, section 7): everything derived, with locations mapped back to real files and lines. Produced only by Python, from either raw source. All downstream stages read only final facts.

---

## 2. Background the implementer needs

- The ProLeap preprocessor replaces each `COPY X.` with the text of copybook X and leaves **no marker**. It also merges continuation lines. So line numbers from the parser are line numbers in the preprocessed text, not in the source. Task 2.1 fixes this by injecting marker comment lines around each copybook, and `linemap.py` maps every preprocessed line back to `(file, line)`.
- `EXEC CICS`, `EXEC SQL`, `EXEC SQLIMS` blocks are not parsed by ProLeap. They arrive as tokens of type `EXECCICSLINE` / `EXECSQLLINE` / `EXECSQLIMSLINE`, each token one line starting with the tag `*>EXECCICS` / `*>EXECSQL` / `*>EXECSQLIMS`, and the line containing END-EXEC has a ` }` appended. Python parses the command text (`cics.py`, `sql.py`).
- `EXEC DLI` is not handled by ProLeap at all (it causes syntax errors). Python scans it from the original source (`textscan.scan_exec_dli`).
- In the ProLeap lexer, a comment line must be `*>` followed by a space. The markers therefore start with `*> @@`.
- The parse tree classes are generated from `C:\My Folder\TCS\proleap-cobol-parser\src\main\antlr4\io\proleap\cobol\Cobol.g4`. Rule `fooBar` produces class `CobolParser.FooBarContext`. Generated sources are under `C:\My Folder\TCS\proleap-cobol-parser\target\generated-sources\antlr4` if you need to check a name. **Use only the `Ctx` helper methods (section 4.5) to navigate the tree**, not generated accessor methods; this avoids accessor-name mistakes.

---

## 3. Task order

| Task | Content | Done when |
|---|---|---|
| 2.1 | Java: `MarkingPreprocessor`, `MarkingDocumentParser`, `MarkingDocumentParserListener`, `Json`, `Ctx`, a minimal `FactsExtractor` (only `program_ids`, `syntax_errors`, `divisions`) and the full `FactsRunner`. Python: `common.py`, `linemap.py`, `test_linemap.py`. | Checks C1 and C2 pass (section 9) |
| 2.2 | Java: complete `FactsExtractor` (section 5). | Check C3 passes |
| 2.3 | Python: `cics.py`, `sql.py`, `layout.py` + their tests | `python -m unittest discover -s facts/tests -t facts` passes |
| 2.4 | Python: `dynamic.py`, `flow.py`, `build.py` | Checks C4–C8 pass |
| 2.5 | Python: `textscan.py`, `compare.py`, `report.py`, `run_facts.py` | Checks C9–C11 pass |
| 2.6 | Docs: `facts/README.md`, `docs/FACTS_SCHEMA.md`, README edit; final report | Section 12 delivered |

---

## 4. Java

All new classes are in package `local.cobol.facts`, directory `cobol-ast-runner/src/main/java/local/cobol/facts/`. Use tabs for indentation, like the existing code.

### 4.1 MarkingPreprocessor.java (write exactly this)

```java
package local.cobol.facts;

import java.util.List;

import io.proleap.cobol.preprocessor.impl.CobolPreprocessorImpl;
import io.proleap.cobol.preprocessor.sub.document.CobolDocumentParser;

/**
 * ProLeap preprocessor that writes marker comment lines around every expanded copybook, so that
 * preprocessed lines can be mapped back to the copybook file they came from. Missing copybooks do
 * not stop preprocessing; they are recorded and replaced by a single marker line.
 */
public class MarkingPreprocessor extends CobolPreprocessorImpl {

	public static final String ENTER = "*> @@CPYENTER ";

	public static final String EXIT = "*> @@CPYEXIT ";

	public static final String MISSING = "*> @@CPYMISSING ";

	protected final List<String> missing;

	public MarkingPreprocessor(final List<String> missing) {
		this.missing = missing;
	}

	@Override
	protected CobolDocumentParser createDocumentParser() {
		return new MarkingDocumentParser(missing);
	}
}
```

### 4.2 MarkingDocumentParser.java (write exactly this)

```java
package local.cobol.facts;

import java.util.List;

import org.antlr.v4.runtime.CommonTokenStream;

import io.proleap.cobol.asg.params.CobolParserParams;
import io.proleap.cobol.preprocessor.sub.document.CobolDocumentParserListener;
import io.proleap.cobol.preprocessor.sub.document.impl.CobolDocumentParserImpl;

public class MarkingDocumentParser extends CobolDocumentParserImpl {

	protected final List<String> missing;

	public MarkingDocumentParser(final List<String> missing) {
		this.missing = missing;
	}

	@Override
	protected CobolDocumentParserListener createDocumentParserListener(final CobolParserParams params,
			final CommonTokenStream tokens) {
		return new MarkingDocumentParserListener(params, tokens, missing);
	}
}
```

### 4.3 MarkingDocumentParserListener.java (write exactly this)

```java
package local.cobol.facts;

import java.io.File;
import java.io.IOException;
import java.util.List;

import org.antlr.v4.runtime.BufferedTokenStream;

import io.proleap.cobol.CobolPreprocessorParser.CopySourceContext;
import io.proleap.cobol.asg.params.CobolParserParams;
import io.proleap.cobol.preprocessor.sub.document.impl.CobolDocumentParserListenerImpl;

public class MarkingDocumentParserListener extends CobolDocumentParserListenerImpl {

	protected final List<String> missing;

	public MarkingDocumentParserListener(final CobolParserParams params, final BufferedTokenStream tokens,
			final List<String> missing) {
		super(params, tokens);
		this.missing = missing;
	}

	public static String copyName(final CopySourceContext copySource) {
		String text = copySource.getChild(0).getText().trim();
		if (text.length() >= 2 && (text.startsWith("'") || text.startsWith("\""))) {
			text = text.substring(1, text.length() - 1);
		}
		return text.toUpperCase();
	}

	@Override
	protected String getCopyBookContent(final CopySourceContext copySource, final CobolParserParams params) {
		final String name = copyName(copySource);
		final File copyBook = findCopyBook(copySource, params);

		if (copyBook == null) {
			missing.add(name);
			return "\n" + MarkingPreprocessor.MISSING + name;
		}

		final String content;
		try {
			content = new MarkingPreprocessor(missing).process(copyBook, params);
		} catch (final IOException e) {
			missing.add(name + " (unreadable: " + e.getMessage() + ")");
			return "\n" + MarkingPreprocessor.MISSING + name;
		}

		return "\n" + MarkingPreprocessor.ENTER + name + "|" + copyBook.getAbsolutePath() + "\n" + content + "\n"
				+ MarkingPreprocessor.EXIT + name;
	}
}
```

If `super(params, tokens)` does not compile because the constructor parameter type differs, change only the parameter type to match the ProLeap constructor.

### 4.4 Json.java

A minimal JSON serializer. Public API:

```java
public static String write(Object value)          // compact, no indentation
public static void write(Object value, Writer out) throws IOException
```

Supported values: `null`, `Boolean`, `Number` (write `Integer`/`Long` with `toString()`; `Double` with `toString()`, but write `NaN`/`Infinity` as `null`), `String`, `Map<?,?>` (keys via `String.valueOf`, iterate in map order; always use `LinkedHashMap` when building), `List<?>`/`Collection<?>`. Anything else: write as JSON string of `String.valueOf(value)`.

String escaping: `"` → `\"`, `\` → `\\`, `\n` → `\n`, `\r` → `\r`, `\t` → `\t`, `\b`, `\f`, every other char < 0x20 → `\u00XX` (4 hex digits, lower case). Characters ≥ 0x20 are written as they are (file is UTF-8).

### 4.5 Ctx.java (parse tree helpers)

Static methods only. Imports `org.antlr.v4.runtime.*`, `org.antlr.v4.runtime.misc.Interval`, `org.antlr.v4.runtime.tree.*`, `io.proleap.cobol.CobolParser`.

| Method | Behaviour |
|---|---|
| `static <T extends ParserRuleContext> T child(ParserRuleContext ctx, Class<T> type)` | First **direct** child that is an instance of `type`, else `null`. `ctx == null` → `null`. |
| `static <T extends ParserRuleContext> List<T> children(ParserRuleContext ctx, Class<T> type)` | All direct children of `type`, in order. |
| `static <T extends ParserRuleContext> T first(ParserRuleContext ctx, Class<T> type)` | First descendant (pre-order, excluding `ctx` itself) of `type`, else `null`. |
| `static <T extends ParserRuleContext> List<T> all(ParserRuleContext ctx, Class<T> type)` | All descendants of `type` in pre-order (excluding `ctx`). Iterative DFS with an explicit stack; push children in reverse. |
| `static <T extends ParserRuleContext> List<T> allOutsideStatements(ParserRuleContext ctx, Class<T> type)` | Like `all`, but does **not** descend into any `CobolParser.StatementContext` below `ctx`. |
| `static <T extends ParserRuleContext> T ancestor(ParserRuleContext ctx, Class<T> type)` | Nearest proper ancestor of `type`, else `null`. |
| `static boolean hasToken(ParserRuleContext ctx, int tokenType)` | Some **direct** child is a `TerminalNode` whose `getSymbol().getType() == tokenType`. |
| `static String firstTokenText(ParserRuleContext ctx)` | Text of the first direct `TerminalNode` child, else `null`. |
| `static String lastTokenText(ParserRuleContext ctx)` | Text of the last direct `TerminalNode` child, else `null`. |
| `static String text(ParserRuleContext ctx)` | Original source text including whitespace: if `ctx`, start or stop is null, or `stop.getStopIndex() < start.getStartIndex()`, return `""`; else `ctx.getStart().getInputStream().getText(Interval.of(start.getStartIndex(), stop.getStopIndex()))`. |
| `static String compact(String s)` | `s.replaceAll("\\*>[^\\n]*", " ").replaceAll("\\s+", " ").trim()` |
| `static String ctext(ParserRuleContext ctx)` | `compact(text(ctx))` |
| `static String cap(String s, int max)` | `s` if length ≤ max, else `s.substring(0, max) + "..."` |
| `static int startLine(ParserRuleContext ctx)` | `ctx.getStart().getLine()`, or `-1` if null. |
| `static int endLine(ParserRuleContext ctx)` | `ctx.getStop().getLine()`, or `startLine(ctx)` if stop is null. |
| `static String ruleName(ParserRuleContext ctx)` | `CobolParser.ruleNames[ctx.getRuleIndex()]` |
| `static String unquote(String s)` | Trim; if length ≥ 2 and starts and ends with the same quote char (`'` or `"`), remove them and replace doubled quotes (`''` or `""`) inside with one. Else return trimmed `s`. |
| `static String headName(ParserRuleContext ctx)` | Name of the first `QualifiedDataNameFormat1Context` in `ctx` (including `ctx` itself if it is one): the text of its `DataNameContext` or `ConditionNameContext` direct child, upper case. If none: `ctext(ctx).toUpperCase()`. |
| `static String execText(ParserRuleContext ctx, String tag)` | For each direct `TerminalNode` child of `ctx`: take its text, remove the leading `tag` if present, remove every `}` character, trim. Join the non-empty parts with one space. Return the result. |

### 4.6 FactsRunner.java (batch main)

Run as:

```
java -Xmx2g -cp cobol-ast-runner.jar local.cobol.facts.FactsRunner --list <file.tsv> --out <raw_dir> [--copybooks DIR]... [--timeout-sec 300] [--verbose]
```

- `--list`: UTF-8 TSV, one program per line: `NAME<TAB>ABSOLUTE_PATH<TAB>FORMAT<TAB>CHARSET`. FORMAT is `FIXED`, `VARIABLE` or `TANDEM`. CHARSET is a Java charset name (`UTF-8` or `ISO-8859-1`). Ignore empty lines.
- `--copybooks`: repeatable. Copybook extensions are collected exactly as `AstRunner.collectExtensions` does (copy that method, do not call AstRunner).
- Set `System.setProperty("org.slf4j.simpleLogger.defaultLogLevel", verbose ? "info" : "warn")` before anything else.
- Create `<raw_dir>` if missing.
- For each line, in order:
  1. If `<raw_dir>/<NAME>.raw.json` already exists, print `SKIP <NAME>` and continue (this makes the run resumable).
  2. Run `processOne(...)` on a single-thread `ExecutorService` whose thread is a **daemon** thread. Wait with `future.get(timeoutSec, SECONDS)`.
  3. On `TimeoutException`: write the raw JSON with `status` = `"timeout"` (fields from 5.1 that are known: schema, name, program_file, parser, format, charset, status, error = `"timeout after N s"`), print `TIMEOUT <NAME>`, flush stdout, call `System.exit(4)`. The Python driver restarts the run and the SKIP rule continues after it.
  4. On normal completion print `DONE <NAME> <status>`.
- After the loop print `FINISHED` and exit 0. Exit 1 for bad arguments.

`processOne(name, file, format, charset, copybookDirs, outDir)`:

```
params = new CobolParserParamsImpl(); setCopyBookDirectories, setCopyBookExtensions, setFormat, setDialect(ANSI85),
         setCharset(charset), setIgnoreSyntaxErrors(true)
missing = new ArrayList<String>()
start = System.currentTimeMillis()
try:
    pp = new MarkingPreprocessor(missing).process(file, params)
catch java.nio.charset.CharacterCodingException (includes MalformedInputException):
    charset = ISO_8859_1; params.setCharset(charset); missing.clear(); pp = new MarkingPreprocessor(missing).process(file, params)
catch any other Exception e:
    write raw with status "preprocess_failed", error = e.toString(); return
write <outDir>/<NAME>.pp.cbl  (UTF-8, content = pp)
errors = new ArrayList<Map>()   // filled by the error listener: {"pline": line, "col": charPositionInLine, "msg": shortened msg}
lexer = new CobolLexer(CharStreams.fromString(pp)); lexer.removeErrorListeners(); lexer.addErrorListener(collector)
tokens = new CommonTokenStream(lexer)
parser = new CobolParser(tokens); parser.removeErrorListeners(); parser.addErrorListener(collector)
try:
    root = parser.startRule()
    facts = new FactsExtractor(root).extract()     // LinkedHashMap
    status = errors.isEmpty() ? "ok" : "syntax_errors"
catch any Exception/StackOverflowError e:
    facts = new LinkedHashMap(); status = "parse_failed"; error = e.toString()
put header fields (5.1) first, then facts fields, write <outDir>/<NAME>.raw.json (UTF-8)
```

Message shortening: copy the logic from `CollectingParserRunner` (cut the part after ` expecting {` to 120 chars and append ` ...}`). Keep at most the first 500 syntax errors, and set `syntax_error_count` to the full count.

Write the JSON to a temp file `<NAME>.raw.json.tmp` first, then rename to `<NAME>.raw.json` (`Files.move(..., REPLACE_EXISTING, ATOMIC_MOVE)`; if ATOMIC_MOVE throws, retry without it). This keeps the SKIP rule correct after a kill.

### 4.7 FactsExtractor.java

Constructor `FactsExtractor(CobolParser.StartRuleContext root)`. Method `Map<String,Object> extract()` returns a `LinkedHashMap` with exactly the keys of section 5.2, in that order. Use `Ctx` helpers for all navigation. All names are upper-cased. All plines are `Ctx.startLine` / `Ctx.endLine`. All values that are lists are `ArrayList`, maps are `LinkedHashMap`. Missing values are JSON `null`, never omitted.

Implementation details for each key are given in section 5.2 (the "How" column). Statement handling is in 5.3.

---

## 5. Raw facts schema (`cobol-raw-facts/1`)

File: `<out>/facts/raw/<NAME>.raw.json`. One object.

### 5.1 Header (written by FactsRunner)

| Key | Type | Value |
|---|---|---|
| `schema` | string | `"cobol-raw-facts/1"` |
| `name` | string | NAME from the list file |
| `program_file` | string | absolute path |
| `parser` | string | `"proleap"` (textscan writes `"text"`) |
| `format` | string | `FIXED` / `VARIABLE` / `TANDEM` |
| `charset` | string | charset actually used |
| `status` | string | `ok`, `syntax_errors`, `preprocess_failed`, `parse_failed`, `timeout` |
| `error` | string/null | exception text, else null |
| `parse_ms` | int | milliseconds for preprocessing + parsing + extraction |
| `preprocessed_file` | string/null | `"<NAME>.pp.cbl"` (file name only), null if preprocessing failed |
| `missing_copybooks` | list[string] | from the `missing` list, de-duplicated, in first-seen order |
| `syntax_error_count` | int | |
| `syntax_errors` | list | `{"pline", "col", "msg"}`, max 500 |

### 5.2 Extracted keys (written by FactsExtractor)

| Key | Type | How |
|---|---|---|
| `program_ids` | list[string] | Every `ProgramIdParagraphContext` → its `ProgramNameContext` → `Ctx.unquote(text)` upper. |
| `divisions` | object | Keys `identification`, `environment`, `data`, `procedure`. Each `[startPline, endPline]` of the **first** `IdentificationDivisionContext` / `EnvironmentDivisionContext` / `DataDivisionContext` / `ProcedureDivisionContext`, or null. |
| `data_sections` | list | For each `DataDivisionSectionContext` in the first data division: let `s` = its first child rule context. `kind` = `FILE` for `FileSectionContext`, `WORKING-STORAGE` for `WorkingStorageSectionContext`, `LOCAL-STORAGE` for `LocalStorageSectionContext`, `LINKAGE` for `LinkageSectionContext`, else `OTHER`. Object `{"kind", "start", "end"}` (plines of `s`). |
| `selects` | list | For each `FileControlEntryContext`: see 5.4. |
| `fds` | list | For each `FileDescriptionEntryContext`: `{"file": text of FileNameContext upper, "kind": firstTokenText upper ("FD"/"SD"), "pline"}`. |
| `data_items` | list | See 5.5. |
| `data_exec_sql` | list | For each `DataDescriptionEntryExecSqlContext`: `{"exec_text": Ctx.execText(ctx, "*>EXECSQL"), "pline", "pline_end"}`. |
| `procedure_using` | list[string] | First `ProcedureDivisionUsingClauseContext` in the procedure division: for each `QualifiedDataNameFormat1Context` in it: its head name. Empty list if none. |
| `sections` | list | For each `ProcedureSectionContext` and each `ProcedureDeclarativeContext` (pre-order): `{"name": text of the SectionNameContext inside its ProcedureSectionHeaderContext, upper, "start", "end", "declaratives": true for ProcedureDeclarativeContext else false}`. |
| `paragraphs` | list | For each `ParagraphContext` in the procedure division (pre-order): `{"name": text of its ParagraphNameContext upper, "section": name of nearest ancestor ProcedureSectionContext or ProcedureDeclarativeContext (via its header) or null, "declaratives": true if it has an ancestor ProcedureDeclarativesContext, "start", "end"}`. |
| `statements` | list | See 5.3. |

### 5.3 Statements

Collect every `StatementContext` under the first `ProcedureDivisionContext` with `Ctx.all` (pre-order = source order). Number them `id` = 1, 2, 3, … in that order. For each statement `S`, let `X` = `S.getChild(0)` cast to `ParserRuleContext` (the specific statement, e.g. `MoveStatementContext`).

Common fields (every statement, in this order):

| Field | Value |
|---|---|
| `id` | int |
| `type` | `Ctx.ruleName(X)` with the suffix `Statement` removed. Examples: `move`, `perform`, `if`, `evaluate`, `call`, `execCics`, `execSql`, `execSqlIms`, `goTo`, `goback`, `stop`, `exit`, `open`, `read`, `write`, `rewrite`, `delete`, `start`, `close`, `search`, `set`, `compute`, `add`, `initialize`, `display`, `continue`, `nextSentence`. |
| `pline`, `pline_end` | `Ctx.startLine(X)`, `Ctx.endLine(X)` |
| `paragraph` | name of nearest ancestor `ParagraphContext`, or null |
| `section` | name of nearest ancestor `ProcedureSectionContext` / `ProcedureDeclarativeContext`, or null |
| `parent` | `id` of the nearest ancestor `StatementContext`, or null |
| `branch` | null if `parent` is null. Otherwise: let `P` = parent statement's specific context (its child 0). Walk up from `S` until the node whose parent is `P`; call that node `B`. Then: `IfThenContext` → `"then"`; `IfElseContext` → `"else"`; `EvaluateWhenPhraseContext` → `"when:" + index` (0-based index of `B` among `Ctx.children(P, EvaluateWhenPhraseContext.class)`); `EvaluateWhenOtherContext` → `"other"`; `PerformInlineStatementContext` → `"inline"`; `SearchWhenContext` → `"when:" + index` among `Ctx.children(P, SearchWhenContext.class)`; anything else → `Ctx.ruleName(B)` (for example `atEndPhrase`, `invalidKeyPhrase`, `notInvalidKeyPhrase`, `onExceptionClause`). |
| `text` | For `execCics`/`execSql`/`execSqlIms`: same as `exec_text` below, capped 300. Otherwise `Ctx.cap(Ctx.ctext(X), 300)`. |
| `reads`, `writes` | See "data references" below. Sorted unique lists of upper-case names. |

Data references: take `Ctx.allOutsideStatements(X, QualifiedDataNameFormat1Context.class)`. For each `q`: name = text of its `DataNameContext` or `ConditionNameContext` direct child, upper. Decide write vs read by walking up from `q` to `X` (exclusive):
- if an ancestor is `SubscriptContext` or `ReferenceModifierContext` → **read** (stop walking);
- if an ancestor is one of `ComputeStoreContext`, `AddToContext`, `AddGivingContext`, `SubtractMinuendContext`, `SubtractGivingContext`, `MultiplyRegularOperandContext`, `MultiplyGivingResultContext`, `DivideIntoContext`, `DivideGivingContext`, `DivideRemainderContext`, `SetToContext`, `ReadIntoContext`, `StringIntoPhraseContext`, `UnstringIntoContext` → **write** (stop);
- if an ancestor is an `IdentifierContext` whose parent is `MoveToStatementContext`, `MoveCorrespondingToStatementContext`, `InitializeStatementContext` or `AcceptStatementContext` → **write** (stop);
- otherwise → **read**.

A name can appear in both lists.

Type-specific fields (added after the common fields):

| type | Fields |
|---|---|
| `perform` | `inline`: true if `X` has a `PerformInlineStatementContext` child. `target`, `thru`: for `PerformProcedureStatementContext`: its `ProcedureNameContext` children; for each: if it has a `ParagraphNameContext` child use its text, else the `SectionNameContext` text; upper. `target` = first, `thru` = second or null. Inline: both null. `perform_type`: `"times"` / `"until"` / `"varying"` if a `PerformTimesContext` / `PerformUntilContext` / `PerformVaryingContext` exists in the `PerformTypeContext` of the procedure or inline statement, else null. `until`: `Ctx.ctext` of the `ConditionContext` inside `PerformUntilContext` (or inside `PerformVaryingContext`, first one) or null. |
| `goTo` | `targets`: names of all `ProcedureNameContext` in `X` (same rule as perform). `depending`: `Ctx.ctext` of the identifier in `GoToDependingOnStatementContext`, or null. |
| `call` | If `X` has a direct `LiteralContext` child: `target_literal` = `Ctx.unquote(text)` upper, `target_var` = null. Else: `target_literal` = null, `target_var` = `Ctx.headName` of the direct `IdentifierContext` child, `target_text` = its ctext. (`target_text` is always present: literal text or identifier text.) `using`: list of `{"mode": "reference"/"value"/"content", "text": ctext, "name": headName or null if literal}` for each item in `CallByReferenceContext` / `CallByValueContext` / `CallByContentContext` inside the `CallUsingPhraseContext`, in order; mode from the enclosing `CallByReferencePhraseContext` / `CallByValuePhraseContext` / `CallByContentPhraseContext`. |
| `move` | `corresponding`: bool. For `MoveToStatementContext`: sending = `MoveToSendingAreaContext`. If it has a `LiteralContext` child: `from_literal` = `Ctx.text(literal)` (raw, quotes kept), `from_var` = null; else `from_literal` = null, `from_var` = headName. `to`: headName of each direct `IdentifierContext` child of the `MoveToStatementContext`. For corresponding: `from_var` = headName of `MoveCorrespondingToSendingAreaContext`, `to` likewise. |
| `if` | `condition`: `Ctx.cap(Ctx.ctext(ConditionContext child), 1000)`. `else_pline`: start line of the `IfElseContext` child, or null. |
| `evaluate` | `subjects`: ctext of `EvaluateSelectContext` children of `X` and of each `EvaluateAlsoSelectContext`'s select. `whens`: for each `EvaluateWhenPhraseContext` child (index i): `{"index": i, "pline": start line, "conditions": [for each EvaluateWhenContext child: ctext with a leading "WHEN " removed (regex ^WHEN\s+, case-insensitive)]}`. `has_other`: bool. `other_pline`: start line of `EvaluateWhenOtherContext` or null. |
| `search` | `table`: headName of the direct `QualifiedDataNameContext` child. `all`: true if `X` has token `CobolLexer.ALL`. `whens`: for each `SearchWhenContext` (index i): `{"index": i, "pline", "condition": ctext of its ConditionContext}`. |
| `open` | `modes`: for each child of type `OpenInputStatementContext` → `INPUT`, `OpenOutputStatementContext` → `OUTPUT`, `OpenIOStatementContext` → `I-O`, `OpenExtendStatementContext` → `EXTEND`: `{"mode", "files": [text upper of each FileNameContext inside]}`. |
| `read` | `file`: text of first `FileNameContext` upper. `into`: headName of `ReadIntoContext` or null. |
| `write`, `rewrite` | `record`: headName of the `RecordNameContext`. `from`: headName of `WriteFromPhraseContext` / `RewriteFromContext`, or null. |
| `delete`, `start` | `file`: first `FileNameContext` text upper. |
| `close` | `files`: list of each `CloseFileContext`'s `FileNameContext` text upper. |
| `execCics` | `exec_text`: `Ctx.execText(X, "*>EXECCICS")` |
| `execSql` | `exec_text`: `Ctx.execText(X, "*>EXECSQL")` |
| `execSqlIms` | `exec_text`: `Ctx.execText(X, "*>EXECSQLIMS")` |
| `stop` | `run`: true if `X` has token `CobolLexer.RUN` (direct or in `StopStatementGivingContext`). |
| `exit` | `program`: true if `X` has token `CobolLexer.PROGRAM`. |
| `set` | `to`: headNames of all `SetToContext`; `value`: ctext of the first `SetToValueContext` or `SetByValueContext`, or null. |

### 5.4 Selects

For each `FileControlEntryContext` `F`:

| Field | Value |
|---|---|
| `file` | text of the `FileNameContext` in the `SelectClauseContext`, upper |
| `assign` | `AssignClauseContext`: if it has an `AssignmentNameContext` → its text upper; else if it has a `LiteralContext` → `Ctx.unquote(text)` upper; else `Ctx.lastTokenText` upper (DISK, PRINTER, …) |
| `assign_is_literal` | bool |
| `organization` | ctext of `OrganizationClauseContext` upper with leading `ORGANIZATION ` and `IS ` removed, or null |
| `access` | ctext of `AccessModeClauseContext` upper, keep only the last word, or null |
| `record_key` | headName of the `RecordKeyClauseContext`, or null |
| `file_status` | headName of the first `QualifiedDataNameContext` in `FileStatusClauseContext`, or null |
| `pline` | start line of `F` |

### 5.5 Data items

Walk the first `DataDivisionContext`. For each data section (5.2 `data_sections`), in order, iterate entries:
- FILE section: for each `FileDescriptionEntryContext`, set current `fd` = its file name, then iterate its direct `DataDescriptionEntryContext` children.
- Other sections: iterate the section context's direct `DataDescriptionEntryContext` children. `fd` = null.

For each `DataDescriptionEntryContext` `E`, let `D` = its first child rule context. Skip `DataDescriptionEntryExecSqlContext` (already in `data_exec_sql`). Assign `id` = 1, 2, … across the whole program in order. Fields, in this order:

| Field | Format1 (`DataDescriptionEntryFormat1Context`) | Format3 (88) | Format2 (66) |
|---|---|---|---|
| `id` | int | int | int |
| `level` | `Integer.parseInt(firstTokenText(D))` | 88 | 66 |
| `name` | `DataNameContext` child text upper; else `"FILLER"` if `hasToken(D, CobolLexer.FILLER)`; else null | `ConditionNameContext` text upper | `DataNameContext` text upper |
| `section` | section kind | same | same |
| `fd` | current fd or null | same | same |
| `pic` | `PictureStringContext` (inside `DataPictureClauseContext` child) `.getText()` upper, or null | null | null |
| `usage` | `lastTokenText(DataUsageClauseContext)` upper, or null | null | null |
| `values` | from `DataValueClauseContext` child (see below) or null | same, required | null |
| `occurs` | from `DataOccursClauseContext` (see below) or null | null | null |
| `redefines` | text of `DataNameContext` in `DataRedefinesClauseContext`, upper, or null | null | null |
| `sign` | ctext of `DataSignClauseContext` upper or null | null | null |
| `sync` | bool (has `DataSynchronizedClauseContext`) | false | false |
| `justified` | bool | false | false |
| `blank_when_zero` | bool | false | false |
| `renames` | null | null | ctext of `DataRenamesClauseContext` upper |
| `pline`, `pline_end` | lines of `E` | same | same |

`values`: for each `DataValueIntervalContext` in the clause: `{"from": Ctx.text(DataValueIntervalFromContext), "thru": Ctx.text(LiteralContext inside DataValueIntervalToContext) or null}`. Keep raw text (quotes included).

`occurs`: `{"min": int, "max": int, "depending": headName of the QualifiedDataNameContext in DataOccursDependingContext or null, "indexed_by": [upper text of every IndexNameContext inside the clause]}`. Let `n` = value of the first direct `IntegerLiteralContext` (parse its text as int; if it is an identifier instead, n = 1). If a `DataOccursToContext` exists: `min` = n, `max` = its integer. Else `min` = `max` = n.

---

## 6. Python

General rules for all modules:
- `facts/run_facts.py` adds its own directory to `sys.path` and imports `facts_lib.*`.
- All JSON written with `json.dump(obj, f, indent=1, ensure_ascii=False)` and UTF-8, files opened with `newline="\n"`.
- All text files read with `common.read_text(path)`.
- Names compared upper-case everywhere.

### 6.1 common.py

```python
NAME_RE = r"[A-Z0-9][A-Z0-9-]*"           # COBOL word (upper)

def read_text(path):
    """Read a file as text: try utf-8, on UnicodeDecodeError use latin-1. Returns str."""

def split_lines(text):
    """text.split('\n') after replacing '\r\n' and '\r' by '\n'. Drop one trailing empty element if text ends with newline."""

def source_area(line, fmt):
    """Return (indicator, content) of a source line.
    FIXED:    indicator = line[6] if len(line) > 6 else ' ';  content = line[7:72]
    VARIABLE: indicator = line[6] if len(line) > 6 else ' ';  content = line[7:]
    TANDEM / anything else: indicator = ' ';                    content = line
    Tabs are not expanded."""

def is_comment(indicator, content):
    """True if indicator in '*/' or content.lstrip().startswith('*>')."""

def norm_key(s):
    """Upper case and remove every whitespace character: re.sub(r'\s+', '', s.upper())."""

def est_tokens(chars):
    """Token estimate used everywhere: (chars + 2) // 3."""

def relpath(path, root):
    """Path relative to root with forward slashes if path is inside root, else the absolute path with forward slashes."""

def write_json(path, obj): ...
def load_json(path): ...
```

### 6.2 linemap.py

```python
def build_linemap(pp_lines, program_path, fmt, read_lines=None):
    """
    pp_lines:     list of preprocessed lines (the .pp.cbl split with common.split_lines)
    program_path: absolute path of the program file
    fmt:          'FIXED' / 'VARIABLE' / 'TANDEM'
    read_lines:   optional function(path) -> list of lines (tests inject this); default reads the file
                  with common.read_text + common.split_lines. A path that cannot be read gives [].
    Returns dict:
      'files':  list of {'index', 'path' (absolute, as given), 'name' (upper file name without extension), 'kind'}
                index 0 = program (kind 'program'); copybooks get the next index when first entered
                (kind 'copybook'); the same absolute path always reuses its index.
      'map':    list, one entry per pp line: [file_index, line_number (1-based), exact (bool)]
      'copies': list of copy events (see below), in order of appearance
      'exact_ratio': exact mapped non-blank pp lines / all non-blank pp lines (1.0 if none)
    """
```

Original-line keys (computed once per file):
- For each original line: `(ind, content) = source_area(line, fmt)`. Then: if `ind in "*/"`: `key = "C:" + norm_key(content)`; elif `content.lstrip().startswith("*>")`: `key = "C:" + norm_key(content.lstrip()[2:])`; else `key = norm_key(content)`. Also record `cont[j] = (ind == "-")`.

Preprocessed-line keys:
- `s = line.strip()`.
- If `s.startswith("*> @@CPYENTER ")`, `"*> @@CPYEXIT "`, `"*> @@CPYMISSING "` → marker (handled below).
- elif `s.startswith("*>EXECSQLIMS")`: `key = norm_key(s[len("*>EXECSQLIMS"):].replace("}", ""))`
- elif `s.startswith("*>EXECCICS")`: same with that tag; elif `s.startswith("*>EXECSQL")`: same.
- elif `s.startswith("*>CE")`: `key = norm_key(s[4:])` (comment entry, matches code lines)
- elif `s.startswith("*>")`: `key = "C:" + norm_key(s[2:])`
- else `key = norm_key(s)`
- A key equal to `""` or `"C:"` is **blank**.

Algorithm (segment stack). A segment = `{file_index, keys, cont, p (pointer, 0-based), last (last mapped 1-based line, start 1)}`. Start with the program segment.

```
WINDOW = 400
for i, line in enumerate(pp_lines):
    seg = stack[-1]
    if ENTER marker:
        name, path = text after the tag, split once on '|'
        copy_loc = find_copy(seg, name)            # see below; returns 1-based line or None
        map[i] = [seg.file_index, copy_loc or seg.last, copy_loc is not None]
        push new segment for path (assign/reuse file index)
        copies.append({'name': name, 'path': path, 'file_index': new index, 'parent_file': seg.file_index,
                       'line': copy_loc or seg.last, 'exact': copy_loc is not None, 'enter_pline': i + 1,
                       'exit_pline': None, 'depth': len(stack) - 1 (after push), 'missing': False})
    elif EXIT marker:
        pop the segment; set exit_pline = i + 1 on the most recent copy event with that file_index and exit_pline None
        parent = stack[-1]; map[i] = [parent.file_index, parent.last, False]
    elif MISSING marker:
        name = text after the tag
        copy_loc = find_copy(seg, name)
        map[i] = [seg.file_index, copy_loc or seg.last, copy_loc is not None]
        copies.append({... same keys ..., 'path': None, 'file_index': None, 'enter_pline': i + 1,
                       'exit_pline': i + 1, 'depth': len(stack), 'missing': True})
    elif key is blank:
        if seg.p < len(seg.keys) and seg.keys[seg.p] in ('', 'C:'):
            map[i] = [seg.file_index, seg.p + 1, True]; seg.last = seg.p + 1; seg.p += 1
        else:
            map[i] = [seg.file_index, seg.last, False]
    else:
        j = first index in range(seg.p, min(seg.p + WINDOW, len(seg.keys))) where match(key, seg.keys[j])
        if found:
            map[i] = [seg.file_index, j + 1, True]; seg.last = j + 1; seg.p = j + 1
            while seg.p < len(seg.keys) and seg.cont[seg.p]: seg.p += 1      # skip merged continuation lines
        else:
            map[i] = [seg.file_index, seg.last, False]

match(k, o): o not blank and (k == o or (len(o) >= 4 and k.startswith(o)) or (len(k) >= 4 and o.startswith(k)))

find_copy(seg, name):
    target = 'COPY' + norm_key(name)
    for j in range(seg.p, min(seg.p + WINDOW, len(seg.keys))):
        if not seg.keys[j].startswith('C:') and target in seg.keys[j]:
            # consume the COPY statement up to the line containing '.'
            k = j
            while k < len(seg.keys) - 1 and '.' not in seg.keys[k]: k += 1
            seg.p = k + 1; seg.last = j + 1
            return j + 1
    return None
```

Also export:

```python
def loc(lm, pline):
    """[file_index, line] for a 1-based pline; [0, 0] if pline is None, < 1 or > len(map)."""
def is_exact(lm, pline): ...
```

For text-scan raw facts (parser `"text"`) use instead:

```python
def identity_linemap(program_path, n_lines):
    """files = [program]; map[i] = [0, i + 1, True]; copies = []; exact_ratio = 1.0"""
```

### 6.3 cics.py

```python
def parse(exec_text):
    """
    Returns {'command': 'XCTL', 'options': OrderedDict, 'raw': exec_text}
    option values are dicts:
      {'flag': True}                                  option without argument (UPDATE, NOHANDLE, ERASE ...)
      {'literal': 'COSGN00C'}                         quoted argument, unquoted (doubled quotes collapsed)
      {'number': '80'}                                argument that is all digits
      {'var': 'WS-PGMNAME', 'text': 'WS-PGMNAME(1)'}  anything else; var = first COBOL word of the argument, upper
                                                      ('LENGTH OF X' -> var 'X')
    """
```

Algorithm:
1. `t = exec_text.strip()`. Remove a leading `EXEC\s+CICS\b` and a trailing `END-EXEC\s*\.?\s*$` (case-insensitive regexes). Strip.
2. Scan left to right. Skip whitespace and commas. Read a word `[A-Za-z0-9-]+` (upper it). Skip whitespace. If the next char is `(`, read a balanced argument: depth counting over `(`/`)`, ignoring parentheses inside `'...'` or `"..."` literals. The argument is the text between the outer parentheses, stripped. Otherwise the word has no argument. Any other character: skip it.
3. The first word is the command. If it has no argument and it is in `TWO_WORD` and the second word has no argument and is in `TWO_WORD[first]`, the command is `first + " " + second`. Special case: for `INQUIRE` and `SET`, always join the second word if it has no argument.
   ```python
   TWO_WORD = {'SEND': {'MAP', 'TEXT', 'CONTROL', 'PAGE'}, 'RECEIVE': {'MAP'},
               'WRITEQ': {'TS', 'TD'}, 'READQ': {'TS', 'TD'}, 'DELETEQ': {'TS', 'TD'},
               'HANDLE': {'ABEND', 'AID', 'CONDITION'}, 'IGNORE': {'CONDITION'},
               'GET': {'CONTAINER'}, 'PUT': {'CONTAINER'}, 'DELETE': {'CONTAINER'}}
   ```
   If the first word itself has an argument (rare), the command is the word and its argument is stored as option `_ARG`.
4. Remaining words become options in order. If an option name repeats, keep the first.
5. Argument classification: starts with `'` or `"` → `literal` (strip outer quotes, collapse doubled quotes); all digits → `number`; starts with `LENGTH OF ` (case-insensitive) → `var` of the word after it; else `var` = first match of `[A-Za-z0-9][A-Za-z0-9-]*` upper, `text` = argument.

```python
def interpret(parsed):
    """
    Turns a parsed command into facts. Returns dict with lists:
      'transfers':      [{'kind', 'target', 'commarea', 'length'}]
      'resources':      [{'kind', 'name', 'op', 'command', 'mapset', 'extra'}]
      'error_handling': [{'kind', 'detail'}]
      'labels':         [paragraph names that become reachability seeds]
      'reads', 'writes': variable names
    'target' / 'name' / 'mapset' are option value dicts as returned by parse(), or None.
    """
```

Rules (command → output):

| Command | Output |
|---|---|
| `XCTL`, `LINK` | transfer kind = command, target = `PROGRAM`, commarea = var of `COMMAREA` or None, length = text/number of `LENGTH` or None |
| `RETURN` with `TRANSID` | transfer `RETURN_TRANSID`, target = `TRANSID`, commarea as above |
| `RETURN` without `TRANSID` | transfer `RETURN`, target None |
| `START` | transfer `START_TRANSID`, target = `TRANSID` |
| `READ` | resource `cics_file`, name = `FILE` or `DATASET`, op = `read_update` if `UPDATE` flag else `read`, extra = `{'ridfld': var or None}` |
| `READNEXT`, `READPREV`, `STARTBR`, `RESETBR`, `ENDBR` | resource `cics_file`, op `browse` |
| `WRITE` | resource `cics_file`, op `write` |
| `REWRITE` | resource `cics_file`, op `update` |
| `DELETE` | resource `cics_file`, op `delete` |
| `UNLOCK` | resource `cics_file`, op `unlock` |
| `SEND MAP` / `RECEIVE MAP` | resource `map`, name = `MAP`, mapset = `MAPSET` or (if absent) same as `MAP`, op `send` / `receive` |
| `SEND TEXT`, `SEND CONTROL`, `SEND PAGE` | resource `terminal`, name None, op `send_text` / `send_control` / `send_page` |
| `WRITEQ TS`, `READQ TS`, `DELETEQ TS` | resource `ts_queue`, name = `QUEUE` or `QNAME`, op `write` / `read` / `delete` |
| `WRITEQ TD`, `READQ TD`, `DELETEQ TD` | resource `td_queue`, name = `QUEUE`, op likewise |
| `HANDLE ABEND` | error `HANDLE_ABEND`, detail = `PROGRAM` or `LABEL` text; if `PROGRAM`: transfer `HANDLE_ABEND` target = `PROGRAM`; if `LABEL`: label added |
| `HANDLE CONDITION` | error `HANDLE_CONDITION`, detail = `"COND(LABEL), ..."`; every option value that is a var is a label |
| `HANDLE AID` | error `HANDLE_AID`, detail = option names; var values are labels |
| `ABEND` | error `ABEND`, detail = `ABCODE` value text |
| any command with option `RESP` | additionally error `RESP_CHECK`, detail = `command + " RESP(" + var + ")"` |
| `GET CONTAINER`, `PUT CONTAINER` | resource `container`, name = `CONTAINER`, op `get` / `put`, extra = `{'channel': CHANNEL}` |
| everything else | nothing (only reads/writes) |

reads/writes: vars of options `INTO`, `SET`, `RESP`, `RESP2` → writes. Vars of all other options (except `PROGRAM`, `TRANSID`, `FILE`, `DATASET`, `MAP`, `MAPSET`, `QUEUE`, `QNAME`, `LABEL`) → reads. Label options are not data.

### 6.4 sql.py

```python
def parse(exec_text):
    """
    Returns {'kind', 'tables': [{'name', 'op'}], 'cursor', 'include', 'host_reads', 'host_writes', 'raw'}
    kind: one of include, declare_cursor, declare_table, select, insert, update, delete, open, fetch,
          close, whenever, commit, rollback, other
    """
```

Algorithm:
1. `t` = exec_text; remove leading `EXEC\s+SQL\b` and trailing `END-EXEC\s*\.?\s*$` (case-insensitive); collapse whitespace; upper; strip. Let `m` = `t` with every `'...'` literal replaced by `''` (for keyword searching).
2. kind by the start of `m`:
   - `INCLUDE x` → include = x (strip quotes)
   - `DECLARE c CURSOR` → cursor = c, kind `declare_cursor`; tables from the SELECT part (op `read`)
   - `DECLARE t TABLE` → kind `declare_table`, tables `[{t, 'declare'}]`
   - `SELECT` → `select`, tables from FROM (op `read`)
   - `INSERT INTO t` → `insert`, table t op `insert`, plus FROM tables of a subselect op `read`
   - `UPDATE t` → `update`, t op `update`, plus FROM tables op `read`
   - `DELETE FROM t` → `delete`, t op `delete`, plus other FROM tables op `read`
   - `OPEN c` / `FETCH [NEXT FROM|FROM] c` / `CLOSE c` → kind, cursor = c
   - `WHENEVER` / `COMMIT` / `ROLLBACK` → that kind
   - else `other`
3. FROM tables: for each match of `\bFROM\s+(.+?)(?=\s+(?:WHERE|GROUP|ORDER|HAVING|UNION|FETCH|FOR|WITH|EXCEPT|INTERSECT|INTO)\b|\)|$)` in `m`: split the captured text on `,` and on `\b(?:INNER\s+|LEFT\s+(?:OUTER\s+)?|RIGHT\s+(?:OUTER\s+)?|FULL\s+(?:OUTER\s+)?|CROSS\s+)?JOIN\b`; for each part take the first token matching `[A-Z0-9_#@$.]+`; skip parts starting with `(` or `:`; also skip a part right after `ON` (the join condition: strip everything from `\bON\b` before taking the token). Also add every `\bJOIN\s+([A-Z0-9_#@$.]+)`.
4. De-duplicate tables by (name, op), keep order.
5. Host variables: every `:([A-Z0-9][A-Z0-9-]*)` in `t`. Writes: host vars between `\bINTO\b` and the next `\bFROM\b` (or end) for kind `select` and `fetch`. All others are reads.

### 6.5 layout.py

```python
def build_items(raw_items):
    """
    raw_items: data_items from raw facts (5.5), in order.
    Returns a list of item dicts (copies) with added keys:
      parent (id or None), record (id of its 01/77), children (ids), conditions (88 child names),
      effective_usage, size, occurs_count, total_size, offset, is_group, size_unknown
    """
```

Hierarchy (one pass with a stack of open items):
- Level 01 or 77: record root. Clear the stack, push it. parent = None, record = own id.
- Level 66: parent = None, record = record of the previous item; do not push.
- Level 88: parent = the most recent non-88/non-66 item; append its name to parent's `conditions`; do not push.
- Other levels (2–49): pop while `stack[-1].level >= level`; parent = `stack[-1]` if stack else None; record = parent's record (own id if no parent); push.
- Children lists are in order. `is_group` = has children with level not 66/88.

Effective usage: own `usage` if set, else nearest ancestor's `usage`, else `DISPLAY`. Normalize: `COMPUTATIONAL` → `COMP`, `COMPUTATIONAL-n` → `COMP-n`, `BINARY` / `COMP-4` → `COMP`, `PACKED-DECIMAL` → `COMP-3`.

Elementary size (`pic_size(pic, usage, sign)`):
1. Expand repeats: replace every `(.)\((\d+)\)` with the char repeated n times.
2. `digits` = count of `9`. `chars` = length after removing `S`, `V`, `P` (keep `CR`/`DB` as 2 chars).
3. By effective usage:
   - `DISPLAY`: `chars` + 1 if `sign` contains `SEPARATE`
   - `COMP`, `COMP-5`: digits 1–4 → 2, 5–9 → 4, 10–18 → 8, else 8
   - `COMP-3`: `digits // 2 + 1`
   - `COMP-1` → 4, `COMP-2` → 8, `INDEX` / `POINTER` / `PROCEDURE-POINTER` / `FUNCTION-POINTER` → 4
   - `NATIONAL`: `chars * 2`
   - other: `chars`
4. No pic: `COMP-1` 4, `COMP-2` 8, `INDEX`/`POINTER` 4; else size 0 and `size_unknown` = True.

Group size = sum of `total_size` of children that have no `redefines` (levels 66/88 excluded). `occurs_count` = occurs.max if occurs else 1. `total_size` = size × occurs_count. Level 88/66 items: size 0, total_size 0, offset = parent's offset (88) or None (66).

Offsets (relative to the record start): record root offset 0. Walking each parent's children in order with a running cursor starting at the parent's offset: a child with `redefines` gets the offset of the earlier sibling with that name (if not found: cursor) and does not advance the cursor; any other child gets `cursor`, then `cursor += total_size`. A level-01 item with `redefines` keeps offset 0 (record coordinates of its own record) and gets `redefines_id` = id of the redefined 01.

Every item gets `redefines_id` = id of the redefined item (same parent, or another 01 for level 01), or None.

```python
def literal_value(text):
    """Classify a raw VALUE literal. Returns {'kind', 'value'}:
      'string':     quoted literal (also X'..' -> kind 'hex', value the hex digits; ALL 'x' -> kind 'all', value x)
      'number':     matches ^[+-]?\d*\.?\d+$  (value = the text)
      'figurative': SPACE(S), ZERO(S|ES), LOW-VALUE(S), HIGH-VALUE(S), QUOTE(S), NULL(S) (value = singular upper form: SPACE, ZERO, LOW-VALUE, HIGH-VALUE, QUOTE, NULL)
      'other':      anything else (value = text upper)"""

def record_image(items, record_id):
    """Initial value image of one record: a list of length = record total_size with one character or None per byte.
    For every elementary item of the record (not 88/66) that has values, is not inside an OCCURS (neither it nor an
    ancestor has occurs), and has offset and size: write its first value:
      string -> content padded with spaces / truncated to size
      number -> for DISPLAY usage: digits of abs value (no sign, no decimal point), zero-padded left to size; other usages: skip
      figurative SPACE -> ' ' * size, ZERO -> '0' * size, LOW-VALUE -> '\x00' * size, HIGH-VALUE -> '\xff' * size
      other kinds -> skip
    Groups with a string/figurative value are written the same way over their total_size, before their children.
    Items are applied in id order, so later items overwrite earlier ones."""

def occurrence_values(items, item_id):
    """All initial values of an item inside an OCCURS table, read from record_image of its record.
    Let O be the nearest item (itself or ancestor) with occurs. stride = O.size; count = O.occurs.max.
    For k in range(count): bytes [item.offset + k*stride, item.offset + k*stride + item.size).
    Skip an occurrence if any byte is None. Return the list of strings (rstripped)."""
```

### 6.6 dynamic.py

```python
PROGRAM_RE = r"^[A-Z0-9@#$][A-Z0-9@#$-]{0,7}$"
TRANSID_RE = r"^[A-Z0-9@#$]{1,4}$"

def resolve(var, kind, ctx):
    """
    var:  upper-case data name used as target (head name)
    kind: 'program', 'transid', 'name' (file / map / mapset / queue)
    ctx:  {'items': list from layout.build_items, 'by_name': name -> [items], 'statements': raw statements}
    Returns a list of {'value', 'how'} in discovery order, de-duplicated by value (first 'how' kept).
    """
```

Steps, collecting candidates:
1. `value_clause`: for every item named `var` (level not 88) with values: each value whose `literal_value` kind is `string` → its value stripped.
2. `move_literal`: every `move` statement with `var` in `to` and `from_literal` not None: `literal_value(from_literal)` of kind `string` → value stripped.
3. `set_condition`: every `set` statement whose `to` contains an 88 name whose parent item is named `var` and whose `value` text upper is `TRUE`: that 88's values of kind `string`.
4. `value_table`: for every item named `var` that is inside an OCCURS: `layout.occurrence_values(items, item.id)`, each stripped.
5. `move_var`: every `move` statement with `var` in `to` and `from_var` not None: recursively `resolve(from_var, kind, ctx)` with depth + 1; max depth 3; keep a visited set of var names to stop cycles. Results get `how` = `"move_var:" + from_var`.

Filter: value upper; drop empty; keep only values matching `PROGRAM_RE` (kinds `program`, `name`) or `TRANSID_RE` (kind `transid`).

```python
def resolve_option(opt, kind, ctx):
    """opt: option dict from cics.parse or None.
    literal -> [{'value': literal upper stripped, 'how': 'literal'}] (filtered by the kind regex);
    var -> resolve(var, kind, ctx); None/flag/number -> []."""
```

### 6.7 flow.py

```python
OUTLINE_TYPES = {'perform', 'goTo', 'call', 'execCics', 'execSql', 'execSqlIms', 'if', 'evaluate',
                 'search', 'read', 'write', 'rewrite', 'delete', 'start', 'open', 'close',
                 'goback', 'stop', 'exit'}
```

Functions (each takes the raw statements/paragraphs/sections lists plus the linemap; all names upper):

1. `guards(stmt, by_id)` → list of strings, outermost first, each capped at 200 chars. Walk from `stmt.parent` upward; for each ancestor `A` with the branch `b` that leads to the child:
   - `then` → `A.condition`; `else` → `"NOT (" + A.condition + ")"`
   - `when:i` on evaluate → let `S` = A.subjects, `C` = A.whens[i].conditions: if `len(S) == 1` and `S[0].upper() == "TRUE"` → `" OR ".join(C)`; else `" ALSO ".join(S) + " = " + " OR ".join(C)`
   - `other` → `" ALSO ".join(S) + " = OTHER"`
   - `when:i` on search → `A.whens[i].condition`
   - `inline` → `"LOOP UNTIL " + A.until` if `A.until` else `"LOOP"`
   - anything else → `A.type.upper() + " " + PHRASES.get(b, b)` with `PHRASES = {'atEndPhrase': 'AT END', 'notAtEndPhrase': 'NOT AT END', 'invalidKeyPhrase': 'INVALID KEY', 'notInvalidKeyPhrase': 'NOT INVALID KEY', 'onSizeErrorPhrase': 'ON SIZE ERROR', 'notOnSizeErrorPhrase': 'NOT ON SIZE ERROR', 'onExceptionClause': 'ON EXCEPTION', 'notOnExceptionClause': 'NOT ON EXCEPTION', 'onOverflowPhrase': 'ON OVERFLOW', 'notOnOverflowPhrase': 'NOT ON OVERFLOW'}`
   Then reverse the list.
2. `depth(stmt, by_id)` → number of ancestors.
3. `resolve_targets(name, thru, paragraphs, sections)` → list of paragraph names: if `name` is a paragraph name (first match in order): from its index to the index of `thru` (inclusive; if `thru` is None or not found, just itself); elif `name` is a section name: all paragraphs of that section, and if `thru` is a section, all paragraphs of the sections from `name` to `thru` in order; else `[]` (record as unresolved perform target).
4. `terminates(par, statements)` → True if the last statement of the paragraph with `parent is None` (highest `pline`, then highest id) is: `goback`; `stop` with `run`; `exit` with `program`; `goTo` with `depending` None and exactly one target; `execCics` whose `cics.parse(exec_text)['command']` is `RETURN` or `XCTL`.
5. `reachability(paragraphs, sections, statements, labels)` → set of reachable paragraph names. States `(name, mode)` with mode `flow` or `performed`. Seeds: first non-declaratives paragraph in `flow` mode; all declaratives paragraphs in `flow` mode; every name in `labels` (from CICS HANDLE) in `flow` mode. BFS:
   - For paragraph `p` in any mode: for each `perform` statement with `paragraph == p` and a `target`: each of `resolve_targets(target, thru)` → `(t, performed)`. For each `goTo`: each target's `resolve_targets(t, None)` → `(t, flow)`.
   - Only in `flow` mode: if not `terminates(p)` and `p` is not the last paragraph → `(next paragraph, flow)`.
   - Statements with `paragraph` None (before the first paragraph) belong to a pseudo paragraph that is always reached first: apply their performs/gotos as from a `flow` paragraph, and if none of those statements is a terminator at top level, the first paragraph is reached in flow mode (it is a seed anyway).
6. `complexity(par_statements)` = 1 + number of `if` + total number of `whens` of `evaluate` statements + number of `search` whens + number of `perform` with `perform_type` in (`until`, `varying`) + number of `\b(AND|OR)\b` matches in all `if.condition`, evaluate when conditions and search when conditions.
7. `outline(par_statements, by_id, lm)` → list (max 200 entries, then append `{'type': 'truncated'}`) of `{'type', 'depth', 'loc', 'summary'}` for statements whose type is in `OUTLINE_TYPES`, in pline order. Additionally for every `evaluate` add one entry per when: `{'type': 'when', 'depth': depth + 1, 'loc': loc(when.pline), 'summary': 'WHEN ' + ' OR '.join(conditions)}` and for `has_other` one `WHEN OTHER` entry at `other_pline`; for every `if` with `else_pline` add `{'type': 'else', 'depth': depth, 'loc': loc(else_pline), 'summary': 'ELSE'}`. Sort all entries by `(pline, order of creation)`. Summaries (cap 160 chars):
   - perform: `PERFORM X THRU Y UNTIL cond` (omit missing parts; inline: `PERFORM (inline)` + ` UNTIL cond` / ` VARYING` / ` TIMES`)
   - if: `IF ` + condition; evaluate: `EVALUATE ` + `" ALSO ".join(subjects)`; search: `SEARCH ` + table
   - call: `CALL ` + target_text; goTo: `GO TO ` + `", ".join(targets)`
   - execCics: `EXEC CICS ` + command + for the first present of `PROGRAM, TRANSID, FILE, DATASET, MAP, QUEUE, QNAME`: ` NAME(value)` where value is literal or var text
   - execSql / execSqlIms: `EXEC SQL ` + first 100 chars of exec_text after removing the `EXEC SQL` prefix
   - read/delete/start: `TYPE file`; write/rewrite: `TYPE record`; open: `OPEN MODE files ...`; close: `CLOSE files`
   - goback: `GOBACK`; stop: `STOP RUN` or `STOP`; exit: `EXIT PROGRAM` or `EXIT`

### 6.8 build.py

```python
def build(raw, pp_lines, ctx):
    """
    raw:      raw facts dict (proleap or text)
    pp_lines: preprocessed lines (proleap) or original lines (text)
    ctx:      {'codebase_root', 'inventory_record' (the inventory.json file record), 'copybook_index' (upper name -> list of relative paths, from inventory types copybook and dclgen)}
    Returns the final facts dict (section 7).
    """
```

Steps, in this order (each step fills the section 7 keys named in brackets):

1. **Line map.** proleap → `linemap.build_linemap(pp_lines, raw['program_file'], raw['format'])`; text → `linemap.identity_linemap(...)`. Convert `files` paths with `common.relpath(path, codebase_root)`. Define `L(pline)` = `linemap.loc`. [`files`, `quality.line_map_exact_ratio`]
2. **Copybooks.** proleap: from `copies`. text: from `raw['copy_events_direct']` (already final-shaped, section 6.9). For each event: `region` = the region containing `enter_pline` (data section kind lower-cased: `file`, `working-storage`, `local-storage`, `linkage`, `other`; `procedure` if inside `divisions.procedure`; `environment` / `identification` likewise; else `unknown`). `via` = name of the enclosing copy event (the latest earlier event with `enter_pline < this.enter_pline <= exit_pline`), else None. [`copybooks`]
3. **Data items.** `layout.build_items(raw['data_items'])`; for each item add `loc` = `L(pline)` and `file_index` = loc[0]. Build `by_name`. [`data_items`]
4. **SQL includes.** For each `data_exec_sql` and each `execSql` statement: `sql.parse`; kind `include` → `{'name', 'loc'}`. [`sql_includes`]
5. **Exec parsing.** For each `execCics` statement: `p = cics.parse(exec_text)`, `r = cics.interpret(p)`; add `r.reads`/`r.writes` to the statement's lists; collect `r.labels`. For each `execSql`: `sql.parse`; add `host_reads`/`host_writes`.
6. **Flow.** Paragraph records with `start`/`end` = `L(start)`/`L(end)`, statements per paragraph, `statements` count, `complexity`, `reachable`, `reads`/`writes` (sorted union), `performs` (sorted unique perform targets resolved to paragraph names via `resolve_targets`), `performed_by` (inverse), `outline`, `est_tokens` (see below), `transfers` and `resources` (ids, filled after step 7). `est_tokens`: if `start[0] == end[0] == 0`: sum of `len(content.rstrip())` of `source_area(line, fmt)[1]` over original lines `start[1]..end[1]`; else sum of `len(pp_lines[k].strip())` over plines start..end; then `common.est_tokens`. Sections likewise (`name`, `start`, `end`, `declaratives`, `paragraphs`). [`procedure`, `dead_paragraphs`]
7. **Transfers, resources, errors** (ids `T1..`, `R1..`, `E1..` in statement order). Every entry gets `paragraph`, `loc` = `L(stmt.pline)`, `guards` = `flow.guards`, `stmt_id`, `source` = raw parser (`proleap` or `text`).
   - `call` with `target_literal` in `DLI_CALLS = {'CBLTDLI', 'AIBTDLI', 'CEETDLI'}` → resource `ims_call`: `name` = None, `op` = resolved function (dynamic.resolve of `using[0].name`, kind `name`, first value, else `using[0].text`), `extra` = `{'pcb': using[1].text if present, 'io_area': using[2].text if present}`.
   - `call` with `target_literal` in `MQ_CALLS = {'MQCONN','MQCONNX','MQOPEN','MQPUT','MQPUT1','MQGET','MQCLOSE','MQDISC','MQINQ','MQSET','MQBEGIN','MQCMIT','MQBACK'}` → resource `mq_call`, `op` = target lower, `extra` = `{'object': using[1].text if present}`.
   - Any other `call` → transfer `CALL`: `target` = `{'literal': X}` or `{'var': V, 'text': target_text}`; `resolved_targets` = `[{'value': X, 'how': 'literal'}]` or `dynamic.resolve(V, 'program', ...)`; `using` = list of using texts. If `target_literal` in `ABEND_CALLS = {'CEE3ABD', 'ILBOABN0', 'CEE3AB2'}` also error `ABEND` with detail `'CALL ' + X`.
   - `execCics` → each `r.transfers` entry: `target`, `resolved_targets` via `dynamic.resolve_option(target, 'transid' if kind in ('RETURN_TRANSID', 'START_TRANSID') else 'program')`, `commarea`, `length`; each `r.resources` entry: `name`, `name_resolved` = `resolve_option(name, 'name')`, `mapset`, `mapset_resolved`, `op`, `command`, `extra`; each `r.error_handling` entry.
   - `execSql` → for each table: resource `db2_table` with `name` = `{'literal': table}`, `name_resolved` = `[{'value': table, 'how': 'literal'}]`, `op`, `command` = kind, `extra` = `{'cursor': cursor}`. kind `whenever` → error `SQL_WHENEVER` with detail = text.
   - `execSqlIms` → resource `ims_call`, `op` = first word of the text after `EXEC SQLIMS`, extra `{'text': exec_text}`.
   - `EXEC DLI` blocks from `textscan.scan_exec_dli(original program lines, fmt)` (always, for both parsers): resource `ims_call`, `op` = command (`GU`, `GN`, `GNP`, `GHU`, `GHN`, `GHNP`, `ISRT`, `REPL`, `DLET`, `SCHD`, `TERM`, `CHKP`, `ROLB`, …, the first word), `extra` = `{'segment': SEGMENT value text, 'pcb': PCB value text}` (use `cics.parse` on the block text with the `EXEC DLI` prefix removed by replacing `DLI` with `CICS` before parsing), `loc` = `[0, line]`, `paragraph` = the paragraph whose start/end in file 0 contains the line, else None, `guards` = [].
   - Terminators: `goback` → transfer `GOBACK`; `stop` with run → `STOP_RUN`; `exit` with program → `EXIT_PROGRAM`. Target None, resolved_targets [].
   - Every transfer/resource gets `unresolved` = True if it has a var target/name and the resolved list is empty, else False.
8. **Batch files** [`files_io`]: one entry per select: `select`, `dd` = assign with a leading `UT-S-`, `UR-S-`, `DA-S-`, `S-` or `AS-` removed, `assign_is_literal`, `organization`, `access`, `record_key`, `file_status`, `records` = names of level-01 items with `fd == select.file`, `open_modes` (sorted unique modes from `open` statements naming this file), `ops` (sorted unique: `READ`/`START`/`DELETE` statements whose `file` is this select; `WRITE`/`REWRITE` statements whose `record` is one of `records`), `access_summary`: modes INPUT → read, OUTPUT/EXTEND → write, I-O → read_write; ops READ/START → read, WRITE → write, REWRITE/DELETE → read_write; combine: only read → `read`, only write → `write`, anything else non-empty → `read_write`, nothing → `unknown`. Also add a resource `batch_file` per select: `name` = `{'literal': dd}`, `name_resolved` = `[{'value': dd, 'how': 'literal'}]`, `op` = access_summary, `paragraph` None, `loc` = `L(select.pline)`, `guards` [].
9. **Decisions** (`D1..` in statement order) for `if`, `evaluate`, `search` [`decisions`]: `id`, `kind`, `paragraph`, `loc`, `end` = `L(pline_end)`, `depth`, `stmt_id`, and `condition` (if) or `subjects` + `whens` (`[{'loc', 'conditions'}]`) + `has_other` (evaluate) or `table` + `whens` (`[{'loc', 'condition'}]`) (search).
10. **More error handling**: for each decision: if any condition text references (as a whole word) a `file_status` variable of a select, or a level-88 child of one → error `FILE_STATUS_CHECK` with detail = condition (cap 200). If it references `SQLCODE` or `SQLSTATE` → `SQLCODE_CHECK`. If it references `EIBRESP` or a variable that appears as `RESP` in any exec cics → `RESP_EVAL`. [`error_handling`]
11. **Unresolved names** [`unresolved_names`]: all names from statement reads/writes, minus: data item names (all levels incl. 88/66), select file names, fd names, `indexed_by` names, paragraph and section names, `SPECIAL_REGISTERS = {'RETURN-CODE','SORT-RETURN','SORT-CONTROL','TALLY','WHEN-COMPILED','LENGTH','ADDRESS','DEBUG-ITEM','LINAGE-COUNTER','SHIFT-OUT','SHIFT-IN','XML-CODE','JNIENVPTR'}`, names starting with `EIB`, `DFH`, `SQL`. Each: `{'name', 'count', 'first_loc'}` sorted by name.
12. **Usage** [`unused_data`, `write_only_data`]: referenced = union of statement reads and writes plus all var names found in transfers (commarea), resources (ridfld), procedure_using, select record_key and file_status, occurs depending. An item is used if its name, or the name of an ancestor, a descendant or one of its 88 conditions is referenced. `unused_data` = names of items with `file_index == 0`, level not 88/66, name not FILLER/None, not used; max 500. `write_only_data` = names of such items (file 0) that are in some writes, in no reads (direct name), and no ancestor/descendant/88 name is in reads; max 500.
13. **Interface** [`interface`]: `procedure_using`; `linkage_records` = names of level-01 items with section `LINKAGE`; `commarea` = `{'name': 'DFHCOMMAREA', 'size': its total_size}` if a linkage 01 named DFHCOMMAREA exists, else None; `linkage_layout` = for each linkage record, its items as `{'name', 'level', 'offset', 'size', 'pic', 'usage'}` (max 300 per record).
14. **Kind & flags** [`kind`, `flags`]: `uses_cics` = any execCics; `uses_db2` = any execSql statement in the procedure division, or any data_exec_sql whose kind is not `include`; `uses_ims` = any ims_call resource; `uses_mq` = any mq_call resource; `uses_files` = any select or any cics_file resource. `kind`: `cics_online` if uses_cics; elif `procedure_using` non-empty → `batch_subroutine`; else `batch_main`.
15. **Metrics** [`metrics`]: `lines` = original program line count; `code_lines`, `comment_lines`, `blank_lines` (by `source_area`/`is_comment`); `statements`; `paragraphs`; `complexity` (sum); `est_tokens_program` = est_tokens over all original lines' content; `est_tokens_expanded` = est_tokens over `sum(len(l.strip()) for l in pp_lines)`; `cics_commands` = dict command → count; `statement_types` = dict type → count.
16. **Quality** [`quality`]: `status`, `parser`, `syntax_error_count`, `syntax_error_samples` (first 20 as `{'loc': L(pline), 'msg'}`), `line_map_exact_ratio`, `missing_copybooks`, `fallback_reason` (set by run_facts), `parse_ms`.

### 6.9 textscan.py

```python
def scan(path, fmt, name, copybook_index):
    """Text-only scanner. Returns a raw facts dict with the schema of section 5 (parser 'text'), plus
    'copy_events_direct'. Line numbers are original line numbers (pline == line)."""

def scan_exec_dli(lines, fmt):
    """Returns [{'line': first line (1-based), 'text': joined content from EXEC DLI to END-EXEC}] for every
    EXEC DLI block in non-comment code (content area only)."""
```

`scan` rules (apply regexes to the upper-cased content area of non-comment lines; `masked` = content with the inside of every `'...'` / `"..."` literal replaced by `x` of the same length):
- Header fields as in 5.1: `parser` `"text"`, `status` `"ok"`, `error` None, `syntax_error_count` 0, `syntax_errors` [], `missing_copybooks` = names of direct COPYs not in `copybook_index`, `preprocessed_file` None, `parse_ms` measured.
- Divisions: lines matching `^\s*(IDENTIFICATION|ID|ENVIRONMENT|DATA|PROCEDURE)\s+DIVISION\b` (on masked). Each division ends at the line before the next division or at the last line.
- `program_ids`: `PROGRAM-ID\.?\s+['"]?([A-Z0-9#@$-]+)`.
- `data_sections`: `^\s*(FILE|WORKING-STORAGE|LOCAL-STORAGE|LINKAGE)\s+SECTION\s*\.` within the data division.
- `procedure_using`: on the PROCEDURE DIVISION line plus following lines until a `.`: words after `USING`, excluding `BY`, `REFERENCE`, `VALUE`, `CONTENT`.
- Data entries (data division): accumulate content across lines until a `.` that is outside a literal and followed by whitespace or end of line. Entry start line = first line. Parse each entry: `^\s*(\d{1,2})\s+(.*)$`. The first word of the rest is the name if it is not a clause keyword (`PIC`, `PICTURE`, `VALUE`, `VALUES`, `OCCURS`, `REDEFINES`, `USAGE`, `COMP*`, `BINARY`, `PACKED-DECIMAL`, `DISPLAY`, `SIGN`, `SYNC*`, `JUST*`, `BLANK`, `INDEXED`) — `FILLER` stays `FILLER`. Clauses (on the masked entry; extract literal text from the original at the same span): `\bPIC(?:TURE)?\s+(?:IS\s+)?(\S+)` (strip a trailing `.`), usage `\b(COMP(?:UTATIONAL)?(?:-[1-5])?|BINARY|PACKED-DECIMAL|INDEX|POINTER)\b`, `\bREDEFINES\s+([A-Z0-9-]+)`, `\bOCCURS\s+(\d+)(?:\s+TO\s+(\d+))?`, `DEPENDING\s+ON\s+([A-Z0-9-]+)`, `INDEXED\s+BY\s+([A-Z0-9-]+(?:\s+[A-Z0-9-]+)*)`, values: after `\bVALUES?\s+(?:IS\s+|ARE\s+)?` take repeated literals `('(?:[^']|'')*'|"(?:[^"]|"")*"|[^\s.,]+(?:\.\d+)?)` each optionally followed by `\s+(?:THRU|THROUGH)\s+<literal>`, separated by spaces or commas, stopping at a clause keyword. Lines `^\s*(FD|SD)\s+([A-Z0-9-]+)` set the current fd (and are added to `fds`). `EXEC SQL ... END-EXEC` inside the data division → `data_exec_sql`. All other raw item fields as in 5.5 (`sign` None, `sync`/`justified`/`blank_when_zero` False, `renames` None).
- `selects` (environment division): accumulate from `SELECT` to the next `.`; `SELECT\s+(?:OPTIONAL\s+)?([A-Z0-9-]+)\s+ASSIGN\s+(?:TO\s+)?([A-Z0-9-]+|'[^']*'|"[^"]*")`; organization `ORGANIZATION\s+(?:IS\s+)?((?:LINE\s+)?\w+)`; access `ACCESS\s+(?:MODE\s+)?(?:IS\s+)?(\w+)`; `RECORD\s+KEY\s+(?:IS\s+)?([A-Z0-9-]+)`; `(?:FILE\s+)?STATUS\s+(?:IS\s+)?([A-Z0-9-]+)`.
- Procedure division: section header `^([A-Z0-9][A-Z0-9-]*)\s+SECTION\s*\.` and paragraph header `^([A-Z0-9][A-Z0-9-]*)\s*\.\s*$`, both only when the content starts in column 8 (content[0] != ' '). A paragraph/section ends at the line before the next header or at the last code line. `declaratives` False.
- Statements (procedure division, one per match, `parent` None, `branch` None, `reads`/`writes` [] unless stated, `section`/`paragraph` from the current header, `pline` = `pline_end` = line except EXEC):
  - EXEC block: from a line with `\bEXEC\s+(CICS|SQL)\b` to the line containing `END-EXEC`; type `execCics`/`execSql`, `exec_text` = joined content stripped, `pline` first line, `pline_end` last line. Lines inside an EXEC block are not scanned for other statements.
  - `\bPERFORM\s+([A-Z0-9][A-Z0-9-]*)(?:\s+(?:THRU|THROUGH)\s+([A-Z0-9-]+))?` — if group 1 in (`UNTIL`, `VARYING`, `WITH`, `TEST`) or the word after group 1 is `TIMES` → `inline` True, target None; else `target`, `thru`. `perform_type`: `until` if `UNTIL` follows on the same line, `varying` if `VARYING`, `times` if `TIMES`, else None; `until` = rest after `UNTIL` or None.
  - `\bCALL\s+('([^']+)'|"([^"]+)"|([A-Z0-9-]+))`: literal or var; `using` = words after `USING` on that line as `{'mode': 'reference', 'text': w, 'name': w}`.
  - `\bMOVE\s+('(?:[^']|'')*'|"(?:[^"]|"")*"|[A-Z0-9-]+(?:\([^)]*\))?)\s+TO\s+([A-Z0-9-]+)` (on the original-case-upper content, not masked): `from_literal` if quoted else `from_var` = word before `(`; `to` = [group 2]; writes = [group 2]; reads = [from_var] if var.
  - `\bGO\s+TO\s+([A-Z0-9-]+)`, `\bGOBACK\b`, `\bSTOP\s+RUN\b` (`run` True), `\bEXIT\s+PROGRAM\b` (`program` True).
  - `\bOPEN\s+(INPUT|OUTPUT|I-O|EXTEND)\b(.*)`: split the rest into words; a word that is a mode starts a new mode group; other words are files.
  - `\bREAD\s+([A-Z0-9-]+)`, `\bWRITE\s+([A-Z0-9-]+)` (record), `\bREWRITE\s+([A-Z0-9-]+)`, `\bDELETE\s+([A-Z0-9-]+)`, `\bSTART\s+([A-Z0-9-]+)`, `\bCLOSE\s+(.*)` (files = words).
  - `^\s*IF\s+(.*)` → `if`, condition = rest; `else_pline` None. `^\s*EVALUATE\s+(.*)` → `evaluate`, subjects [rest], whens [], has_other False; `^\s*WHEN\s+(.*)` → if rest starts with `OTHER`: last evaluate's `has_other` True, `other_pline` = line; else append `{'index', 'pline', 'conditions': [rest]}` to the last evaluate.
- `copy_events_direct`: every `\bCOPY\s+('([^']+)'|"([^"]+)"|([A-Z0-9][A-Z0-9-]*))(?:\s+(?:OF|IN)\s+([A-Z0-9-]+))?` in non-comment content (any division): `{'name', 'path': first match in copybook_index or None, 'file_index': None, 'parent_file': 0, 'line', 'exact': True, 'enter_pline': line, 'exit_pline': line, 'depth': 1, 'missing': name not in copybook_index}`.

### 6.10 compare.py

```python
CATEGORIES = ['copybooks', 'call_targets', 'cics_programs', 'transids', 'cics_files', 'maps', 'db2_tables', 'batch_dd']

def dep_sets(final):
    """{category: set of upper names} from a final facts dict:
    copybooks: names of copybooks with depth 1; call_targets: resolved values of CALL transfers;
    cics_programs: resolved values of XCTL/LINK; transids: resolved values of RETURN_TRANSID/START_TRANSID;
    cics_files / maps / db2_tables / batch_dd: name_resolved values of resources of kind cics_file / map / db2_table / batch_file."""

def compare(final_proleap, final_text):
    """{category: {'proleap_only': sorted list, 'text_only': sorted list}} for categories with differences."""

def merge_text_only(final_proleap, final_text, diff):
    """For every text_only value, copy the matching entries (copybook / transfer / resource) from final_text
    into final_proleap, with 'source' = 'text_only' and new ids continuing the T/R numbering. Returns final_proleap."""
```

### 6.11 report.py

```python
def write_index(out_dir, entries):      # facts/_index.json
def write_report(out_dir, finals, diffs, meta):   # facts/facts_report.md
```

`_index.json`: `{"schema": "cobol-facts-index/1", "generated": iso time, "codebase_root", "programs": [{"name", "path", "source", "status", "kind", "facts_file": "cobol/<NAME>.json"}]}`.

`facts_report.md` sections, in order:
1. `# COBOL facts: <codebase_root>` and a line with generation time and program count.
2. **Summary table**: `| Program | Source | Status | Syntax errors | Line map exact | Kind | Paragraphs | Dead | Transfers (unresolved) | Resources (unresolved) | Missing copybooks |`.
3. **Programs using the text fallback**: name and `fallback_reason`; "none" if empty.
4. **Unresolved dynamic targets**: `| Program | Kind | Variable | Location |` for every transfer/resource with `unresolved` True.
5. **Missing copybooks**: name → programs.
6. **Parser vs text differences**: per program and category, `proleap_only` and `text_only`.
7. **Top unresolved data names**: up to 50 by total count across programs.

### 6.12 run_facts.py (driver)

```
python3 facts/run_facts.py --inventory <analysis_dir>/inventory.json --out <analysis_dir>
                           --jar <path>/cobol-ast-runner.jar
                           [--codebase <root>] [--jobs 1] [--timeout 300] [--xmx 2g]
                           [--only NAME[,NAME...]] [--no-proleap] [--java java]
```

- `--codebase` defaults to `inventory.meta.codebase_root`. All inventory paths are relative to it.
- Programs = inventory files with type `cobol_program`; filter by `--only` (upper names). Programs with encoding `ebcdic` or `binary` are skipped: they get no facts file and appear in the report with status `skipped_encoding`.
- FORMAT: inventory `source_format` `fixed` → `FIXED`, anything else → `VARIABLE`. CHARSET: `UTF-8` for every encoding except `latin-1` → `ISO-8859-1`.
- Copybook dirs: sorted unique absolute parent directories of inventory files with type `copybook` or `dclgen`. `copybook_index`: upper `name` → list of relative paths, for the same files.
- Output dirs: `<out>/facts/raw`, `<out>/facts/cobol`, `<out>/facts/logs`.
- Unless `--no-proleap`: split programs round-robin into `--jobs` lists; write `<out>/facts/logs/list_<k>.tsv`; run `java -Xmx<xmx> -cp <jar> local.cobol.facts.FactsRunner --list ... --out <out>/facts/raw --copybooks D1 --copybooks D2 ... --timeout-sec <timeout>` for all lists in parallel (`subprocess.Popen`, stdout/stderr appended to `<out>/facts/logs/java_<k>.log`). For each list: while the process exits with code 4, start it again (the SKIP rule resumes). If it exits with another non-zero code, start it once more; if it fails again, stop for that list. Python-side safety timeout per process run: `timeout * (remaining programs) + 120` seconds; on expiry kill it and treat as code 4 after writing a `timeout` raw JSON for the first program of the list that has no raw JSON.
- Print progress lines: `[proleap] list k: exit code c` and at the end `[facts] N programs: P proleap, T text, S skipped`.
- For each program (sorted by name):
  1. `text_raw = textscan.scan(...)`; `text_final = build.build(text_raw, original_lines, ctx)`.
  2. If a proleap raw JSON exists and its status is `ok` or `syntax_errors` and `divisions.procedure` is not null and (`len(paragraphs) > 0` or `len(text_raw.paragraphs) == 0`): `final = build.build(raw, pp_lines, ctx)`; `diff = compare.compare(final, text_final)`; `final = compare.merge_text_only(final, text_final, diff)`.
  3. Else: `final = text_final`, `quality.fallback_reason` = one of `no_proleap_output`, `status_<status>`, `no_procedure_division`, `no_paragraphs_found` (first that applies); diff = {}.
  4. Any exception in step 2 → log the traceback to `<out>/facts/logs/build_errors.log`, use step 3 with reason `build_error`.
  5. Write `<out>/facts/cobol/<NAME>.json`.
- Write `_index.json` and `facts_report.md`. Exit 0.

---

## 7. Final facts schema (`cobol-facts/1`)

File `<out>/facts/cobol/<NAME>.json`. Keys in this order. A location (`loc`, `start`, `end`) is always `[file_index, line]` where `file_index` points into `files`; `[0, 0]` means unknown.

| Key | Content |
|---|---|
| `schema` | `"cobol-facts/1"` |
| `name`, `path` | member name, path relative to the codebase root |
| `program_id` | first of `program_ids` or null |
| `source` | `proleap` or `text` |
| `quality` | 6.8 step 16 |
| `files` | `[{index, path, name, kind}]` |
| `metrics` | 6.8 step 15 |
| `kind`, `flags` | 6.8 step 14 |
| `interface` | 6.8 step 13 |
| `copybooks` | `[{name, path, file_index, loc, region, depth, via, missing, exact, source}]` (`loc` = location of the COPY statement in the parent file) |
| `sql_includes` | `[{name, loc}]` |
| `data_items` | `[{id, level, name, parent, record, children, conditions, section, fd, pic, usage, effective_usage, values (with kind/value added from literal_value), occurs, redefines, redefines_id, size, occurs_count, total_size, offset, is_group, size_unknown, loc, file_index}]` |
| `files_io` | 6.8 step 8 |
| `procedure` | `{sections: [...], paragraphs: [{name, section, declaratives, start, end, statements, complexity, est_tokens, reachable, reads, writes, performs, performed_by, transfers, resources, outline}]}` |
| `dead_paragraphs` | names with `reachable` False |
| `decisions` | 6.8 step 9 |
| `transfers` | `[{id, kind, target, resolved_targets, unresolved, commarea, length, using, paragraph, loc, guards, stmt_id, source}]` — kinds `CALL`, `LINK`, `XCTL`, `RETURN_TRANSID`, `RETURN`, `START_TRANSID`, `HANDLE_ABEND`, `GOBACK`, `STOP_RUN`, `EXIT_PROGRAM` |
| `resources` | `[{id, kind, name, name_resolved, mapset, mapset_resolved, op, command, extra, unresolved, paragraph, loc, guards, stmt_id, source}]` — kinds `cics_file`, `map`, `terminal`, `ts_queue`, `td_queue`, `container`, `db2_table`, `ims_call`, `mq_call`, `batch_file` |
| `error_handling` | `[{id, kind, detail, paragraph, loc}]` — kinds `HANDLE_ABEND`, `HANDLE_CONDITION`, `HANDLE_AID`, `ABEND`, `RESP_CHECK`, `RESP_EVAL`, `FILE_STATUS_CHECK`, `SQLCODE_CHECK`, `SQL_WHENEVER` |
| `unresolved_names` | 6.8 step 11 |
| `unused_data`, `write_only_data` | 6.8 step 12 |

Missing keys are never omitted: use null, `[]` or `{}`.

---

## 8. How later stages use these facts (copy into FACTS_SCHEMA.md)

| Later stage | Facts used |
|---|---|
| 3 Graph | `transfers` (with `resolved_targets`, `guards`), `copybooks`, `sql_includes`, `resources` (with `op`), `files_io.dd`, `interface` |
| 4 Modules and bundles | edges built from the above; `files_io.access_summary` and resource `op` for data ownership; `kind` and `flags`; `copybooks` (all depths) for bundle completeness |
| 5 Chunking | paragraph `start`/`end` (real lines), `est_tokens`, `reads`/`writes` (data definitions to include), `outline` (compact view of oversized paragraphs), `data_items` with `loc` |
| 6 LLM extraction | `decisions` (anchors and coverage check), `data_items` conditions (88-level names), valid names and lines for the hallucination guard |
| 7 IR | everything, excerpted by `ir_query` within a token budget |
| 8 Documents | `interface.linkage_layout`, `data_items` layouts, `files_io`, `transfers` + `guards` (screen flow), `outline` (activity diagrams), `error_handling`, `dead_paragraphs`, `metrics` |

---

## 9. Acceptance checks (AWS repo only)

Prerequisite: `analysis_out/aws-carddemo/inventory.json` exists. If not, run:
`python inventory/inventory.py "C:\My Folder\TCS\aws-mainframe-modernization-carddemo" --out analysis_out/aws-carddemo`

Build: `cd cobol-ast-runner` then `<mvn.cmd> -q clean package` (Maven path in section 0). Jar: `cobol-ast-runner/target/cobol-ast-runner.jar`.

Write the check scripts in the scratchpad directory of your session, not in the repo.

| # | After task | Check | Pass criteria |
|---|---|---|---|
| C1 | 2.1 | **Markers do not change parsing.** Use the batch programs `CBTRN02C`, `CBACT01C`, `CBACT04C` (they copy nothing that is missing; the CICS programs copy IBM's `DFHAID`/`DFHBMSCA`, which are not in the repo, so AstRunner stops on them). Run `java -jar cobol-ast-runner.jar <program> --copybooks <repo>/app/cpy --out <scratch>` (existing AstRunner) and note "Syntax errors". Run FactsRunner on the same three with `--copybooks <repo>/app/cpy`. Then run FactsRunner on `COMEN01C` and confirm `missing_copybooks` is `["DFHAID", "DFHBMSCA"]` and status is not `preprocess_failed`. | `syntax_error_count` equals the AstRunner count for each batch program; COMEN01C as described. **If not: stop (rule 0.6).** |
| C2 | 2.1 | **Line map.** Run `run_facts.py --only COMEN01C,COSGN00C,CBTRN02C` (with a temporary minimal build that only writes linemap results is fine), or call `linemap.build_linemap` directly on the three `.pp.cbl` files. For every pp line that starts with a paragraph name followed by `.` and that is mapped exact to file 0, the original line content (cols 8–72) must start with that paragraph name. For every copy event, the parent file line must contain `COPY` and the copybook name. | 100 % of those lines correct; `exact_ratio` ≥ 0.95 for all three |
| C3 | 2.2 | Run FactsRunner on all 26 programs. | 26 raw JSON files; every status is `ok` or `syntax_errors`; no `parse_failed`; raw JSON loads with `json.load` |
| C4 | 2.4 | `COMEN01C` final facts | a transfer `XCTL` with target var `CDEMO-MENU-OPT-PGMNAME` whose `resolved_targets` values include `COACTVWC`, `COACTUPC`, `COCRDLIC`, `COCRDSLC`, `COCRDUPC`, `COTRN00C` (how `value_table`); a transfer `XCTL` with var `CDEMO-TO-PROGRAM` resolving to `COSGN00C`; a `RETURN_TRANSID` resolving to `CM00` (how `value_clause`); resources `map` with name `COMEN1A` and mapset `COMEN01`, ops `send` and `receive`; `kind` `cics_online` |
| C5 | 2.4 | `COSGN00C` | resource `cics_file` op `read` with var `WS-USRSEC-FILE` resolved to `USRSEC`; XCTL literals `COADM01C` and `COMEN01C`, each with at least one guard |
| C6 | 2.4 | `CBTRN02C` | `kind` `batch_main`; `files_io` dd names exactly `ACCTFILE, DALYREJS, DALYTRAN, TCATBALF, TRANFILE, XREFFILE`; `DALYTRAN` access `read`; `TRANFILE` access includes write (`write` or `read_write`); transfer `CALL` `CEE3ABD`; an `ABEND` error entry; at least one `FILE_STATUS_CHECK` |
| C7 | 2.4 | `CSUTLDTC`, `CORPT00C`, `COTRN02C` | `CSUTLDTC.kind` `batch_subroutine`, `interface.procedure_using` = `LS-DATE, LS-DATE-FORMAT, LS-RESULT`; `CORPT00C` and `COTRN02C` each have a `CALL` transfer resolving to `CSUTLDTC` |
| C8 | 2.4 | All 26 programs | for every paragraph with `start[0] == 0`, original line `start[1]` content starts with the paragraph name; every `loc` with file_index 0 is within the program's line count; JSON loads |
| C9 | 2.5 | `run_facts.py` on the whole AWS inventory | exit 0; 26 facts files; `_index.json` and `facts_report.md` written; all 26 `source` = `proleap` |
| C10 | 2.5 | Text fallback alone: `run_facts.py ... --no-proleap --out <scratch>` | 26 facts files with `source` `text`; `COMEN01C` still has the XCTL `COSGN00C` (move_literal) and the map resources |
| C11 | 2.5 | Report review | `facts_report.md` "Parser vs text differences" lists no `text_only` entries for `copybooks` (if it does, report them; do not fix by hand) |

Also run the unit tests: `python -m unittest discover -s facts/tests -t facts` → all pass.

### Unit test cases (put these in the test files)

`test_cics.py`:
- `parse("EXEC CICS XCTL PROGRAM('COSGN00C') COMMAREA(CARDDEMO-COMMAREA) END-EXEC")` → command `XCTL`, PROGRAM literal `COSGN00C`, COMMAREA var `CARDDEMO-COMMAREA`.
- `parse("EXEC CICS RETURN TRANSID (WS-TRANID) COMMAREA (CARDDEMO-COMMAREA) END-EXEC")` → command `RETURN`, TRANSID var `WS-TRANID` (space before parenthesis).
- `parse("EXEC CICS SEND MAP('COMEN1A') MAPSET('COMEN01') FROM(COMEN1AO) ERASE END-EXEC")` → command `SEND MAP`, ERASE flag, FROM var `COMEN1AO`.
- `parse("EXEC CICS READ DATASET (WS-USRSEC-FILE) INTO (SEC-USER-DATA) RIDFLD (WS-USER-ID) RESP (WS-RESP-CD) END-EXEC")` → `interpret` gives resource `cics_file` op `read`, writes include `SEC-USER-DATA` and `WS-RESP-CD`, error `RESP_CHECK`.
- `parse("EXEC CICS XCTL PROGRAM(CDEMO-MENU-OPT-PGMNAME(WS-OPTION)) END-EXEC")` → PROGRAM var `CDEMO-MENU-OPT-PGMNAME`, text `CDEMO-MENU-OPT-PGMNAME(WS-OPTION)`.
- `parse("EXEC CICS HANDLE CONDITION NOTFND(9000-NOTFND) ERROR(9999-ERR) END-EXEC")` → command `HANDLE CONDITION`; interpret labels `9000-NOTFND`, `9999-ERR`.

`test_sql.py`:
- `"EXEC SQL SELECT A, B INTO :WS-A, :WS-B FROM CARDDEMO.ACCT_TBL WHERE ID = :WS-ID END-EXEC"` → kind `select`, tables `[CARDDEMO.ACCT_TBL read]`, host_writes `WS-A, WS-B`, host_reads `WS-ID`.
- `"EXEC SQL INSERT INTO TRAN_TYPE (C1, C2) VALUES (:H1, :H2) END-EXEC"` → `insert`, table `TRAN_TYPE` op `insert`.
- `"EXEC SQL DECLARE C1 CURSOR FOR SELECT X FROM T1 A JOIN T2 B ON A.K = B.K END-EXEC"` → `declare_cursor`, cursor `C1`, tables `T1`, `T2` op `read`.
- `"EXEC SQL INCLUDE SQLCA END-EXEC"` → include `SQLCA`.
- `"EXEC SQL DELETE FROM T3 WHERE K IN (SELECT K FROM T4) END-EXEC"` → `T3 delete`, `T4 read`.

`test_layout.py`:
- Items: `01 R.` / `05 A PIC X(10).` / `05 B PIC S9(7)V99 COMP-3.` / `05 C PIC 9(4) COMP.` / `05 D REDEFINES C PIC XX.` / `05 E OCCURS 3 TIMES.` / `10 E1 PIC X(2).` / `10 E2 PIC 9(3).` → sizes A 10, B 5, C 2, D 2, E size 5 total 15, R 32; offsets A 0, B 10, C 15, D 15, E 17, E1 17, E2 19.
- `pic_size('S9(5)V99', 'DISPLAY', 'SIGN LEADING SEPARATE')` → 8.
- A table like COMEN02Y: `01 T.` / `05 T-DATA.` / `10 FILLER PIC 9(02) VALUE 1.` / `10 FILLER PIC X(08) VALUE 'PGMA'.` / `10 FILLER PIC 9(02) VALUE 2.` / `10 FILLER PIC X(08) VALUE 'PGMB'.` / `05 T-TAB REDEFINES T-DATA.` / `10 T-ENT OCCURS 2 TIMES.` / `15 T-NUM PIC 9(02).` / `15 T-PGM PIC X(08).` → `occurrence_values` of `T-PGM` = `['PGMA', 'PGMB']`, of `T-NUM` = `['01', '02']`.

`test_linemap.py` (use `read_lines` injection, FIXED format; build original lines with 6-space sequence area + indicator column):
- Program lines: 1 `       IDENTIFICATION DIVISION.`, 2 `       PROGRAM-ID. T1.`, 3 `      * comment`, 4 `       DATA DIVISION.`, 5 `       WORKING-STORAGE SECTION.`, 6 `       COPY CPY1.`, 7 `       PROCEDURE DIVISION.`, 8 `       MAIN-PARA.`, 9 `           GOBACK.`. Copybook `/x/CPY1.cpy` lines: 1 `       01 A PIC X.`.
  pp lines: `       IDENTIFICATION DIVISION.`, `       PROGRAM-ID. T1.`, `      *> comment`, `       DATA DIVISION.`, `       WORKING-STORAGE SECTION.`, `       `, `*> @@CPYENTER CPY1|/x/CPY1.cpy`, `       01 A PIC X.`, `*> @@CPYEXIT CPY1`, `       PROCEDURE DIVISION.`, `       MAIN-PARA.`, `           GOBACK.`
  Expected map (file, line): (0,1) (0,2) (0,3) (0,4) (0,5) (0,5 not exact) (0,6) (1,1) (0,6 not exact) (0,7) (0,8) (0,9); one copy event CPY1 line 6 depth 1.
- Continuation: original lines `       MOVE 'ABC` + continuation line with `-` indicator `    'DEF' TO X.` then `       DISPLAY X.`; pp lines `       MOVE 'ABCDEF' TO X.`, `       DISPLAY X.` → maps to lines 1 and 3.

---

## 10. Documentation tasks (task 2.6)

1. `facts/README.md`, written for a person on the offline VM without any AI assistant. Sections: Purpose (2 lines); Requirements (Python 3.8+, Java 17, the jar built from `cobol-ast-runner`); Steps: (1) run inventory, (2) build the jar (`mvn clean package` in `cobol-ast-runner`, Nexus sections in the pom), (3) the `run_facts.py` command with every option explained, (4) what is in the output folder; How to read `facts_report.md`; Troubleshooting: `timeout` status (raise `--timeout`, `--xmx`), `parse_failed` (the text fallback is used automatically), missing copybooks (listed in the report; add the folder to the codebase), out of memory (`--xmx 4g`, `--jobs 1`).
2. `docs/FACTS_SCHEMA.md`: section 7 and section 8 of this document, plus one short example object for a transfer, a resource and a paragraph taken from the real `COMEN01C` output.
3. `cobol-ast-runner/README.md`: add a section "Batch facts mode" with the FactsRunner command line from 4.6, the TSV format and exit codes (0 finished, 1 bad arguments, 4 timeout: restart to resume). Say that normally `facts/run_facts.py` calls it.
4. In `docs/MODULARIZATION_PLAN.md`, under "### 2a. COBOL programs", add one line at the top: `Detailed build plan: [STEP2_BUILD_PLAN.md](STEP2_BUILD_PLAN.md). Output schema: [FACTS_SCHEMA.md](FACTS_SCHEMA.md).`

---

## 11. Things not to do

- No ASG (`CobolParserRunnerImpl.analyzeFile`) in the facts path; only the parse tree.
- No LLM calls in this step.
- No new dependencies (Java or Python).
- Do not change the output of `AstRunner`.
- Do not "improve" acceptance values to make checks pass; if real output differs, report it.
- Do not run anything on `CardDemo-Cobol-main` or CBSA.

---

## 12. Final report to the user

When all tasks are done, report in this format:

1. Files created and edited (list).
2. Results of checks C1–C11 and the unit tests: pass/fail and, for any fail, the actual output.
3. Numbers from the AWS run: programs by source and status, total transfers, resources, unresolved transfers/resources (list them), missing copybooks, average `line_map_exact_ratio`, total run time.
4. Every place where this plan was unclear and what you chose (rule in the header of this document).
5. The exact commands the user runs on the other two repos (one `inventory.py` and one `run_facts.py` command each, with `analysis_out/carddemo-main` and `analysis_out/cbsa` output folders).
