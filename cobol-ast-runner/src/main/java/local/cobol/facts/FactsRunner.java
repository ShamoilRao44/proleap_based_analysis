package local.cobol.facts;

import java.io.BufferedReader;
import java.io.File;
import java.io.IOException;
import java.io.Writer;
import java.nio.charset.Charset;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.StandardCharsets;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.TreeSet;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

import org.antlr.v4.runtime.BaseErrorListener;
import org.antlr.v4.runtime.CharStreams;
import org.antlr.v4.runtime.CommonTokenStream;
import org.antlr.v4.runtime.RecognitionException;
import org.antlr.v4.runtime.Recognizer;

import io.proleap.cobol.CobolLexer;
import io.proleap.cobol.CobolParser;
import io.proleap.cobol.asg.params.CobolDialect;
import io.proleap.cobol.asg.params.CobolParserParams;
import io.proleap.cobol.asg.params.impl.CobolParserParamsImpl;
import io.proleap.cobol.preprocessor.CobolPreprocessor.CobolSourceFormatEnum;

/**
 * Batch facts mode: parses many COBOL programs in one JVM and writes one raw facts JSON (and the
 * marked preprocessed source) per program.
 */
public class FactsRunner {

	protected static final String USAGE = String.join("\n", //
			"Usage: java -cp cobol-ast-runner.jar local.cobol.facts.FactsRunner --list FILE.tsv --out RAW_DIR", //
			"       [--copybooks DIR]... [--timeout-sec 300] [--verbose]", //
			"", //
			"List file: NAME<TAB>ABSOLUTE_PATH<TAB>FORMAT<TAB>CHARSET per line.", //
			"Exit codes: 0 finished, 1 bad arguments, 4 timeout (restart to resume).");

	public static void main(final String[] args) {
		System.exit(new FactsRunner().run(args));
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

	public int run(final String[] args) {
		File listFile = null;
		File outDir = null;
		final List<File> copybookDirs = new ArrayList<File>();
		int timeoutSec = 300;
		boolean verbose = false;

		try {
			for (int i = 0; i < args.length; i++) {
				switch (args[i]) {
				case "--list":
					listFile = new File(args[++i]);
					break;
				case "--out":
					outDir = new File(args[++i]);
					break;
				case "--copybooks":
					copybookDirs.add(new File(args[++i]));
					break;
				case "--timeout-sec":
					timeoutSec = Integer.parseInt(args[++i]);
					break;
				case "--verbose":
					verbose = true;
					break;
				case "-h":
				case "--help":
					System.out.println(USAGE);
					return 0;
				default:
					throw new IllegalArgumentException("Unknown argument: " + args[i]);
				}
			}
		} catch (final ArrayIndexOutOfBoundsException | IllegalArgumentException e) {
			System.err.println("Bad arguments: " + e.getMessage() + "\n\n" + USAGE);
			return 1;
		}

		if (listFile == null || outDir == null || !listFile.isFile()) {
			System.err.println(USAGE);
			return 1;
		}

		System.setProperty("org.slf4j.simpleLogger.defaultLogLevel", verbose ? "info" : "warn");

		final List<File> existingDirs = new ArrayList<File>();
		for (final File d : copybookDirs) {
			if (d.isDirectory()) {
				existingDirs.add(d);
			} else {
				System.err.println("Warning: copybook folder does not exist: " + d.getAbsolutePath());
			}
		}

		final List<String[]> entries = new ArrayList<String[]>();
		try (BufferedReader reader = Files.newBufferedReader(listFile.toPath(), StandardCharsets.UTF_8)) {
			String line;
			while ((line = reader.readLine()) != null) {
				if (line.trim().isEmpty()) {
					continue;
				}
				final String[] parts = line.split("\t");
				if (parts.length < 4) {
					System.err.println("Bad list line: " + line);
					return 1;
				}
				entries.add(parts);
			}
		} catch (final IOException e) {
			System.err.println("Cannot read list file: " + e);
			return 1;
		}

		outDir.mkdirs();

		final ExecutorService executor = Executors.newSingleThreadExecutor(r -> {
			final Thread t = new Thread(r, "facts-worker");
			t.setDaemon(true);
			return t;
		});

		for (final String[] entry : entries) {
			final String name = entry[0];
			final File rawFile = new File(outDir, name + ".raw.json");

			if (rawFile.exists()) {
				System.out.println("SKIP " + name);
				continue;
			}

			final File program = new File(entry[1]);
			final String format = entry[2];
			final String charset = entry[3];
			final List<File> dirs = existingDirs;
			final File out = outDir;

			final Future<String> future = executor
					.submit(() -> processOne(name, program, format, charset, dirs, out));

			try {
				final String status = future.get(timeoutSec, TimeUnit.SECONDS);
				System.out.println("DONE " + name + " " + status);
			} catch (final TimeoutException e) {
				try {
					final Map<String, Object> raw = header(name, program, format, charset);
					raw.put("status", "timeout");
					raw.put("error", "timeout after " + timeoutSec + " s");
					writeRaw(rawFile, raw);
				} catch (final IOException io) {
					System.err.println("Cannot write timeout file: " + io);
				}
				System.out.println("TIMEOUT " + name);
				System.out.flush();
				System.exit(4);
			} catch (final InterruptedException | ExecutionException e) {
				System.err.println("FAILED " + name + ": " + e);
				try {
					final Map<String, Object> raw = header(name, program, format, charset);
					raw.put("status", "parse_failed");
					raw.put("error", String.valueOf(e.getCause() != null ? e.getCause() : e));
					writeRaw(rawFile, raw);
				} catch (final IOException io) {
					System.err.println("Cannot write failure file: " + io);
				}
			}
		}

		System.out.println("FINISHED");
		return 0;
	}

	protected Map<String, Object> header(final String name, final File program, final String format,
			final String charset) {
		final Map<String, Object> raw = new LinkedHashMap<String, Object>();
		raw.put("schema", "cobol-raw-facts/1");
		raw.put("name", name);
		raw.put("program_file", program.getAbsolutePath());
		raw.put("parser", "proleap");
		raw.put("format", format);
		raw.put("charset", charset);
		raw.put("status", "ok");
		raw.put("error", null);
		raw.put("parse_ms", 0);
		raw.put("preprocessed_file", null);
		raw.put("missing_copybooks", new ArrayList<String>());
		raw.put("syntax_error_count", 0);
		raw.put("syntax_errors", new ArrayList<Object>());
		return raw;
	}

	protected void writeRaw(final File rawFile, final Map<String, Object> raw) throws IOException {
		final File tmp = new File(rawFile.getParentFile(), rawFile.getName() + ".tmp");
		try (Writer w = Files.newBufferedWriter(tmp.toPath(), StandardCharsets.UTF_8)) {
			Json.write(raw, w);
		}
		try {
			Files.move(tmp.toPath(), rawFile.toPath(), StandardCopyOption.REPLACE_EXISTING,
					StandardCopyOption.ATOMIC_MOVE);
		} catch (final AtomicMoveNotSupportedException e) {
			Files.move(tmp.toPath(), rawFile.toPath(), StandardCopyOption.REPLACE_EXISTING);
		}
	}

	protected String shorten(final String msg) {
		final int expecting = msg.indexOf(" expecting {");
		return expecting > 0 && msg.length() - expecting > 120 ? msg.substring(0, expecting + 120) + " ...}" : msg;
	}

	protected String processOne(final String name, final File file, final String format, final String charsetName,
			final List<File> copybookDirs, final File outDir) throws IOException {
		Charset charset = Charset.forName(charsetName);
		final Map<String, Object> raw = header(name, file, format, charsetName);
		final File rawFile = new File(outDir, name + ".raw.json");

		final CobolParserParams params = new CobolParserParamsImpl();
		params.setCopyBookDirectories(copybookDirs);
		params.setCopyBookExtensions(collectExtensions(copybookDirs));
		params.setFormat(CobolSourceFormatEnum.valueOf(format.toUpperCase()));
		params.setDialect(CobolDialect.ANSI85);
		params.setCharset(charset);
		params.setIgnoreSyntaxErrors(true);

		final List<String> missing = new ArrayList<String>();
		final long start = System.currentTimeMillis();
		String pp;

		try {
			try {
				pp = new MarkingPreprocessor(missing).process(file, params);
			} catch (final CharacterCodingException e) {
				charset = StandardCharsets.ISO_8859_1;
				params.setCharset(charset);
				raw.put("charset", charset.name());
				missing.clear();
				pp = new MarkingPreprocessor(missing).process(file, params);
			}
		} catch (final Exception e) {
			raw.put("status", "preprocess_failed");
			raw.put("error", e.toString());
			raw.put("missing_copybooks", new ArrayList<String>(new LinkedHashSet<String>(missing)));
			raw.put("parse_ms", System.currentTimeMillis() - start);
			writeRaw(rawFile, raw);
			return "preprocess_failed";
		}

		Files.writeString(new File(outDir, name + ".pp.cbl").toPath(), pp, StandardCharsets.UTF_8);
		raw.put("preprocessed_file", name + ".pp.cbl");

		final List<Object> errors = new ArrayList<Object>();
		final int[] errorCount = new int[1];
		final BaseErrorListener collector = new BaseErrorListener() {
			@Override
			public void syntaxError(final Recognizer<?, ?> recognizer, final Object offendingSymbol, final int line,
					final int charPositionInLine, final String msg, final RecognitionException e) {
				errorCount[0]++;
				if (errors.size() < 500) {
					final Map<String, Object> err = new LinkedHashMap<String, Object>();
					err.put("pline", line);
					err.put("col", charPositionInLine);
					err.put("msg", shorten(msg));
					errors.add(err);
				}
			}
		};

		final CobolLexer lexer = new CobolLexer(CharStreams.fromString(pp));
		lexer.removeErrorListeners();
		lexer.addErrorListener(collector);

		final CommonTokenStream tokens = new CommonTokenStream(lexer);
		final CobolParser parser = new CobolParser(tokens);
		parser.removeErrorListeners();
		parser.addErrorListener(collector);

		Map<String, Object> facts;
		String status;
		String error = null;

		try {
			final CobolParser.StartRuleContext root = parser.startRule();
			facts = new FactsExtractor(root).extract();
			status = errorCount[0] == 0 ? "ok" : "syntax_errors";
		} catch (final Exception | StackOverflowError e) {
			facts = new LinkedHashMap<String, Object>();
			status = "parse_failed";
			error = e.toString();
		}

		raw.put("status", status);
		raw.put("error", error);
		raw.put("parse_ms", System.currentTimeMillis() - start);
		raw.put("missing_copybooks", new ArrayList<String>(new LinkedHashSet<String>(missing)));
		raw.put("syntax_error_count", errorCount[0]);
		raw.put("syntax_errors", errors);
		raw.putAll(facts);

		writeRaw(rawFile, raw);
		return status;
	}
}
