package local.cobol.facts;

import java.util.ArrayList;
import java.util.List;

import org.antlr.v4.runtime.ParserRuleContext;
import org.antlr.v4.runtime.Token;
import org.antlr.v4.runtime.misc.Interval;
import org.antlr.v4.runtime.tree.ParseTree;
import org.antlr.v4.runtime.tree.TerminalNode;

import io.proleap.cobol.CobolParser;

/** Parse tree helper functions. */
public class Ctx {

	public static <T extends ParserRuleContext> T child(final ParserRuleContext ctx, final Class<T> type) {
		if (ctx == null) {
			return null;
		}
		for (int i = 0; i < ctx.getChildCount(); i++) {
			final ParseTree c = ctx.getChild(i);
			if (type.isInstance(c)) {
				return type.cast(c);
			}
		}
		return null;
	}

	public static <T extends ParserRuleContext> List<T> children(final ParserRuleContext ctx, final Class<T> type) {
		final List<T> result = new ArrayList<T>();
		if (ctx == null) {
			return result;
		}
		for (int i = 0; i < ctx.getChildCount(); i++) {
			final ParseTree c = ctx.getChild(i);
			if (type.isInstance(c)) {
				result.add(type.cast(c));
			}
		}
		return result;
	}

	public static <T extends ParserRuleContext> T first(final ParserRuleContext ctx, final Class<T> type) {
		final List<T> found = collect(ctx, type, false, true);
		return found.isEmpty() ? null : found.get(0);
	}

	public static <T extends ParserRuleContext> List<T> all(final ParserRuleContext ctx, final Class<T> type) {
		return collect(ctx, type, false, false);
	}

	public static <T extends ParserRuleContext> List<T> allOutsideStatements(final ParserRuleContext ctx,
			final Class<T> type) {
		return collect(ctx, type, true, false);
	}

	protected static <T extends ParserRuleContext> List<T> collect(final ParserRuleContext ctx, final Class<T> type,
			final boolean skipStatements, final boolean stopAtFirst) {
		final List<T> result = new ArrayList<T>();
		if (ctx == null) {
			return result;
		}
		final List<ParseTree> stack = new ArrayList<ParseTree>();
		for (int i = ctx.getChildCount() - 1; i >= 0; i--) {
			stack.add(ctx.getChild(i));
		}
		while (!stack.isEmpty()) {
			final ParseTree node = stack.remove(stack.size() - 1);
			if (!(node instanceof ParserRuleContext)) {
				continue;
			}
			if (type.isInstance(node)) {
				result.add(type.cast(node));
				if (stopAtFirst) {
					return result;
				}
			}
			if (skipStatements && node instanceof CobolParser.StatementContext) {
				continue;
			}
			for (int i = node.getChildCount() - 1; i >= 0; i--) {
				stack.add(node.getChild(i));
			}
		}
		return result;
	}

	public static <T extends ParserRuleContext> T ancestor(final ParserRuleContext ctx, final Class<T> type) {
		if (ctx == null) {
			return null;
		}
		ParserRuleContext p = ctx.getParent();
		while (p != null) {
			if (type.isInstance(p)) {
				return type.cast(p);
			}
			p = p.getParent();
		}
		return null;
	}

	public static boolean hasToken(final ParserRuleContext ctx, final int tokenType) {
		if (ctx == null) {
			return false;
		}
		for (int i = 0; i < ctx.getChildCount(); i++) {
			final ParseTree c = ctx.getChild(i);
			if (c instanceof TerminalNode && ((TerminalNode) c).getSymbol().getType() == tokenType) {
				return true;
			}
		}
		return false;
	}

	public static String firstTokenText(final ParserRuleContext ctx) {
		if (ctx == null) {
			return null;
		}
		for (int i = 0; i < ctx.getChildCount(); i++) {
			if (ctx.getChild(i) instanceof TerminalNode) {
				return ctx.getChild(i).getText();
			}
		}
		return null;
	}

	public static String lastTokenText(final ParserRuleContext ctx) {
		if (ctx == null) {
			return null;
		}
		for (int i = ctx.getChildCount() - 1; i >= 0; i--) {
			if (ctx.getChild(i) instanceof TerminalNode) {
				return ctx.getChild(i).getText();
			}
		}
		return null;
	}

	public static String text(final ParserRuleContext ctx) {
		if (ctx == null) {
			return "";
		}
		final Token start = ctx.getStart();
		final Token stop = ctx.getStop();
		if (start == null || stop == null || stop.getStopIndex() < start.getStartIndex()) {
			return "";
		}
		return start.getInputStream().getText(Interval.of(start.getStartIndex(), stop.getStopIndex()));
	}

	public static String compact(final String s) {
		return s.replaceAll("\\*>[^\\n]*", " ").replaceAll("\\s+", " ").trim();
	}

	public static String ctext(final ParserRuleContext ctx) {
		return compact(text(ctx));
	}

	public static String cap(final String s, final int max) {
		return s.length() <= max ? s : s.substring(0, max) + "...";
	}

	public static int startLine(final ParserRuleContext ctx) {
		return ctx == null || ctx.getStart() == null ? -1 : ctx.getStart().getLine();
	}

	public static int endLine(final ParserRuleContext ctx) {
		return ctx == null || ctx.getStop() == null ? startLine(ctx) : ctx.getStop().getLine();
	}

	public static String ruleName(final ParserRuleContext ctx) {
		return CobolParser.ruleNames[ctx.getRuleIndex()];
	}

	public static String unquote(final String s) {
		final String t = s.trim();
		if (t.length() >= 2) {
			final char q = t.charAt(0);
			if ((q == '\'' || q == '"') && t.charAt(t.length() - 1) == q) {
				final String inner = t.substring(1, t.length() - 1);
				return inner.replace("" + q + q, "" + q);
			}
		}
		return t;
	}

	public static String headName(final ParserRuleContext ctx) {
		if (ctx == null) {
			return null;
		}
		CobolParser.QualifiedDataNameFormat1Context q;
		if (ctx instanceof CobolParser.QualifiedDataNameFormat1Context) {
			q = (CobolParser.QualifiedDataNameFormat1Context) ctx;
		} else {
			q = first(ctx, CobolParser.QualifiedDataNameFormat1Context.class);
		}
		if (q != null) {
			ParserRuleContext n = child(q, CobolParser.DataNameContext.class);
			if (n == null) {
				n = child(q, CobolParser.ConditionNameContext.class);
			}
			if (n != null) {
				return n.getText().toUpperCase();
			}
		}
		return ctext(ctx).toUpperCase();
	}

	public static String execText(final ParserRuleContext ctx, final String tag) {
		final List<String> parts = new ArrayList<String>();
		for (int i = 0; i < ctx.getChildCount(); i++) {
			final ParseTree c = ctx.getChild(i);
			if (c instanceof TerminalNode) {
				String t = c.getText();
				if (t.startsWith(tag)) {
					t = t.substring(tag.length());
				}
				t = t.replace("}", "").trim();
				if (!t.isEmpty()) {
					parts.add(t);
				}
			}
		}
		return String.join(" ", parts);
	}
}
