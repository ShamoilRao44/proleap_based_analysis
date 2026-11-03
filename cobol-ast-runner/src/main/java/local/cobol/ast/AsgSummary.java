package local.cobol.ast;

import java.io.PrintWriter;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.IdentityHashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;

import org.antlr.v4.runtime.ParserRuleContext;
import org.antlr.v4.runtime.tree.ParseTree;

import io.proleap.cobol.asg.metamodel.ASGElement;
import io.proleap.cobol.asg.metamodel.Program;
import io.proleap.cobol.asg.metamodel.ProgramUnit;
import io.proleap.cobol.asg.metamodel.call.Call;
import io.proleap.cobol.asg.metamodel.call.Call.CallType;
import io.proleap.cobol.asg.metamodel.data.datadescription.DataDescriptionEntry;
import io.proleap.cobol.asg.metamodel.identification.IdentificationDivision;
import io.proleap.cobol.asg.metamodel.procedure.Paragraph;
import io.proleap.cobol.asg.metamodel.procedure.Section;
import io.proleap.cobol.asg.metamodel.procedure.Statement;
import io.proleap.cobol.asg.metamodel.procedure.call.CallStatement;
import io.proleap.cobol.asg.metamodel.procedure.execcics.ExecCicsStatement;
import io.proleap.cobol.asg.metamodel.procedure.execsql.ExecSqlStatement;

/**
 * Collects facts from the ASG by walking the AST and looking up the ASG element registered for each
 * node: program ids, data items, sections, paragraphs, statement counts, CALL targets, EXEC CICS /
 * EXEC SQL blocks and names that could not be resolved (typically defined in a missing copybook).
 */
public class AsgSummary {

	public static class Item {

		public final String text;

		public final int line;

		public Item(final String text, final int line) {
			this.text = text;
			this.line = line;
		}
	}

	protected static final int MAX_LINES_PER_NAME = 10;

	public final List<String> programIds = new ArrayList<String>();

	public final List<Item> topLevelDataItems = new ArrayList<Item>();

	public int dataItemCount;

	public final List<Item> sections = new ArrayList<Item>();

	public final List<Item> paragraphs = new ArrayList<Item>();

	public final Map<String, Integer> statementCounts = new TreeMap<String, Integer>();

	public final List<Item> callTargets = new ArrayList<Item>();

	public final List<Item> execCics = new ArrayList<Item>();

	public final List<Item> execSql = new ArrayList<Item>();

	/** unresolved name (upper case) -> lines where it is used */
	public final Map<String, List<Integer>> unresolvedNames = new TreeMap<String, List<Integer>>();

	protected final Set<ASGElement> seen = Collections.newSetFromMap(new IdentityHashMap<ASGElement, Boolean>());

	protected final Set<Integer> unresolvedTokens = new HashSet<Integer>();

	public static AsgSummary of(final Program program, final ParseTree root) {
		final AsgSummary result = new AsgSummary();
		result.walk(program, root);
		return result;
	}

	protected static String compact(final String text) {
		return text == null ? "" : text.replaceAll("\\s+", " ").trim();
	}

	protected static int lineOf(final ASGElement element) {
		final ParserRuleContext ctx = element.getCtx();
		return ctx == null || ctx.getStart() == null ? -1 : ctx.getStart().getLine();
	}

	protected void collect(final ASGElement element) {
		final int line = lineOf(element);

		if (element instanceof ProgramUnit) {
			final IdentificationDivision identificationDivision = ((ProgramUnit) element).getIdentificationDivision();

			if (identificationDivision != null && identificationDivision.getProgramIdParagraph() != null) {
				programIds.add(identificationDivision.getProgramIdParagraph().getName());
			}
		} else if (element instanceof DataDescriptionEntry) {
			final DataDescriptionEntry entry = (DataDescriptionEntry) element;
			dataItemCount++;

			final Integer level = entry.getLevelNumber();

			if (level != null && (level == 1 || level == DataDescriptionEntry.LEVEL_NUMBER_SCALAR)) {
				topLevelDataItems.add(new Item(String.format("%02d %s", level, entry.getName()), line));
			}
		} else if (element instanceof Section) {
			sections.add(new Item(((Section) element).getName(), line));
		} else if (element instanceof Paragraph) {
			paragraphs.add(new Item(((Paragraph) element).getName(), line));
		} else if (element instanceof Call && ((Call) element).getCallType() == CallType.UNDEFINED_CALL) {
			// the parser registers one undefined call per nesting level (identifier > dataName > ...),
			// so count each use once, by the position of its first token
			final ParserRuleContext ctx = element.getCtx();

			if (ctx != null && ctx.getStart() != null && unresolvedTokens.add(ctx.getStart().getTokenIndex())) {
				final String name = String.valueOf(((Call) element).getName()).toUpperCase();
				unresolvedNames.computeIfAbsent(name, k -> new ArrayList<Integer>()).add(line);
			}
		}

		if (element instanceof Statement) {
			final Statement statement = (Statement) element;
			statementCounts.merge(String.valueOf(statement.getStatementType()), 1, Integer::sum);

			if (statement instanceof CallStatement) {
				final CallStatement callStatement = (CallStatement) statement;
				final String target = callStatement.getProgramValueStmt() == null ? "?"
						: callStatement.getProgramValueStmt().getCtx().getText();
				callTargets.add(new Item(target, line));
			} else if (statement instanceof ExecCicsStatement) {
				execCics.add(new Item(compact(((ExecCicsStatement) statement).getExecCicsText()), line));
			} else if (statement instanceof ExecSqlStatement) {
				execSql.add(new Item(compact(((ExecSqlStatement) statement).getExecSqlText()), line));
			}
		}
	}

	protected void walk(final Program program, final ParseTree root) {
		final List<ParseTree> stack = new ArrayList<ParseTree>();
		stack.add(root);

		// iterative depth-first walk, children pushed in reverse to keep source order
		while (!stack.isEmpty()) {
			final ParseTree node = stack.remove(stack.size() - 1);
			final ASGElement element = program.getASGElementRegistry().getASGElement(node);

			if (element != null && seen.add(element)) {
				collect(element);
			}

			for (int i = node.getChildCount() - 1; i >= 0; i--) {
				stack.add(node.getChild(i));
			}
		}
	}

	public void write(final PrintWriter out, final Map<String, String> header, final List<String> emptyCopybooks,
			final List<CollectingParserRunner.SyntaxError> syntaxErrors, final String asgError) {
		out.println("COBOL AST / ASG SUMMARY");
		out.println("=======================");

		for (final Map.Entry<String, String> entry : header.entrySet()) {
			out.println(String.format("%-20s: %s", entry.getKey(), entry.getValue()));
		}

		out.println();
		out.println("Line numbers refer to the preprocessed source (*.preprocessed.cbl).");

		section(out, "SYNTAX ERRORS (" + syntaxErrors.size() + ")");
		if (syntaxErrors.isEmpty()) {
			out.println("  none");
		}
		for (final CollectingParserRunner.SyntaxError error : syntaxErrors) {
			out.println(String.format("  L%-6d col %-4d %s", error.line, error.column, error.message));
		}

		if (asgError != null) {
			section(out, "ASG ANALYSIS FAILED");
			out.println("  " + asgError);
			out.println("  The AST was still written. The facts below may be incomplete.");
		}

		section(out, "EMPTY COPYBOOKS / STUBS (" + emptyCopybooks.size() + ")");
		if (emptyCopybooks.isEmpty()) {
			out.println("  none");
		}
		for (final String name : emptyCopybooks) {
			out.println("  " + name);
		}

		section(out, "PROGRAM");
		out.println("  program-id(s)      : " + String.join(", ", programIds));
		out.println("  data items         : " + dataItemCount);
		out.println("  sections           : " + sections.size());
		out.println("  paragraphs         : " + paragraphs.size());
		out.println("  statements         : " + statementCounts.values().stream().mapToInt(Integer::intValue).sum());

		section(out, "UNRESOLVED NAMES (" + unresolvedNames.size() + ")");
		out.println("  Data names / paragraphs used but not defined. Usually defined in a missing or stubbed copybook.");
		for (final Map.Entry<String, List<Integer>> entry : unresolvedNames.entrySet()) {
			final List<Integer> lines = entry.getValue();
			final List<Integer> shown = lines.subList(0, Math.min(lines.size(), MAX_LINES_PER_NAME));
			out.println(String.format("  %-30s %3dx  lines %s%s", entry.getKey(), lines.size(), shown,
					lines.size() > shown.size() ? " ..." : ""));
		}

		items(out, "CALL TARGETS", callTargets);
		items(out, "EXEC CICS", execCics);
		items(out, "EXEC SQL", execSql);

		section(out, "STATEMENT COUNTS");
		final Map<String, Integer> sortedCounts = new LinkedHashMap<String, Integer>();
		statementCounts.entrySet().stream().sorted(Map.Entry.<String, Integer>comparingByValue().reversed())
				.forEach(e -> sortedCounts.put(e.getKey(), e.getValue()));
		for (final Map.Entry<String, Integer> entry : sortedCounts.entrySet()) {
			out.println(String.format("  %-30s %d", entry.getKey(), entry.getValue()));
		}

		items(out, "TOP-LEVEL DATA ITEMS (01 / 77)", topLevelDataItems);
		items(out, "SECTIONS", sections);
		items(out, "PARAGRAPHS", paragraphs);
	}

	protected void items(final PrintWriter out, final String title, final List<Item> items) {
		section(out, title + " (" + items.size() + ")");

		for (final Item item : items) {
			out.println(String.format("  L%-6d %s", item.line, item.text));
		}
	}

	protected void section(final PrintWriter out, final String title) {
		out.println();
		out.println(title);
		out.println("-".repeat(title.length()));
	}
}
