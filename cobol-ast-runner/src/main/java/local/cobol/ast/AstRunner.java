package local.cobol.ast;

import java.io.File;
import java.io.IOException;
import java.io.PrintWriter;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.Charset;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeSet;

import io.proleap.cobol.asg.metamodel.Program;
import io.proleap.cobol.asg.params.CobolDialect;
import io.proleap.cobol.asg.params.CobolParserParams;
import io.proleap.cobol.asg.params.impl.CobolParserParamsImpl;
import io.proleap.cobol.preprocessor.CobolPreprocessor.CobolSourceFormatEnum;
import io.proleap.cobol.preprocessor.exception.CobolPreprocessorException;

/**
 * Parses one COBOL program with the ProLeap parser and writes:
 *
 * <ul>
 * <li>NAME.preprocessed.cbl - source after COPY expansion, as seen by the parser</li>
 * <li>NAME.ast.txt - indented AST</li>
 * <li>NAME.summary.txt - syntax errors, unresolved names, CALL / EXEC CICS / EXEC SQL, structure</li>
 * </ul>
 *
 * Syntax errors do not stop the run; they are collected and reported.
 */
public class AstRunner {

	protected static final String USAGE = String.join("\n", //
			"Usage: java -jar cobol-ast-runner.jar <program_file> [options]", //
			"", //
			"Options:", //
			"  --copybooks DIR     copybook folder, may be repeated (default: <program dir>/copybooks)", //
			"  --format FORMAT     FIXED (default), VARIABLE or TANDEM", //
			"  --dialect DIALECT   ANSI85 (default), MF or OSVS", //
			"  --charset NAME      source charset (default UTF-8, falls back to ISO-8859-1 on bad bytes)", //
			"  --out DIR           output folder (default: <program dir>/ast_output)", //
			"  --no-collapse       print every AST rule on its own line", //
			"  --verbose           show ProLeap log messages", //
			"", //
			"Exit codes: 0 parsed cleanly, 1 bad arguments, 2 parsed with syntax errors or ASG failure,", //
			"            3 copybook not found or file unreadable");

	public static void main(final String[] args) {
		System.exit(new AstRunner().run(args));
	}

	protected List<String> collectExtensions(final List<File> copybookDirs) {
		final TreeSet<String> result = new TreeSet<String>();
		result.add("");

		for (final File dir : copybookDirs) {
			final File[] files = dir.listFiles(File::isFile);

			if (files != null) {
				for (final File file : files) {
					final String name = file.getName();
					final int dot = name.lastIndexOf('.');

					if (dot > 0) {
						result.add(name.substring(dot + 1));
					}
				}
			}
		}

		return new ArrayList<String>(result);
	}

	protected List<String> collectEmptyCopybooks(final List<File> copybookDirs) {
		final List<String> result = new ArrayList<String>();

		for (final File dir : copybookDirs) {
			final File[] files = dir.listFiles(f -> f.isFile() && f.length() == 0);

			if (files != null) {
				Arrays.stream(files).map(File::getName).sorted().forEach(result::add);
			}
		}

		return result;
	}

	protected CobolParserParams createParams(final List<File> copybookDirs, final CobolSourceFormatEnum format,
			final CobolDialect dialect, final Charset charset) {
		final CobolParserParams params = new CobolParserParamsImpl();
		params.setCopyBookDirectories(copybookDirs);
		params.setCopyBookExtensions(collectExtensions(copybookDirs));
		params.setFormat(format);
		params.setDialect(dialect);
		params.setCharset(charset);
		params.setIgnoreSyntaxErrors(true);
		return params;
	}

	protected String fileNameOf(final File programFile) {
		final String name = programFile.getName();
		final int dot = name.lastIndexOf('.');
		return dot > 0 ? name.substring(0, dot) : name;
	}

	public int run(final String[] args) {
		File programFile = null;
		final List<File> copybookDirs = new ArrayList<File>();
		CobolSourceFormatEnum format = CobolSourceFormatEnum.FIXED;
		CobolDialect dialect = CobolDialect.ANSI85;
		Charset charset = StandardCharsets.UTF_8;
		File outDir = null;
		boolean collapse = true;
		boolean verbose = false;

		try {
			for (int i = 0; i < args.length; i++) {
				switch (args[i]) {
				case "--copybooks":
					copybookDirs.add(new File(args[++i]));
					break;
				case "--format":
					format = CobolSourceFormatEnum.valueOf(args[++i].toUpperCase());
					break;
				case "--dialect":
					dialect = CobolDialect.valueOf(args[++i].toUpperCase());
					break;
				case "--charset":
					charset = Charset.forName(args[++i]);
					break;
				case "--out":
					outDir = new File(args[++i]);
					break;
				case "--no-collapse":
					collapse = false;
					break;
				case "--verbose":
					verbose = true;
					break;
				case "-h":
				case "--help":
					System.out.println(USAGE);
					return 0;
				default:
					if (args[i].startsWith("--") || programFile != null) {
						throw new IllegalArgumentException("Unknown argument: " + args[i]);
					}
					programFile = new File(args[i]);
				}
			}
		} catch (final ArrayIndexOutOfBoundsException e) {
			System.err.println("Missing value for " + args[args.length - 1] + "\n\n" + USAGE);
			return 1;
		} catch (final IllegalArgumentException e) {
			System.err.println(e.getMessage() + "\n\n" + USAGE);
			return 1;
		}

		if (programFile == null) {
			System.err.println(USAGE);
			return 1;
		}
		if (!programFile.isFile()) {
			System.err.println("Program file not found: " + programFile.getAbsolutePath());
			return 1;
		}

		// must be set before the first logger is created
		System.setProperty("org.slf4j.simpleLogger.defaultLogLevel", verbose ? "info" : "warn");

		final File programDir = programFile.getAbsoluteFile().getParentFile();

		if (copybookDirs.isEmpty()) {
			copybookDirs.add(new File(programDir, "copybooks"));
		}
		for (final File dir : copybookDirs) {
			if (!dir.isDirectory()) {
				System.err.println("Warning: copybook folder does not exist: " + dir.getAbsolutePath());
			}
		}
		if (outDir == null) {
			outDir = new File(programDir, "ast_output");
		}

		final List<File> existingCopybookDirs = new ArrayList<File>();
		copybookDirs.stream().filter(File::isDirectory).forEach(existingCopybookDirs::add);

		try {
			return parseAndWrite(programFile, existingCopybookDirs, format, dialect, charset, outDir, collapse);
		} catch (final IOException e) {
			System.err.println("Could not read or write files: " + e);
			return 3;
		}
	}

	protected int parseAndWrite(final File programFile, final List<File> copybookDirs,
			final CobolSourceFormatEnum format, final CobolDialect dialect, final Charset requestedCharset,
			final File outDir, final boolean collapse) throws IOException {
		Charset charset = requestedCharset;
		CollectingParserRunner runner = new CollectingParserRunner();
		Program program = null;
		String asgError = null;

		System.out.println("Parsing " + programFile.getAbsolutePath());
		System.out.println("  format " + format + ", dialect " + dialect + ", copybooks " + copybookDirs);

		final long start = System.currentTimeMillis();

		try {
			try {
				program = runner.analyzeFile(programFile, createParams(copybookDirs, format, dialect, charset));
			} catch (final CharacterCodingException e) {
				System.out.println("  input is not valid " + charset + ", retrying with ISO-8859-1");
				charset = StandardCharsets.ISO_8859_1;
				runner = new CollectingParserRunner();
				program = runner.analyzeFile(programFile, createParams(copybookDirs, format, dialect, charset));
			}
		} catch (final CobolPreprocessorException e) {
			System.err.println("Preprocessing failed: " + e.getMessage());
			System.err.println("Run fetch_copybooks.py with --stub-missing to create empty stubs for missing copybooks.");
			return 3;
		} catch (final RuntimeException e) {
			// AST was built but the semantic analysis (ASG) failed, usually because of syntax errors
			if (runner.getStartRule() == null) {
				throw e;
			}
			asgError = e.toString();
			program = null;
		}

		final long millis = System.currentTimeMillis() - start;
		final String name = fileNameOf(programFile);
		Files.createDirectories(outDir.toPath());

		final File preprocessedFile = new File(outDir, name + ".preprocessed.cbl");
		Files.writeString(preprocessedFile.toPath(), runner.getPreprocessedInput(), StandardCharsets.UTF_8);

		final File astFile = new File(outDir, name + ".ast.txt");
		try (PrintWriter out = new PrintWriter(astFile, StandardCharsets.UTF_8)) {
			new AstPrinter(out, program, collapse).print(runner.getStartRule(), 0);
		}

		final AsgSummary summary = program == null ? new AsgSummary()
				: AsgSummary.of(program, runner.getStartRule());

		final Map<String, String> header = new LinkedHashMap<String, String>();
		header.put("program file", programFile.getAbsolutePath());
		header.put("format", format.name());
		header.put("dialect", dialect.name());
		header.put("charset", charset.name());
		header.put("copybook folders", copybookDirs.toString());
		header.put("parse time", millis + " ms");

		final List<CollectingParserRunner.SyntaxError> syntaxErrors = runner.getSyntaxErrors();
		final File summaryFile = new File(outDir, name + ".summary.txt");
		try (PrintWriter out = new PrintWriter(summaryFile, StandardCharsets.UTF_8)) {
			summary.write(out, header, collectEmptyCopybooks(copybookDirs), syntaxErrors, asgError);
		}

		System.out.println();
		System.out.println("Parse time        : " + millis + " ms");
		System.out.println("Syntax errors     : " + syntaxErrors.size());
		if (asgError != null) {
			System.out.println("ASG analysis      : FAILED - " + asgError);
		}
		System.out.println("Program-id        : " + String.join(", ", summary.programIds));
		System.out.println("Paragraphs        : " + summary.paragraphs.size());
		System.out.println("Unresolved names  : " + summary.unresolvedNames.size());
		System.out.println("CALL targets      : " + summary.callTargets.size());
		System.out.println("EXEC CICS / SQL   : " + summary.execCics.size() + " / " + summary.execSql.size());
		System.out.println();
		System.out.println("Written:");
		System.out.println("  " + preprocessedFile.getAbsolutePath());
		System.out.println("  " + astFile.getAbsolutePath());
		System.out.println("  " + summaryFile.getAbsolutePath());

		return syntaxErrors.isEmpty() && asgError == null ? 0 : 2;
	}
}
