package local.cobol.ast;

import java.io.PrintWriter;

import org.antlr.v4.runtime.ParserRuleContext;
import org.antlr.v4.runtime.Token;
import org.antlr.v4.runtime.tree.ErrorNode;
import org.antlr.v4.runtime.tree.ParseTree;
import org.antlr.v4.runtime.tree.TerminalNode;

import io.proleap.cobol.CobolParser;
import io.proleap.cobol.asg.metamodel.ASGElement;
import io.proleap.cobol.asg.metamodel.Program;
import io.proleap.cobol.asg.metamodel.call.Call;
import io.proleap.cobol.asg.metamodel.call.Call.CallType;

/**
 * Writes the AST as an indented tree, one rule per line.
 *
 * <pre>
 * paragraph @L120
 *   paragraphName > cobolWord  "MAIN-PARA"
 *   sentence @L121
 *     ...
 * </pre>
 *
 * Line numbers (@L) refer to the preprocessed source. With collapse enabled, chains of rules that
 * have a single rule child are printed on one line joined by '>'. Rules whose children are all
 * tokens show the tokens on the same line. Names the ASG could not resolve are marked [UNRESOLVED],
 * rules the parser had to recover from are marked !! SYNTAX ERROR.
 */
public class AstPrinter {

	protected final Program program;

	protected final boolean collapse;

	protected final PrintWriter out;

	public AstPrinter(final PrintWriter out, final Program program, final boolean collapse) {
		this.out = out;
		this.program = program;
		this.collapse = collapse;
	}

	protected boolean allChildrenAreTokens(final ParseTree node) {
		for (int i = 0; i < node.getChildCount(); i++) {
			if (!(node.getChild(i) instanceof TerminalNode)) {
				return false;
			}
		}

		return true;
	}

	protected boolean isUnresolved(final ParseTree node) {
		if (program == null) {
			return false;
		}

		final ASGElement element = program.getASGElementRegistry().getASGElement(node);
		return element instanceof Call && ((Call) element).getCallType() == CallType.UNDEFINED_CALL;
	}

	public void print(final ParseTree node, final int depth) {
		final String indent = "  ".repeat(depth);

		if (node instanceof ErrorNode) {
			out.println(indent + "!! SYNTAX ERROR at " + tokenText((TerminalNode) node));
			return;
		}

		if (node instanceof TerminalNode) {
			final Token token = ((TerminalNode) node).getSymbol();

			if (token.getType() != Token.EOF) {
				out.println(indent + tokenText((TerminalNode) node));
			}
			return;
		}

		final StringBuilder line = new StringBuilder(indent);
		ParseTree current = node;
		boolean unresolved = isUnresolved(current);
		line.append(ruleName(current));

		while (collapse && current.getChildCount() == 1 && current.getChild(0) instanceof ParserRuleContext) {
			current = current.getChild(0);
			unresolved |= isUnresolved(current);
			line.append(" > ").append(ruleName(current));
		}

		line.append(" @L").append(((ParserRuleContext) node).getStart().getLine());

		if (unresolved) {
			line.append("  [UNRESOLVED]");
		}

		// the parser recovered from a syntax error inside this rule
		if (((ParserRuleContext) current).exception != null) {
			line.append("  !! SYNTAX ERROR");
		}

		if (allChildrenAreTokens(current)) {
			for (int i = 0; i < current.getChildCount(); i++) {
				final TerminalNode terminal = (TerminalNode) current.getChild(i);

				if (terminal.getSymbol().getType() != Token.EOF) {
					line.append("  ").append(tokenText(terminal));
				}
			}

			out.println(line);
		} else {
			out.println(line);

			for (int i = 0; i < current.getChildCount(); i++) {
				print(current.getChild(i), depth + 1);
			}
		}
	}

	protected String ruleName(final ParseTree node) {
		return CobolParser.ruleNames[((ParserRuleContext) node).getRuleIndex()];
	}

	protected String tokenText(final TerminalNode terminal) {
		// some tokens (e.g. the separator period) carry the following whitespace and newline
		final String text = terminal.getText().strip().replace("\r", "").replace("\n", "\\n");
		return "\"" + text + "\"";
	}
}
