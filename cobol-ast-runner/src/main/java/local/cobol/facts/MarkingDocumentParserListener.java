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

	/**
	 * ProLeap's literal finder only matches a quoted name that already contains the file extension, so
	 * COPY 'NAME' never finds NAME.cpy. This fallback looks the unquoted name up with the configured
	 * extensions, case-insensitively, in the copybook folders (not recursive).
	 */
	protected File findByName(final String name, final CobolParserParams params) {
		if (params.getCopyBookDirectories() == null) {
			return null;
		}
		String base = name.replace("\\", "/");
		base = base.substring(base.lastIndexOf('/') + 1);
		final List<String> extensions = params.getCopyBookExtensions();

		for (final File dir : params.getCopyBookDirectories()) {
			final File[] files = dir.listFiles(File::isFile);
			if (files == null) {
				continue;
			}
			if (extensions != null) {
				for (final String ext : extensions) {
					final String wanted = ext == null || ext.isEmpty() ? base : base + "." + ext;
					for (final File f : files) {
						if (f.getName().equalsIgnoreCase(wanted)) {
							return f;
						}
					}
				}
			}
		}
		return null;
	}

	@Override
	protected String getCopyBookContent(final CopySourceContext copySource, final CobolParserParams params) {
		final String name = copyName(copySource);
		File copyBook = findCopyBook(copySource, params);

		if (copyBook == null) {
			copyBook = findByName(name, params);
		}

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
