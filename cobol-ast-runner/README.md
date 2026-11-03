# cobol-ast-runner

Parses one COBOL program with the ProLeap COBOL parser and writes its AST, the preprocessed source, and a summary of what the semantic graph (ASG) found. Syntax errors do not stop the run: they are collected and reported, and the rest of the program is still parsed.

## Build (once)

Requirements: JDK 17 and Maven 3.

1. Install the ProLeap parser into the local Maven repository:
   ```
   cd proleap-cobol-parser
   mvn clean install -DskipTests
   ```
2. Add your Nexus `<repositories>` and `<pluginRepositories>` sections to `cobol-ast-runner/pom.xml`. Besides the parser, the build needs `slf4j-simple` plus the `maven-compiler-plugin` and `maven-shade-plugin`.
3. Build:
   ```
   cd cobol-ast-runner
   mvn clean package
   ```
   This produces `target/cobol-ast-runner.jar`, a single jar that contains all dependencies.

## Run

Typical flow for one isolated program:

```
# 1. collect copybooks, with empty stubs for the ones that cannot be found
python3 fetch_copybooks.py ~/isolated/CUCO003/CUCO003 /data/codebase --stub-missing

# 2. parse
java -jar target/cobol-ast-runner.jar ~/isolated/CUCO003/CUCO003
```

By default copybooks are read from `<program dir>/copybooks` and output is written to `<program dir>/ast_output/`:

| File | Content |
|---|---|
| `CUCO003.preprocessed.cbl` | Source after COPY expansion, exactly as the parser saw it. All line numbers below refer to this file. |
| `CUCO003.ast.txt` | Indented AST, one grammar rule per line. |
| `CUCO003.summary.txt` | Syntax errors, stubbed copybooks, unresolved names, CALL targets, EXEC CICS and EXEC SQL blocks, statement counts, 01/77 data items, sections and paragraphs. |

Options:

```
--copybooks DIR     copybook folder, may be repeated (default: <program dir>/copybooks)
--format FORMAT     FIXED (default), VARIABLE or TANDEM
--dialect DIALECT   ANSI85 (default), MF or OSVS
--charset NAME      source charset (default UTF-8, falls back to ISO-8859-1 on bad bytes)
--out DIR           output folder (default: <program dir>/ast_output)
--no-collapse       print every AST rule on its own line
--verbose           show ProLeap log messages
```

Exit codes:

- `0` parsed cleanly
- `1` bad arguments
- `2` parsed, but with syntax errors or a failed ASG step (output is still written)
- `3` a copybook was not found, or a file could not be read

## Reading the AST

```
paragraph @L21
  paragraphName > cobolWord @L21  "MAIN-PARA"
  "."
  sentence @L22
    statement > moveStatement @L22
      "MOVE"
      moveToStatement @L22
        moveToSendingArea > identifier > ... > cobolWord @L22  "CUST-ID"
        "TO"
        identifier > ... > cobolWord @L22  [UNRESOLVED]  "MISS-KEY"
```

- `@L22` is the line in the preprocessed file.
- `a > b > c` means a chain of rules that each have exactly one child, printed on one line to save space. Use `--no-collapse` to see them separately.
- `[UNRESOLVED]` marks a name the ASG could not find a definition for. It is usually defined in a missing or stubbed copybook.
- `!! SYNTAX ERROR` marks a rule where the parser had to recover from an error, typically where a stubbed copybook was meant to supply code.

## Notes

- `EXEC CICS`, `EXEC SQL` and `EXEC SQLIMS` blocks are kept as text and not parsed further. The summary lists them in full.
- `EXEC SQL INCLUDE` members (DCLGEN, SQLCA) are not expanded by ProLeap, so host variables defined only in them show up as unresolved names.
- A `CALL` with a variable target (for example `CALL WS-PGM-NAME`) is listed by variable name. Look up its `VALUE` in the data items to find the program.
