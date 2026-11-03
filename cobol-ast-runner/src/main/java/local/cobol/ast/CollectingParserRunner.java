package local.cobol.ast;

import java.io.IOException;
import java.util.ArrayList;
import java.util.List;

import org.antlr.v4.runtime.BaseErrorListener;
import org.antlr.v4.runtime.CharStreams;
import org.antlr.v4.runtime.CommonTokenStream;
import org.antlr.v4.runtime.RecognitionException;
import org.antlr.v4.runtime.Recognizer;

import io.proleap.cobol.CobolLexer;
import io.proleap.cobol.CobolParser;
import io.proleap.cobol.CobolParser.StartRuleContext;
import io.proleap.cobol.asg.metamodel.Program;
import io.proleap.cobol.asg.params.CobolParserParams;
import io.proleap.cobol.asg.runner.impl.CobolParserRunnerImpl;
import io.proleap.cobol.asg.visitor.ParserVisitor;
import io.proleap.cobol.asg.visitor.impl.CobolCompilationUnitVisitorImpl;

/**
 * ProLeap parser runner that never stops on syntax errors. Errors are collected instead, and the
 * preprocessed source and the AST root are kept, so the AST can still be printed if building the
 * ASG fails afterwards.
 */
public class CollectingParserRunner extends CobolParserRunnerImpl {

	public static class SyntaxError {

		public final int line;

		public final int column;

		public final String message;

		public SyntaxError(final int line, final int column, final String message) {
			this.line = line;
			this.column = column;
			this.message = message;
		}
	}

	protected final List<SyntaxError> syntaxErrors = new ArrayList<SyntaxError>();

	protected String preprocessedInput;

	protected StartRuleContext startRule;

	public StartRuleContext getStartRule() {
		return startRule;
	}

	public String getPreprocessedInput() {
		return preprocessedInput;
	}

	public List<SyntaxError> getSyntaxErrors() {
		return syntaxErrors;
	}

	@Override
	protected void parsePreprocessInput(final String preProcessedInput, final String compilationUnitName,
			final Program program, final CobolParserParams params) throws IOException {
		preprocessedInput = preProcessedInput;

		final BaseErrorListener collector = new BaseErrorListener() {
			@Override
			public void syntaxError(final Recognizer<?, ?> recognizer, final Object offendingSymbol, final int line,
					final int charPositionInLine, final String msg, final RecognitionException e) {
				// ANTLR lists every acceptable token after 'expecting', which can be hundreds
				final int expecting = msg.indexOf(" expecting {");
				final String shortMsg = expecting > 0 && msg.length() - expecting > 120
						? msg.substring(0, expecting + 120) + " ...}"
						: msg;
				syntaxErrors.add(new SyntaxError(line, charPositionInLine, shortMsg));
			}
		};

		final CobolLexer lexer = new CobolLexer(CharStreams.fromString(preProcessedInput));
		lexer.removeErrorListeners();
		lexer.addErrorListener(collector);

		final CommonTokenStream tokens = new CommonTokenStream(lexer);

		final CobolParser parser = new CobolParser(tokens);
		parser.removeErrorListeners();
		parser.addErrorListener(collector);

		startRule = parser.startRule();

		final List<String> lines = splitLines(preProcessedInput);
		final ParserVisitor visitor = new CobolCompilationUnitVisitorImpl(compilationUnitName, lines, tokens, program);

		visitor.visit(startRule);
	}
}
