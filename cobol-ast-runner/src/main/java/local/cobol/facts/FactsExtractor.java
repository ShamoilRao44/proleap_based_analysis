package local.cobol.facts;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.IdentityHashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;

import org.antlr.v4.runtime.ParserRuleContext;

import io.proleap.cobol.CobolLexer;
import io.proleap.cobol.CobolParser;
import io.proleap.cobol.CobolParser.*;

/** Extracts raw facts (STEP2_BUILD_PLAN.md section 5) from the ProLeap parse tree. */
public class FactsExtractor {

	protected final StartRuleContext root;

	/** statement context -> statement id */
	protected final Map<ParserRuleContext, Integer> stmtIds = new IdentityHashMap<ParserRuleContext, Integer>();

	/** statement id -> the specific statement context (child 0 of StatementContext) */
	protected final Map<Integer, ParserRuleContext> stmtById = new HashMap<Integer, ParserRuleContext>();

	public FactsExtractor(final StartRuleContext root) {
		this.root = root;
	}

	// ------------------------------------------------------------------ helpers

	protected static String up(final String s) {
		return s == null ? null : s.toUpperCase();
	}

	protected static String nameOf(final ParserRuleContext c) {
		return c == null ? null : c.getText().toUpperCase();
	}

	protected static ParserRuleContext firstRuleChild(final ParserRuleContext c) {
		if (c != null && c.getChildCount() > 0 && c.getChild(0) instanceof ParserRuleContext) {
			return (ParserRuleContext) c.getChild(0);
		}
		return null;
	}

	protected List<Integer> range(final ParserRuleContext ctx) {
		if (ctx == null) {
			return null;
		}
		final List<Integer> r = new ArrayList<Integer>();
		r.add(Ctx.startLine(ctx));
		r.add(Ctx.endLine(ctx));
		return r;
	}

	protected String enclosingSection(final ParserRuleContext ctx) {
		ParserRuleContext p = ctx.getParent();
		while (p != null) {
			if (p instanceof ProcedureSectionContext || p instanceof ProcedureDeclarativeContext) {
				final ProcedureSectionHeaderContext h = Ctx.child(p, ProcedureSectionHeaderContext.class);
				return nameOf(Ctx.child(h, SectionNameContext.class));
			}
			p = p.getParent();
		}
		return null;
	}

	protected String enclosingParagraph(final ParserRuleContext ctx) {
		final ParagraphContext p = Ctx.ancestor(ctx, ParagraphContext.class);
		return p == null ? null : nameOf(Ctx.child(p, ParagraphNameContext.class));
	}

	protected String procName(final ProcedureNameContext p) {
		final ParagraphNameContext para = Ctx.child(p, ParagraphNameContext.class);
		if (para != null) {
			return nameOf(para);
		}
		return nameOf(Ctx.child(p, SectionNameContext.class));
	}

	// ------------------------------------------------------------------ main

	public Map<String, Object> extract() {
		final Map<String, Object> out = new LinkedHashMap<String, Object>();

		final List<String> ids = new ArrayList<String>();
		for (final ProgramIdParagraphContext p : Ctx.all(root, ProgramIdParagraphContext.class)) {
			final ProgramNameContext n = Ctx.child(p, ProgramNameContext.class);
			if (n != null) {
				ids.add(Ctx.unquote(n.getText()).toUpperCase());
			}
		}
		out.put("program_ids", ids);

		final DataDivisionContext dataDivision = Ctx.first(root, DataDivisionContext.class);
		final ProcedureDivisionContext procDivision = Ctx.first(root, ProcedureDivisionContext.class);

		final Map<String, Object> divisions = new LinkedHashMap<String, Object>();
		divisions.put("identification", range(Ctx.first(root, IdentificationDivisionContext.class)));
		divisions.put("environment", range(Ctx.first(root, EnvironmentDivisionContext.class)));
		divisions.put("data", range(dataDivision));
		divisions.put("procedure", range(procDivision));
		out.put("divisions", divisions);

		final List<Object> dataSections = new ArrayList<Object>();
		final List<Object> dataItems = new ArrayList<Object>();
		extractData(dataDivision, dataSections, dataItems);
		out.put("data_sections", dataSections);

		out.put("selects", extractSelects());
		out.put("fds", extractFds());
		out.put("data_items", dataItems);
		out.put("data_exec_sql", extractDataExecSql(dataDivision));

		final List<String> using = new ArrayList<String>();
		final ProcedureDivisionUsingClauseContext usingClause = Ctx.first(procDivision,
				ProcedureDivisionUsingClauseContext.class);
		if (usingClause != null) {
			for (final QualifiedDataNameFormat1Context q : Ctx.all(usingClause,
					QualifiedDataNameFormat1Context.class)) {
				using.add(Ctx.headName(q));
			}
		}
		out.put("procedure_using", using);

		final List<Object> sections = new ArrayList<Object>();
		final List<Object> paragraphs = new ArrayList<Object>();
		final List<StatementContext> statements = new ArrayList<StatementContext>();

		for (final ParserRuleContext c : Ctx.all(procDivision, ParserRuleContext.class)) {
			if (c instanceof ProcedureSectionContext || c instanceof ProcedureDeclarativeContext) {
				final Map<String, Object> s = new LinkedHashMap<String, Object>();
				final ProcedureSectionHeaderContext h = Ctx.child(c, ProcedureSectionHeaderContext.class);
				s.put("name", nameOf(Ctx.child(h, SectionNameContext.class)));
				s.put("start", Ctx.startLine(c));
				s.put("end", Ctx.endLine(c));
				s.put("declaratives", c instanceof ProcedureDeclarativeContext);
				sections.add(s);
			} else if (c instanceof ParagraphContext) {
				final Map<String, Object> p = new LinkedHashMap<String, Object>();
				p.put("name", nameOf(Ctx.child(c, ParagraphNameContext.class)));
				p.put("section", enclosingSection(c));
				p.put("declaratives", Ctx.ancestor(c, ProcedureDeclarativesContext.class) != null);
				p.put("start", Ctx.startLine(c));
				p.put("end", Ctx.endLine(c));
				paragraphs.add(p);
			} else if (c instanceof StatementContext) {
				statements.add((StatementContext) c);
			}
		}
		out.put("sections", sections);
		out.put("paragraphs", paragraphs);
		out.put("statements", extractStatements(statements));
		return out;
	}

	// ------------------------------------------------------------------ data

	protected void extractData(final DataDivisionContext dataDivision, final List<Object> dataSections,
			final List<Object> dataItems) {
		if (dataDivision == null) {
			return;
		}
		final int[] counter = new int[1];

		for (final DataDivisionSectionContext ds : Ctx.children(dataDivision, DataDivisionSectionContext.class)) {
			final ParserRuleContext s = firstRuleChild(ds);
			if (s == null) {
				continue;
			}
			final String kind;
			if (s instanceof FileSectionContext) {
				kind = "FILE";
			} else if (s instanceof WorkingStorageSectionContext) {
				kind = "WORKING-STORAGE";
			} else if (s instanceof LocalStorageSectionContext) {
				kind = "LOCAL-STORAGE";
			} else if (s instanceof LinkageSectionContext) {
				kind = "LINKAGE";
			} else {
				kind = "OTHER";
			}

			final Map<String, Object> sec = new LinkedHashMap<String, Object>();
			sec.put("kind", kind);
			sec.put("start", Ctx.startLine(s));
			sec.put("end", Ctx.endLine(s));
			dataSections.add(sec);

			if (s instanceof FileSectionContext) {
				for (final FileDescriptionEntryContext fd : Ctx.children(s, FileDescriptionEntryContext.class)) {
					final String fdName = nameOf(Ctx.child(fd, FileNameContext.class));
					for (final DataDescriptionEntryContext e : Ctx.children(fd, DataDescriptionEntryContext.class)) {
						addItem(e, kind, fdName, counter, dataItems);
					}
				}
			} else {
				for (final DataDescriptionEntryContext e : Ctx.children(s, DataDescriptionEntryContext.class)) {
					addItem(e, kind, null, counter, dataItems);
				}
			}
		}
	}

	protected void addItem(final DataDescriptionEntryContext e, final String section, final String fd,
			final int[] counter, final List<Object> dataItems) {
		final ParserRuleContext d = firstRuleChild(e);
		if (d == null || d instanceof DataDescriptionEntryExecSqlContext) {
			return;
		}
		final boolean f1 = d instanceof DataDescriptionEntryFormat1Context;
		final boolean f2 = d instanceof DataDescriptionEntryFormat2Context;
		final boolean f3 = d instanceof DataDescriptionEntryFormat3Context;
		if (!f1 && !f2 && !f3) {
			return;
		}

		final Map<String, Object> m = new LinkedHashMap<String, Object>();
		m.put("id", ++counter[0]);

		try {
			int level;
			String name;
			if (f1) {
				try {
					level = Integer.parseInt(Ctx.firstTokenText(d));
				} catch (final NumberFormatException | NullPointerException ex) {
					level = -1;
				}
				final DataNameContext dn = Ctx.child(d, DataNameContext.class);
				name = dn != null ? nameOf(dn) : (Ctx.hasToken(d, CobolLexer.FILLER) ? "FILLER" : null);
			} else if (f3) {
				level = 88;
				name = nameOf(Ctx.child(d, ConditionNameContext.class));
			} else {
				level = 66;
				name = nameOf(Ctx.child(d, DataNameContext.class));
			}
			m.put("level", level);
			m.put("name", name);
			m.put("section", section);
			m.put("fd", fd);

			String pic = null;
			String usage = null;
			Object values = null;
			Object occurs = null;
			String redefines = null;
			String sign = null;
			boolean sync = false;
			boolean justified = false;
			boolean blank = false;
			String renames = null;

			if (f1) {
				final DataPictureClauseContext pc = Ctx.child(d, DataPictureClauseContext.class);
				if (pc != null) {
					final PictureStringContext ps = Ctx.child(pc, PictureStringContext.class);
					pic = ps == null ? null : ps.getText().toUpperCase();
				}
				final DataUsageClauseContext uc = Ctx.child(d, DataUsageClauseContext.class);
				usage = uc == null ? null : up(Ctx.lastTokenText(uc));
				values = values(Ctx.child(d, DataValueClauseContext.class));
				occurs = occurs(Ctx.child(d, DataOccursClauseContext.class));
				final DataRedefinesClauseContext rc = Ctx.child(d, DataRedefinesClauseContext.class);
				redefines = rc == null ? null : nameOf(Ctx.child(rc, DataNameContext.class));
				final DataSignClauseContext sc = Ctx.child(d, DataSignClauseContext.class);
				sign = sc == null ? null : Ctx.ctext(sc).toUpperCase();
				sync = Ctx.child(d, DataSynchronizedClauseContext.class) != null;
				justified = Ctx.child(d, DataJustifiedClauseContext.class) != null;
				blank = Ctx.child(d, DataBlankWhenZeroClauseContext.class) != null;
			} else if (f3) {
				values = values(Ctx.child(d, DataValueClauseContext.class));
			} else {
				final DataRenamesClauseContext rn = Ctx.child(d, DataRenamesClauseContext.class);
				renames = rn == null ? null : Ctx.ctext(rn).toUpperCase();
			}

			m.put("pic", pic);
			m.put("usage", usage);
			m.put("values", values);
			m.put("occurs", occurs);
			m.put("redefines", redefines);
			m.put("sign", sign);
			m.put("sync", sync);
			m.put("justified", justified);
			m.put("blank_when_zero", blank);
			m.put("renames", renames);
		} catch (final RuntimeException ex) {
			m.put("extract_error", ex.toString());
		}
		m.put("pline", Ctx.startLine(e));
		m.put("pline_end", Ctx.endLine(e));
		dataItems.add(m);
	}

	protected List<Object> values(final DataValueClauseContext clause) {
		if (clause == null) {
			return null;
		}
		final List<Object> result = new ArrayList<Object>();
		for (final DataValueIntervalContext iv : Ctx.all(clause, DataValueIntervalContext.class)) {
			final Map<String, Object> v = new LinkedHashMap<String, Object>();
			v.put("from", Ctx.text(Ctx.child(iv, DataValueIntervalFromContext.class)));
			final DataValueIntervalToContext to = Ctx.child(iv, DataValueIntervalToContext.class);
			v.put("thru", to == null ? null : Ctx.text(Ctx.child(to, LiteralContext.class)));
			result.add(v);
		}
		return result;
	}

	protected Map<String, Object> occurs(final DataOccursClauseContext clause) {
		if (clause == null) {
			return null;
		}
		int n = 1;
		final IntegerLiteralContext first = Ctx.child(clause, IntegerLiteralContext.class);
		if (first != null) {
			try {
				n = Integer.parseInt(first.getText());
			} catch (final NumberFormatException ex) {
				n = 1;
			}
		}
		int max = n;
		final DataOccursToContext to = Ctx.child(clause, DataOccursToContext.class);
		if (to != null) {
			final IntegerLiteralContext tl = Ctx.child(to, IntegerLiteralContext.class);
			if (tl != null) {
				try {
					max = Integer.parseInt(tl.getText());
				} catch (final NumberFormatException ex) {
					max = n;
				}
			}
		}
		final Map<String, Object> o = new LinkedHashMap<String, Object>();
		o.put("min", n);
		o.put("max", max);
		final DataOccursDependingContext dep = Ctx.child(clause, DataOccursDependingContext.class);
		o.put("depending", dep == null ? null : Ctx.headName(Ctx.first(dep, QualifiedDataNameContext.class)));
		final List<String> idx = new ArrayList<String>();
		for (final IndexNameContext in : Ctx.all(clause, IndexNameContext.class)) {
			idx.add(in.getText().toUpperCase());
		}
		o.put("indexed_by", idx);
		return o;
	}

	protected List<Object> extractDataExecSql(final DataDivisionContext dataDivision) {
		final List<Object> result = new ArrayList<Object>();
		for (final DataDescriptionEntryExecSqlContext c : Ctx.all(dataDivision,
				DataDescriptionEntryExecSqlContext.class)) {
			final Map<String, Object> m = new LinkedHashMap<String, Object>();
			m.put("exec_text", Ctx.execText(c, "*>EXECSQL"));
			m.put("pline", Ctx.startLine(c));
			m.put("pline_end", Ctx.endLine(c));
			result.add(m);
		}
		return result;
	}

	protected List<Object> extractSelects() {
		final List<Object> result = new ArrayList<Object>();
		for (final FileControlEntryContext f : Ctx.all(root, FileControlEntryContext.class)) {
			final Map<String, Object> m = new LinkedHashMap<String, Object>();
			final SelectClauseContext sel = Ctx.child(f, SelectClauseContext.class);
			m.put("file", nameOf(Ctx.child(sel, FileNameContext.class)));

			String assign = null;
			boolean literal = false;
			final AssignClauseContext ac = Ctx.first(f, AssignClauseContext.class);
			if (ac != null) {
				final AssignmentNameContext an = Ctx.first(ac, AssignmentNameContext.class);
				final LiteralContext lit = Ctx.child(ac, LiteralContext.class);
				if (an != null) {
					assign = an.getText().toUpperCase();
				} else if (lit != null) {
					assign = Ctx.unquote(lit.getText()).toUpperCase();
					literal = true;
				} else {
					assign = up(Ctx.lastTokenText(ac));
				}
			}
			m.put("assign", assign);
			m.put("assign_is_literal", literal);

			final OrganizationClauseContext oc = Ctx.first(f, OrganizationClauseContext.class);
			String org = null;
			if (oc != null) {
				org = Ctx.ctext(oc).toUpperCase().replaceFirst("^ORGANIZATION\\s+", "").replaceFirst("^IS\\s+", "");
			}
			m.put("organization", org);

			final AccessModeClauseContext am = Ctx.first(f, AccessModeClauseContext.class);
			String access = null;
			if (am != null) {
				final String[] words = Ctx.ctext(am).toUpperCase().split("\\s+");
				access = words[words.length - 1];
			}
			m.put("access", access);

			final RecordKeyClauseContext rk = Ctx.first(f, RecordKeyClauseContext.class);
			m.put("record_key", rk == null ? null : Ctx.headName(Ctx.first(rk, QualifiedDataNameContext.class)));

			final FileStatusClauseContext fs = Ctx.first(f, FileStatusClauseContext.class);
			m.put("file_status", fs == null ? null : Ctx.headName(Ctx.first(fs, QualifiedDataNameContext.class)));
			m.put("pline", Ctx.startLine(f));
			result.add(m);
		}
		return result;
	}

	protected List<Object> extractFds() {
		final List<Object> result = new ArrayList<Object>();
		for (final FileDescriptionEntryContext fd : Ctx.all(root, FileDescriptionEntryContext.class)) {
			final Map<String, Object> m = new LinkedHashMap<String, Object>();
			m.put("file", nameOf(Ctx.child(fd, FileNameContext.class)));
			m.put("kind", up(Ctx.firstTokenText(fd)));
			m.put("pline", Ctx.startLine(fd));
			result.add(m);
		}
		return result;
	}

	// ------------------------------------------------------------------ statements

	protected List<Object> extractStatements(final List<StatementContext> statements) {
		final List<Object> result = new ArrayList<Object>();
		int next = 0;

		for (final StatementContext s : statements) {
			final ParserRuleContext x = firstRuleChild(s);
			if (x == null) {
				continue;
			}
			final int id = ++next;
			stmtIds.put(s, id);
			stmtById.put(id, x);

			final Map<String, Object> m = new LinkedHashMap<String, Object>();
			m.put("id", id);
			String type = Ctx.ruleName(x);
			if (type.endsWith("Statement")) {
				type = type.substring(0, type.length() - "Statement".length());
			}
			m.put("type", type);
			m.put("pline", Ctx.startLine(x));
			m.put("pline_end", Ctx.endLine(x));
			m.put("paragraph", enclosingParagraph(s));
			m.put("section", enclosingSection(s));

			Integer parentId = null;
			StatementContext parentStmt = Ctx.ancestor(s, StatementContext.class);
			if (parentStmt != null) {
				parentId = stmtIds.get(parentStmt);
			}
			m.put("parent", parentId);
			m.put("branch", parentId == null ? null : branch(s, stmtById.get(parentId)));

			String text;
			String execText = null;
			if (x instanceof ExecCicsStatementContext) {
				execText = Ctx.execText(x, "*>EXECCICS");
			} else if (x instanceof ExecSqlStatementContext) {
				execText = Ctx.execText(x, "*>EXECSQL");
			} else if (x instanceof ExecSqlImsStatementContext) {
				execText = Ctx.execText(x, "*>EXECSQLIMS");
			}
			text = execText != null ? Ctx.cap(execText, 300) : Ctx.cap(Ctx.ctext(x), 300);
			m.put("text", text);

			final Set<String> reads = new TreeSet<String>();
			final Set<String> writes = new TreeSet<String>();
			try {
				refs(x, reads, writes);
			} catch (final RuntimeException ex) {
				m.put("extract_error", ex.toString());
			}
			m.put("reads", new ArrayList<String>(reads));
			m.put("writes", new ArrayList<String>(writes));

			try {
				typeFields(type, x, execText, m);
			} catch (final RuntimeException ex) {
				m.put("extract_error", ex.toString());
			}
			result.add(m);
		}
		return result;
	}

	protected String branch(final StatementContext s, final ParserRuleContext p) {
		ParserRuleContext node = s;
		while (node.getParent() != null && node.getParent() != p) {
			node = node.getParent();
		}
		if (node.getParent() == null) {
			return null;
		}
		if (node instanceof IfThenContext) {
			return "then";
		}
		if (node instanceof IfElseContext) {
			return "else";
		}
		if (node instanceof EvaluateWhenPhraseContext) {
			return "when:" + Ctx.children(p, EvaluateWhenPhraseContext.class).indexOf(node);
		}
		if (node instanceof EvaluateWhenOtherContext) {
			return "other";
		}
		if (node instanceof PerformInlineStatementContext) {
			return "inline";
		}
		if (node instanceof SearchWhenContext) {
			return "when:" + Ctx.children(p, SearchWhenContext.class).indexOf(node);
		}
		return Ctx.ruleName(node);
	}

	protected static boolean isWriteContext(final ParserRuleContext n) {
		return n instanceof ComputeStoreContext || n instanceof AddToContext || n instanceof AddGivingContext
				|| n instanceof SubtractMinuendContext || n instanceof SubtractGivingContext
				|| n instanceof MultiplyRegularOperandContext || n instanceof MultiplyGivingResultContext
				|| n instanceof DivideIntoContext || n instanceof DivideGivingContext
				|| n instanceof DivideRemainderContext || n instanceof SetToContext || n instanceof ReadIntoContext
				|| n instanceof StringIntoPhraseContext || n instanceof UnstringIntoContext;
	}

	protected void refs(final ParserRuleContext x, final Set<String> reads, final Set<String> writes) {
		for (final QualifiedDataNameFormat1Context q : Ctx.allOutsideStatements(x,
				QualifiedDataNameFormat1Context.class)) {
			final String name = Ctx.headName(q);
			if (name == null || name.isEmpty()) {
				continue;
			}
			boolean write = false;
			ParserRuleContext n = q.getParent();
			while (n != null && n != x) {
				if (n instanceof SubscriptContext || n instanceof ReferenceModifierContext) {
					break;
				}
				if (isWriteContext(n)) {
					write = true;
					break;
				}
				if (n instanceof IdentifierContext) {
					final ParserRuleContext par = n.getParent();
					if (par instanceof MoveToStatementContext || par instanceof MoveCorrespondingToStatementContext
							|| par instanceof InitializeStatementContext || par instanceof AcceptStatementContext) {
						write = true;
						break;
					}
				}
				n = n.getParent();
			}
			if (write) {
				writes.add(name);
			} else {
				reads.add(name);
			}
		}
	}

	protected void typeFields(final String type, final ParserRuleContext x, final String execText,
			final Map<String, Object> m) {
		switch (type) {
		case "perform": {
			final PerformInlineStatementContext inline = Ctx.child(x, PerformInlineStatementContext.class);
			final PerformProcedureStatementContext proc = Ctx.child(x, PerformProcedureStatementContext.class);
			m.put("inline", inline != null);
			String target = null;
			String thru = null;
			if (proc != null) {
				final List<ProcedureNameContext> names = Ctx.children(proc, ProcedureNameContext.class);
				if (names.size() > 0) {
					target = procName(names.get(0));
				}
				if (names.size() > 1) {
					thru = procName(names.get(1));
				}
			}
			m.put("target", target);
			m.put("thru", thru);
			final ParserRuleContext holder = inline != null ? inline : proc;
			final PerformTypeContext pt = Ctx.child(holder, PerformTypeContext.class);
			String performType = null;
			String until = null;
			if (pt != null) {
				if (Ctx.child(pt, PerformTimesContext.class) != null) {
					performType = "times";
				} else if (Ctx.child(pt, PerformUntilContext.class) != null) {
					performType = "until";
					until = Ctx.ctext(Ctx.first(Ctx.child(pt, PerformUntilContext.class), ConditionContext.class));
				} else if (Ctx.child(pt, PerformVaryingContext.class) != null) {
					performType = "varying";
					final ConditionContext cc = Ctx.first(Ctx.child(pt, PerformVaryingContext.class),
							ConditionContext.class);
					until = cc == null ? null : Ctx.ctext(cc);
				}
			}
			m.put("perform_type", performType);
			m.put("until", until);
			break;
		}
		case "goTo": {
			final List<String> targets = new ArrayList<String>();
			for (final ProcedureNameContext p : Ctx.all(x, ProcedureNameContext.class)) {
				targets.add(procName(p));
			}
			m.put("targets", targets);
			final GoToDependingOnStatementContext dep = Ctx.first(x, GoToDependingOnStatementContext.class);
			final IdentifierContext id = dep == null ? null : Ctx.child(dep, IdentifierContext.class);
			m.put("depending", id == null ? null : Ctx.ctext(id));
			break;
		}
		case "call": {
			final LiteralContext lit = Ctx.child(x, LiteralContext.class);
			final IdentifierContext id = Ctx.child(x, IdentifierContext.class);
			if (lit != null) {
				m.put("target_literal", Ctx.unquote(lit.getText()).toUpperCase());
				m.put("target_var", null);
				m.put("target_text", Ctx.ctext(lit));
			} else {
				m.put("target_literal", null);
				m.put("target_var", id == null ? null : Ctx.headName(id));
				m.put("target_text", id == null ? null : Ctx.ctext(id));
			}
			final List<Object> using = new ArrayList<Object>();
			final CallUsingPhraseContext up = Ctx.child(x, CallUsingPhraseContext.class);
			if (up != null) {
				for (final CallUsingParameterContext param : Ctx.children(up, CallUsingParameterContext.class)) {
					for (int i = 0; i < param.getChildCount(); i++) {
						if (!(param.getChild(i) instanceof ParserRuleContext)) {
							continue;
						}
						final ParserRuleContext phrase = (ParserRuleContext) param.getChild(i);
						String mode;
						List<? extends ParserRuleContext> its;
						if (phrase instanceof CallByReferencePhraseContext) {
							mode = "reference";
							its = Ctx.children(phrase, CallByReferenceContext.class);
						} else if (phrase instanceof CallByValuePhraseContext) {
							mode = "value";
							its = Ctx.children(phrase, CallByValueContext.class);
						} else if (phrase instanceof CallByContentPhraseContext) {
							mode = "content";
							its = Ctx.children(phrase, CallByContentContext.class);
						} else {
							continue;
						}
						for (final ParserRuleContext it : its) {
							final Map<String, Object> u = new LinkedHashMap<String, Object>();
							u.put("mode", mode);
							u.put("text", Ctx.ctext(it));
							final IdentifierContext uid = Ctx.child(it, IdentifierContext.class);
							u.put("name", uid == null ? null : Ctx.headName(uid));
							using.add(u);
						}
					}
				}
			}
			m.put("using", using);
			break;
		}
		case "move": {
			final MoveToStatementContext mt = Ctx.child(x, MoveToStatementContext.class);
			final MoveCorrespondingToStatementContext mc = Ctx.child(x, MoveCorrespondingToStatementContext.class);
			m.put("corresponding", mc != null);
			String fromLiteral = null;
			String fromVar = null;
			final List<String> to = new ArrayList<String>();
			if (mt != null) {
				final MoveToSendingAreaContext sa = Ctx.child(mt, MoveToSendingAreaContext.class);
				final LiteralContext lit = Ctx.child(sa, LiteralContext.class);
				if (lit != null) {
					fromLiteral = Ctx.text(lit);
				} else {
					fromVar = Ctx.headName(Ctx.child(sa, IdentifierContext.class));
				}
				for (final IdentifierContext id : Ctx.children(mt, IdentifierContext.class)) {
					to.add(Ctx.headName(id));
				}
			} else if (mc != null) {
				fromVar = Ctx.headName(Ctx.child(mc, MoveCorrespondingToSendingAreaContext.class));
				for (final IdentifierContext id : Ctx.children(mc, IdentifierContext.class)) {
					to.add(Ctx.headName(id));
				}
			}
			m.put("from_literal", fromLiteral);
			m.put("from_var", fromVar);
			m.put("to", to);
			break;
		}
		case "if": {
			m.put("condition", Ctx.cap(Ctx.ctext(Ctx.child(x, ConditionContext.class)), 1000));
			final IfElseContext el = Ctx.child(x, IfElseContext.class);
			m.put("else_pline", el == null ? null : Ctx.startLine(el));
			break;
		}
		case "evaluate": {
			final List<String> subjects = new ArrayList<String>();
			for (final EvaluateSelectContext es : Ctx.children(x, EvaluateSelectContext.class)) {
				subjects.add(Ctx.ctext(es));
			}
			for (final EvaluateAlsoSelectContext also : Ctx.children(x, EvaluateAlsoSelectContext.class)) {
				subjects.add(Ctx.ctext(Ctx.child(also, EvaluateSelectContext.class)));
			}
			m.put("subjects", subjects);
			final List<Object> whens = new ArrayList<Object>();
			int i = 0;
			for (final EvaluateWhenPhraseContext wp : Ctx.children(x, EvaluateWhenPhraseContext.class)) {
				final Map<String, Object> w = new LinkedHashMap<String, Object>();
				w.put("index", i++);
				w.put("pline", Ctx.startLine(wp));
				final List<String> conds = new ArrayList<String>();
				for (final EvaluateWhenContext ew : Ctx.children(wp, EvaluateWhenContext.class)) {
					conds.add(Ctx.ctext(ew).replaceFirst("(?i)^WHEN\\s+", ""));
				}
				w.put("conditions", conds);
				whens.add(w);
			}
			m.put("whens", whens);
			final EvaluateWhenOtherContext other = Ctx.child(x, EvaluateWhenOtherContext.class);
			m.put("has_other", other != null);
			m.put("other_pline", other == null ? null : Ctx.startLine(other));
			break;
		}
		case "search": {
			m.put("table", Ctx.headName(Ctx.child(x, QualifiedDataNameContext.class)));
			m.put("all", Ctx.hasToken(x, CobolLexer.ALL));
			final List<Object> whens = new ArrayList<Object>();
			int i = 0;
			for (final SearchWhenContext sw : Ctx.children(x, SearchWhenContext.class)) {
				final Map<String, Object> w = new LinkedHashMap<String, Object>();
				w.put("index", i++);
				w.put("pline", Ctx.startLine(sw));
				w.put("condition", Ctx.ctext(Ctx.child(sw, ConditionContext.class)));
				whens.add(w);
			}
			m.put("whens", whens);
			break;
		}
		case "open": {
			final List<Object> modes = new ArrayList<Object>();
			for (int i = 0; i < x.getChildCount(); i++) {
				if (!(x.getChild(i) instanceof ParserRuleContext)) {
					continue;
				}
				final ParserRuleContext c = (ParserRuleContext) x.getChild(i);
				String mode = null;
				if (c instanceof OpenInputStatementContext) {
					mode = "INPUT";
				} else if (c instanceof OpenOutputStatementContext) {
					mode = "OUTPUT";
				} else if (c instanceof OpenIOStatementContext) {
					mode = "I-O";
				} else if (c instanceof OpenExtendStatementContext) {
					mode = "EXTEND";
				}
				if (mode == null) {
					continue;
				}
				final Map<String, Object> mm = new LinkedHashMap<String, Object>();
				mm.put("mode", mode);
				final List<String> files = new ArrayList<String>();
				for (final FileNameContext f : Ctx.all(c, FileNameContext.class)) {
					files.add(f.getText().toUpperCase());
				}
				mm.put("files", files);
				modes.add(mm);
			}
			m.put("modes", modes);
			break;
		}
		case "read": {
			m.put("file", nameOf(Ctx.child(x, FileNameContext.class)));
			final ReadIntoContext into = Ctx.child(x, ReadIntoContext.class);
			m.put("into", into == null ? null : Ctx.headName(Ctx.child(into, IdentifierContext.class)));
			break;
		}
		case "write": {
			m.put("record", Ctx.headName(Ctx.child(x, RecordNameContext.class)));
			final WriteFromPhraseContext from = Ctx.child(x, WriteFromPhraseContext.class);
			final IdentifierContext fid = from == null ? null : Ctx.child(from, IdentifierContext.class);
			m.put("from", fid == null ? null : Ctx.headName(fid));
			break;
		}
		case "rewrite": {
			m.put("record", Ctx.headName(Ctx.child(x, RecordNameContext.class)));
			final RewriteFromContext from = Ctx.child(x, RewriteFromContext.class);
			final IdentifierContext fid = from == null ? null : Ctx.child(from, IdentifierContext.class);
			m.put("from", fid == null ? null : Ctx.headName(fid));
			break;
		}
		case "delete":
		case "start":
			m.put("file", nameOf(Ctx.child(x, FileNameContext.class)));
			break;
		case "close": {
			final List<String> files = new ArrayList<String>();
			for (final CloseFileContext cf : Ctx.children(x, CloseFileContext.class)) {
				files.add(nameOf(Ctx.child(cf, FileNameContext.class)));
			}
			m.put("files", files);
			break;
		}
		case "execCics":
		case "execSql":
		case "execSqlIms":
			m.put("exec_text", execText);
			break;
		case "stop": {
			final StopStatementGivingContext giving = Ctx.child(x, StopStatementGivingContext.class);
			m.put("run", Ctx.hasToken(x, CobolLexer.RUN) || Ctx.hasToken(giving, CobolLexer.RUN));
			break;
		}
		case "exit":
			m.put("program", Ctx.hasToken(x, CobolLexer.PROGRAM));
			break;
		case "set": {
			final List<String> to = new ArrayList<String>();
			for (final SetToContext st : Ctx.all(x, SetToContext.class)) {
				to.add(Ctx.headName(st));
			}
			m.put("to", to);
			ParserRuleContext val = Ctx.first(x, SetToValueContext.class);
			if (val == null) {
				val = Ctx.first(x, SetByValueContext.class);
			}
			m.put("value", val == null ? null : Ctx.ctext(val));
			break;
		}
		default:
			break;
		}
	}
}
