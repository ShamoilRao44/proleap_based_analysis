"""Control flow helpers: guards, reachability, complexity and paragraph outlines."""
import re
from collections import deque

from . import cics, linemap

OUTLINE_TYPES = {"perform", "goTo", "call", "execCics", "execSql", "execSqlIms", "if", "evaluate",
                 "search", "read", "write", "rewrite", "delete", "start", "open", "close",
                 "goback", "stop", "exit"}

PHRASES = {"atEndPhrase": "AT END", "notAtEndPhrase": "NOT AT END", "invalidKeyPhrase": "INVALID KEY",
           "notInvalidKeyPhrase": "NOT INVALID KEY", "onSizeErrorPhrase": "ON SIZE ERROR",
           "notOnSizeErrorPhrase": "NOT ON SIZE ERROR", "onExceptionClause": "ON EXCEPTION",
           "notOnExceptionClause": "NOT ON EXCEPTION", "onOverflowPhrase": "ON OVERFLOW",
           "notOnOverflowPhrase": "NOT ON OVERFLOW"}


def _cap(s, n):
    return s if len(s) <= n else s[:n] + "..."


def _guard(a, b):
    t = a.get("type")
    if b == "then":
        return a.get("condition") or ""
    if b == "else":
        return "NOT (" + (a.get("condition") or "") + ")"
    if b and b.startswith("when:"):
        i = int(b.split(":")[1])
        whens = a.get("whens") or []
        if t == "evaluate":
            subjects = a.get("subjects") or []
            conds = whens[i]["conditions"] if i < len(whens) else []
            if len(subjects) == 1 and subjects[0].upper() == "TRUE":
                return " OR ".join(conds)
            return " ALSO ".join(subjects) + " = " + " OR ".join(conds)
        if t == "search":
            return whens[i]["condition"] if i < len(whens) else ""
    if b == "other":
        return " ALSO ".join(a.get("subjects") or []) + " = OTHER"
    if b == "inline":
        return "LOOP UNTIL " + a["until"] if a.get("until") else "LOOP"
    return str(t).upper() + " " + PHRASES.get(b, str(b))


def guards(stmt, by_id):
    """Conditions that must hold for the statement to run, outermost first."""
    out = []
    cur = stmt
    while cur.get("parent") is not None:
        a = by_id[cur["parent"]]
        g = _guard(a, cur.get("branch"))
        if g:
            out.append(_cap(g, 200))
        cur = a
    out.reverse()
    return out


def depth_of(stmt, by_id):
    d = 0
    cur = stmt
    while cur.get("parent") is not None:
        d += 1
        cur = by_id[cur["parent"]]
    return d


def resolve_targets(name, thru, paragraphs, sections):
    """Paragraph names reached by PERFORM / GO TO of a paragraph or section name."""
    names = [p["name"] for p in paragraphs]
    if name in names:
        i = names.index(name)
        if thru and thru in names:
            j = names.index(thru, i) if thru in names[i:] else names.index(thru)
            if j >= i:
                return names[i:j + 1]
        return [name]
    sec_names = [s["name"] for s in sections]
    if name in sec_names:
        i = sec_names.index(name)
        wanted = {name}
        if thru and thru in sec_names:
            j = sec_names.index(thru)
            if j >= i:
                wanted = set(sec_names[i:j + 1])
        return [p["name"] for p in paragraphs if p.get("section") in wanted]
    return []


def terminates(par_stmts):
    """True if the last top-level statement of a paragraph ends the flow."""
    top = [s for s in par_stmts if s.get("parent") is None]
    if not top:
        return False
    last = max(top, key=lambda s: (s["pline"], s["id"]))
    t = last["type"]
    if t == "goback":
        return True
    if t == "stop" and last.get("run"):
        return True
    if t == "exit" and last.get("program"):
        return True
    if t == "goTo" and last.get("depending") is None and len(last.get("targets") or []) == 1:
        return True
    if t == "execCics":
        return cics.parse(cics.split_commands(last.get("exec_text") or "")[-1])["command"] in ("RETURN", "XCTL")
    return False


def reachability(paragraphs, sections, statements, labels):
    """Set of paragraph names that can be reached."""
    names = [p["name"] for p in paragraphs]
    by_par = {}
    pre = []
    for s in statements:
        if s.get("paragraph") is None:
            pre.append(s)
        else:
            by_par.setdefault(s["paragraph"], []).append(s)
    term = {n: terminates(by_par.get(n, [])) for n in names}

    seen = set()
    queue = deque()

    def add(n, mode):
        if (n, mode) not in seen:
            seen.add((n, mode))
            queue.append((n, mode))

    def apply(stmts):
        for s in stmts:
            if s["type"] == "perform" and s.get("target"):
                for t in resolve_targets(s["target"], s.get("thru"), paragraphs, sections):
                    add(t, "performed")
            elif s["type"] == "goTo":
                for tgt in s.get("targets") or []:
                    for t in resolve_targets(tgt, None, paragraphs, sections):
                        add(t, "flow")

    apply(pre)
    for p in paragraphs:
        if p.get("declaratives"):
            add(p["name"], "flow")
    for p in paragraphs:
        if not p.get("declaratives"):
            add(p["name"], "flow")
            break
    for lab in labels:
        for t in resolve_targets(lab, None, paragraphs, sections):
            add(t, "flow")

    while queue:
        n, mode = queue.popleft()
        apply(by_par.get(n, []))
        if mode == "flow" and not term.get(n) and n in names:
            i = names.index(n)
            if i + 1 < len(names):
                add(names[i + 1], "flow")
    return set(n for n, _ in seen)


def complexity(par_stmts):
    c = 1
    texts = []
    for s in par_stmts:
        t = s["type"]
        if t == "if":
            c += 1
            texts.append(s.get("condition") or "")
        elif t == "evaluate":
            c += len(s.get("whens") or [])
            for w in s.get("whens") or []:
                texts.extend(w.get("conditions") or [])
        elif t == "search":
            c += len(s.get("whens") or [])
            for w in s.get("whens") or []:
                texts.append(w.get("condition") or "")
        elif t == "perform" and s.get("perform_type") in ("until", "varying"):
            c += 1
    for tx in texts:
        c += len(re.findall(r"\b(?:AND|OR)\b", tx.upper()))
    return c


def _summary(s):
    t = s["type"]
    if t == "perform":
        if s.get("inline"):
            out = "PERFORM (inline)"
        else:
            out = "PERFORM " + str(s.get("target") or "")
            if s.get("thru"):
                out += " THRU " + s["thru"]
        pt = s.get("perform_type")
        if pt == "until" and s.get("until"):
            out += " UNTIL " + s["until"]
        elif pt == "varying":
            out += " VARYING"
            if s.get("until"):
                out += " UNTIL " + s["until"]
        elif pt == "times":
            out += " TIMES"
        return out
    if t == "if":
        return "IF " + (s.get("condition") or "")
    if t == "evaluate":
        return "EVALUATE " + " ALSO ".join(s.get("subjects") or [])
    if t == "search":
        return "SEARCH " + str(s.get("table") or "")
    if t == "call":
        return "CALL " + str(s.get("target_text") or "")
    if t == "goTo":
        return "GO TO " + ", ".join(s.get("targets") or [])
    if t == "execCics":
        outs = []
        for cmd in cics.split_commands(s.get("exec_text") or ""):
            p = cics.parse(cmd)
            out = "EXEC CICS " + p["command"]
            for key in ("PROGRAM", "TRANSID", "FILE", "DATASET", "MAP", "QUEUE", "QNAME"):
                o = p["options"].get(key)
                if o:
                    val = o.get("literal") or o.get("text") or o.get("number") or ""
                    out += " %s(%s)" % (key, val)
                    break
            outs.append(out)
        return "; ".join(outs)
    if t in ("execSql", "execSqlIms"):
        txt = re.sub(r"(?i)^EXEC\s+SQL(?:IMS)?\s*", "", s.get("exec_text") or "")
        return "EXEC SQL " + txt[:100]
    if t in ("read", "delete", "start"):
        return t.upper() + " " + str(s.get("file") or "")
    if t in ("write", "rewrite"):
        return t.upper() + " " + str(s.get("record") or "")
    if t == "open":
        return "OPEN " + " ".join("%s %s" % (m["mode"], ",".join(m["files"])) for m in s.get("modes") or [])
    if t == "close":
        return "CLOSE " + ", ".join(s.get("files") or [])
    if t == "goback":
        return "GOBACK"
    if t == "stop":
        return "STOP RUN" if s.get("run") else "STOP"
    if t == "exit":
        return "EXIT PROGRAM" if s.get("program") else "EXIT"
    return t.upper()


def outline(par_stmts, by_id, lm):
    """Compact list of the important statements of a paragraph."""
    entries = []
    seq = 0
    for s in sorted(par_stmts, key=lambda x: (x["pline"], x["id"])):
        if s["type"] not in OUTLINE_TYPES:
            continue
        d = depth_of(s, by_id)
        seq += 1
        entries.append((s["pline"], seq, {"type": s["type"], "depth": d, "loc": linemap.loc(lm, s["pline"]),
                                          "summary": _cap(_summary(s), 160)}))
        if s["type"] == "evaluate":
            for w in s.get("whens") or []:
                seq += 1
                entries.append((w["pline"], seq, {"type": "when", "depth": d + 1,
                                                  "loc": linemap.loc(lm, w["pline"]),
                                                  "summary": _cap("WHEN " + " OR ".join(w["conditions"]), 160)}))
            if s.get("has_other") and s.get("other_pline"):
                seq += 1
                entries.append((s["other_pline"], seq, {"type": "when", "depth": d + 1,
                                                        "loc": linemap.loc(lm, s["other_pline"]),
                                                        "summary": "WHEN OTHER"}))
        elif s["type"] == "if" and s.get("else_pline"):
            seq += 1
            entries.append((s["else_pline"], seq, {"type": "else", "depth": d,
                                                   "loc": linemap.loc(lm, s["else_pline"]), "summary": "ELSE"}))
    entries.sort(key=lambda e: (e[0], e[1]))
    result = [e[2] for e in entries]
    if len(result) > 200:
        result = result[:200] + [{"type": "truncated"}]
    return result
