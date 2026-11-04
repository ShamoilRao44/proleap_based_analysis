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
