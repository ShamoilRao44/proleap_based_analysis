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
