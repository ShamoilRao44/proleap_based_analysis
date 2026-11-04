"""Text-only scanner: the fallback when ProLeap cannot parse a program.

Produces raw facts with the same schema as the Java FactsRunner (parser = "text"), using only
regular expressions on the code area of the source. Line numbers are original line numbers.
"""
import re
import time

from . import common

_WORD = r"[A-Z0-9][A-Z0-9-]*"
_NB = r"(?<![A-Z0-9-])"  # not preceded by a COBOL word character
_LIT_RE = re.compile(r"""\s*,?\s*('(?:[^']|'')*'|"(?:[^"]|"")*"|[^\s,]+)""")
_STR_RE = re.compile(r"""'(?:[^']|'')*'|"(?:[^"]|"")*\"""")

CLAUSE_WORDS = {"PIC", "PICTURE", "VALUE", "VALUES", "OCCURS", "REDEFINES", "USAGE", "BINARY", "PACKED-DECIMAL",
                "DISPLAY", "SIGN", "SYNC", "SYNCHRONIZED", "JUST", "JUSTIFIED", "BLANK", "INDEXED", "COMP",
                "COMPUTATIONAL", "INDEX", "POINTER"}
STOP_WORDS = CLAUSE_WORDS | {"TIMES", "DEPENDING", "THRU", "THROUGH", "GLOBAL", "EXTERNAL", "IS"}


def _is_clause_word(w):
    return (w in CLAUSE_WORDS or w.startswith("COMP-") or w.startswith("COMPUTATIONAL")
            or w.startswith("SYNC") or w.startswith("JUST"))


def _mask(s):
    return _STR_RE.sub(lambda m: m.group(0)[0] + "x" * (len(m.group(0)) - 2) + m.group(0)[-1], s)


def _prepare(lines, fmt):
    """Per line (1-based list): None for comment lines, else (content_upper, masked_upper)."""
    info = [None]
    for line in lines:
        ind, content = common.source_area(line, fmt)
        if common.is_comment(ind, content):
            info.append(None)
        else:
            up = content.upper()
            info.append((up, _mask(up)))
    return info


def scan_exec_dli(lines, fmt):
    """EXEC DLI blocks of the source: [{'line', 'text'}]."""
    blocks = []
    cur = None
    for i, line in enumerate(lines, 1):
        ind, content = common.source_area(line, fmt)
        if common.is_comment(ind, content):
            continue
        up = _mask(content.upper())
        raw = content
        pos = 0
        while True:
            if cur is None:
                m = re.search(r"\bEXEC\s+DLI\b", up[pos:])
                if not m:
                    break
                cur = {"line": i, "parts": []}
                pos += m.start()
            end = up.find("END-EXEC", pos)
            if end >= 0:
                cur["parts"].append(raw[pos:end + 8].strip())
                blocks.append({"line": cur["line"], "text": " ".join(cur["parts"])})
                cur = None
                pos = end + 8
                continue
            cur["parts"].append(raw[pos:].strip())
            break
    return blocks


def _entries(info, lo, hi):
    """Split lines lo..hi into period-terminated entries (and EXEC SQL blocks)."""
    result = []
    buf_up = ""
    buf_mk = ""
    start = None
    in_exec = False
    exec_text = ""
    exec_start = None
    for ln in range(lo, min(hi, len(info) - 1) + 1):
        item = info[ln]
        if item is None:
            continue
        up, mk = item
        pos = 0
        while pos <= len(up):
            if in_exec:
                idx = mk.find("END-EXEC", pos)
                if idx >= 0:
                    exec_text += up[pos:idx + 8]
                    result.append({"start": exec_start, "end": ln, "exec": exec_text.strip()})
                    in_exec = False
                    exec_text = ""
                    pos = idx + 8
                    continue
                exec_text += up[pos:] + " "
                break
            if not buf_up.strip() and re.match(r"\s*EXEC\s+SQL\b", mk[pos:]):
                in_exec = True
                exec_start = ln
                exec_text = ""
                continue
            m = re.search(r"\.(?:\s|$)", mk[pos:])
            if m:
                idx = pos + m.start()
                if start is None and up[pos:idx].strip():
                    start = ln
                buf_up += up[pos:idx]
                buf_mk += mk[pos:idx]
                if buf_up.strip():
                    result.append({"start": start if start is not None else ln, "end": ln,
                                   "up": buf_up.strip(), "mk": buf_mk.strip()})
                buf_up = buf_mk = ""
                start = None
                pos = idx + 1
                if pos >= len(up):
                    break
                continue
            if start is None and up[pos:].strip():
                start = ln
            buf_up += up[pos:] + " "
            buf_mk += mk[pos:] + " "
            break
    return result


def _literals(cu, cm, start):
    """Parse the literals of a VALUE clause starting at index start."""
    out = []
    pos = start
    while True:
        m = _LIT_RE.match(cu, pos)
        if not m:
            break
        word = cm[m.start(1):m.end(1)]
        if word in STOP_WORDS or _is_clause_word(word):
            break
        tok = m.group(1)
        end = m.end(1)
        if word == "ALL":
            m2 = _LIT_RE.match(cu, end)
            if m2:
                tok = "ALL " + m2.group(1)
                end = m2.end(1)
        thru = None
        tm = re.match(r"\s+(?:THRU|THROUGH)\s+", cm[end:])
        if tm:
            m3 = _LIT_RE.match(cu, end + tm.end())
            if m3:
                thru = m3.group(1)
                end = m3.end(1)
        out.append({"from": tok, "thru": thru})
        pos = end
    return out


def _parse_data(up, mk, section, fd, ident, start, end):
    mm = re.match(r"(\d{1,2})\s+", mk)
    if not mm:
        return None
    level = int(mm.group(1))
    rest_u = up[mm.end():]
    rest_m = mk[mm.end():]
    first = re.match(_WORD, rest_m)
    name = None
    cstart = 0
    if first:
        w = first.group(0)
        if level == 88 or not _is_clause_word(w):
            name = w
            cstart = first.end()
    cu = rest_u[cstart:]
    cm = rest_m[cstart:]
    item = {"id": ident, "level": level, "name": name, "section": section, "fd": fd, "pic": None, "usage": None,
            "values": None, "occurs": None, "redefines": None, "sign": None, "sync": False, "justified": False,
            "blank_when_zero": False, "renames": None, "pline": start, "pline_end": end}
    if level == 66:
        item["renames"] = cu.strip()
        return item
    if level == 88:
        vm = re.search(r"\bVALUES?\s+(?:IS\s+|ARE\s+)?", cm)
        item["values"] = _literals(cu, cm, vm.end()) if vm else []
        return item
    pm = re.search(r"\bPIC(?:TURE)?\s+(?:IS\s+)?(\S+)", cm)
    if pm:
        item["pic"] = pm.group(1)
    um = re.search(r"(?<![A-Z0-9-])(COMP(?:UTATIONAL)?(?:-[1-5])?|BINARY|PACKED-DECIMAL|INDEX|POINTER)(?![A-Z0-9-])",
                   cm)
    if um:
        item["usage"] = um.group(1)
    rm = re.search(r"\bREDEFINES\s+(" + _WORD + ")", cm)
    if rm:
        item["redefines"] = rm.group(1)
    om = re.search(r"\bOCCURS\s+(\d+)(?:\s+TO\s+(\d+))?", cm)
    if om:
        n = int(om.group(1))
        mx = int(om.group(2)) if om.group(2) else n
        dm = re.search(r"\bDEPENDING\s+(?:ON\s+)?(" + _WORD + ")", cm)
        im = re.search(r"\bINDEXED\s+(?:BY\s+)?((?:" + _WORD + r"\s*)+)", cm)
        idx = []
        if im:
            for w in im.group(1).split():
                if _is_clause_word(w) or w in STOP_WORDS:
                    break
                idx.append(w)
        item["occurs"] = {"min": n, "max": mx, "depending": dm.group(1) if dm else None, "indexed_by": idx}
    vm = re.search(r"\bVALUES?\s+(?:IS\s+|ARE\s+)?", cm)
    if vm:
        item["values"] = _literals(cu, cm, vm.end())
    return item


def _first_group(rx, text):
    m = re.search(rx, text)
    return m.group(1) if m else None


def scan(path, fmt, name, copybook_index):
    """Text scan of one program. Returns raw facts (parser 'text')."""
    t0 = time.time()
    lines = common.split_lines(common.read_text(path))
    info = _prepare(lines, fmt)
    n = len(lines)

    # divisions
    starts = []
    for ln in range(1, n + 1):
        if info[ln] is None:
            continue
        m = re.match(r"\s*(IDENTIFICATION|ID|ENVIRONMENT|DATA|PROCEDURE)\s+DIVISION\b", info[ln][1])
        if m:
            key = "identification" if m.group(1) in ("IDENTIFICATION", "ID") else m.group(1).lower()
            starts.append((key, ln))
    last_code = 0
    for ln in range(n, 0, -1):
        if info[ln] is not None and info[ln][0].strip():
            last_code = ln
            break
    divisions = {"identification": None, "environment": None, "data": None, "procedure": None}
    for i, (key, ln) in enumerate(starts):
        end = starts[i + 1][1] - 1 if i + 1 < len(starts) else last_code
        if divisions[key] is None:
            divisions[key] = [ln, max(end, ln)]

    # program ids
    program_ids = []
    if divisions["identification"]:
        lo, hi = divisions["identification"]
        joined = " ".join(info[k][0] for k in range(lo, hi + 1) if info[k] is not None)
        for m in re.finditer(r"PROGRAM-ID\.?\s+['\"]?([A-Z0-9#@$-]+)", joined):
            program_ids.append(m.group(1))

    # environment: selects
    selects = []
    if divisions["environment"]:
        lo, hi = divisions["environment"]
        for e in _entries(info, lo, hi):
            if "up" not in e:
                continue
            mk, up = e["mk"], e["up"]
            sm = re.match(r"SELECT\s+(?:OPTIONAL\s+)?(" + _WORD + r")\s+ASSIGN\s+(?:TO\s+)?(\S+)", mk)
            if not sm:
                continue
            am = re.match(r"SELECT\s+(?:OPTIONAL\s+)?" + _WORD + r"\s+ASSIGN\s+(?:TO\s+)?(\S+)", up)
            assign = am.group(1) if am else sm.group(2)
            literal = assign[:1] in ("'", '"')
            if literal:
                assign = common_unquote(assign)
            org = _first_group(r"\bORGANIZATION\s+(?:IS\s+)?((?:LINE\s+)?\w+)", mk)
            selects.append({
                "file": sm.group(1), "assign": assign, "assign_is_literal": literal, "organization": org,
                "access": _first_group(r"\bACCESS\s+(?:MODE\s+)?(?:IS\s+)?(\w+)", mk),
                "record_key": _first_group(r"\bRECORD\s+KEY\s+(?:IS\s+)?(" + _WORD + ")", mk),
                "file_status": _first_group(r"(?:\bFILE\s+)?\bSTATUS\s+(?:IS\s+)?(" + _WORD + ")", mk),
                "pline": e["start"]})

    # data division
    data_sections = []
    data_items = []
    fds = []
    data_exec_sql = []
    if divisions["data"]:
        lo, hi = divisions["data"]
        section = "OTHER"
        fd = None
        sec_starts = []
        for e in _entries(info, lo + 1, hi):
            if "exec" in e:
                data_exec_sql.append({"exec_text": e["exec"], "pline": e["start"], "pline_end": e["end"]})
                continue
            mk, up = e["mk"], e["up"]
            sm = re.match(r"(FILE|WORKING-STORAGE|LOCAL-STORAGE|LINKAGE|COMMUNICATION|SCREEN|REPORT)\s+SECTION$", mk)
            if sm:
                section = sm.group(1) if sm.group(1) in ("FILE", "WORKING-STORAGE", "LOCAL-STORAGE", "LINKAGE") \
                    else "OTHER"
                sec_starts.append((section, e["start"]))
                fd = None
                continue
            fm = re.match(r"(FD|SD)\s+(" + _WORD + ")", mk)
            if fm:
                fd = fm.group(2)
                fds.append({"file": fd, "kind": fm.group(1), "pline": e["start"]})
                continue
            item = _parse_data(up, mk, section, fd, len(data_items) + 1, e["start"], e["end"])
            if item is not None:
                data_items.append(item)
        for i, (kind, ln) in enumerate(sec_starts):
            end = sec_starts[i + 1][1] - 1 if i + 1 < len(sec_starts) else hi
            data_sections.append({"kind": kind, "start": ln, "end": end})

    # procedure division
    sections = []
    paragraphs = []
    statements = []
    procedure_using = []
    if divisions["procedure"]:
        lo, hi = divisions["procedure"]
        header = ""
        for ln in range(lo, min(lo + 10, hi) + 1):
            if info[ln] is None:
                continue
            header += " " + info[ln][0]
            if "." in info[ln][1]:
                break
        um = re.search(r"\bUSING\s+(.*?)(?:\bRETURNING\b|\bGIVING\b|\.|$)", header)
        if um:
            for w in re.findall(_WORD, um.group(1)):
                if w not in ("BY", "REFERENCE", "VALUE", "CONTENT"):
                    procedure_using.append(w)

        # headers first
        headers = []
        for ln in range(lo + 1, hi + 1):
            if info[ln] is None:
                continue
            up = info[ln][0]
            if not up[:1].strip():
                continue
            sm = re.match(r"(" + _WORD + r")\s+SECTION\s*\.", up)
            if sm:
                headers.append(("section", sm.group(1), ln))
                continue
            pm = re.match(r"(" + _WORD + r")\s*\.\s*$", up)
            if pm and pm.group(1) != "DECLARATIVES":
                headers.append(("paragraph", pm.group(1), ln))
        cur_section = None
        for i, (kind, nm, ln) in enumerate(headers):
            end = headers[i + 1][2] - 1 if i + 1 < len(headers) else hi
            if kind == "section":
                cur_section = nm
                sections.append({"name": nm, "start": ln, "end": end, "declaratives": False})
            else:
                paragraphs.append({"name": nm, "section": cur_section, "declaratives": False, "start": ln,
                                   "end": end})
        for s in sections:
            nxt = [h[2] for h in headers if h[2] > s["start"] and h[0] == "section"]
            s["end"] = (nxt[0] - 1) if nxt else hi

        statements = _scan_statements(info, lo, hi, headers)

    # COPY statements (any division)
    events = []
    missing = []
    for ln in range(1, n + 1):
        if info[ln] is None:
            continue
        up, mk = info[ln]
        for m in re.finditer(_NB + r"COPY\s+('[^']+'|\"[^\"]+\"|" + _WORD + r")(?:\s+(?:OF|IN)\s+(" + _WORD + "))?",
                             up):
            if mk[m.start():m.start() + 4] != "COPY":
                continue
            cname = common_unquote(m.group(1)).upper().strip()
            cname = re.sub(r"\.[A-Z0-9]+$", "", cname) if "." in cname and cname not in copybook_index else cname
            found = copybook_index.get(cname)
            events.append({"name": cname, "path": found[0] if found else None, "file_index": None,
                           "parent_file": 0, "line": ln, "exact": True, "enter_pline": ln, "exit_pline": ln,
                           "depth": 1, "missing": not found})
            if not found and cname not in missing:
                missing.append(cname)

    return {
        "schema": "cobol-raw-facts/1", "name": name, "program_file": path, "parser": "text", "format": fmt,
        "charset": "utf-8", "status": "ok", "error": None, "parse_ms": int((time.time() - t0) * 1000),
        "preprocessed_file": None, "missing_copybooks": missing, "syntax_error_count": 0, "syntax_errors": [],
        "program_ids": program_ids, "divisions": divisions, "data_sections": data_sections,
        "selects": selects, "fds": fds, "data_items": data_items, "data_exec_sql": data_exec_sql,
        "procedure_using": procedure_using, "sections": sections, "paragraphs": paragraphs,
        "statements": statements, "copy_events_direct": events}


def common_unquote(s):
    t = s.strip()
    if len(t) >= 2 and t[0] in ("'", '"') and t[-1] == t[0]:
        return t[1:-1].replace(t[0] * 2, t[0])
    return t


_KEYWORD_STOP = {"ON", "NOT", "END-CALL", "GIVING", "RETURNING", "AT", "INVALID", "END-READ", "END-WRITE"}


def _scan_statements(info, lo, hi, headers):
    """Statements of the procedure division."""
    stmts = []
    header_at = {}
    for kind, nm, ln in headers:
        header_at.setdefault(ln, []).append((kind, nm))
    cur_par = None
    cur_sec = None
    in_exec = None

    def new(type_, ln, ln_end, text):
        s = {"id": 0, "type": type_, "pline": ln, "pline_end": ln_end, "paragraph": cur_par, "section": cur_sec,
             "parent": None, "branch": None, "text": text[:300], "reads": [], "writes": []}
        return s

    last_evaluate = None
    for ln in range(lo + 1, hi + 1):
        for kind, nm in header_at.get(ln, []):
            if kind == "section":
                cur_sec = nm
            else:
                cur_par = nm
        item = info[ln]
        if item is None:
            continue
        up, mk = item

        if in_exec is not None:
            end = mk.find("END-EXEC")
            in_exec["parts"].append(up[:end + 8] if end >= 0 else up)
            if end >= 0:
                s = in_exec["stmt"]
                s["pline_end"] = ln
                s["exec_text"] = " ".join(p.strip() for p in in_exec["parts"]).strip()
                s["text"] = s["exec_text"][:300]
                in_exec = None
            continue

        line_stmts = []
        em = re.search(r"\bEXEC\s+(CICS|SQL)\b", mk)
        scan_end = len(up)
        if em:
            scan_end = em.start()
            st = new("execCics" if em.group(1) == "CICS" else "execSql", ln, ln, up[em.start():])
            st["exec_text"] = ""
            end = mk.find("END-EXEC", em.start())
            if end >= 0:
                st["exec_text"] = up[em.start():end + 8].strip()
                st["text"] = st["exec_text"][:300]
            else:
                in_exec = {"stmt": st, "parts": [up[em.start():]]}
            line_stmts.append((em.start(), st))
        u = up[:scan_end]
        m_ = mk[:scan_end]

        def ok(m):
            return m_[m.start():m.start() + 3] == u[m.start():m.start() + 3]

        for m in re.finditer(_NB + r"PERFORM\s+(" + _WORD + r")(?:\s+(?:THRU|THROUGH)\s+(" + _WORD + "))?", u):
            if not ok(m):
                continue
            rest = u[m.end():]
            g1 = m.group(1)
            inline = g1 in ("UNTIL", "VARYING", "WITH", "TEST") or bool(re.match(r"\s+TIMES\b", rest))
            st = new("perform", ln, ln, m.group(0))
            full = u[m.start():]
            ptype = None
            until = None
            if re.search(r"\bUNTIL\b", full):
                ptype = "until"
                until = full[re.search(r"\bUNTIL\b", full).end():].strip()[:200]
            elif re.search(r"\bVARYING\b", full):
                ptype = "varying"
            elif re.search(r"\bTIMES\b", full):
                ptype = "times"
            st.update({"inline": inline, "target": None if inline else g1,
                       "thru": None if inline else m.group(2), "perform_type": ptype, "until": until})
            line_stmts.append((m.start(), st))
        for m in re.finditer(_NB + r"CALL\s+('([^']+)'|\"([^\"]+)\"|(" + _WORD + "))", u):
            if not ok(m):
                continue
            lit = m.group(2) or m.group(3)
            var = m.group(4)
            st = new("call", ln, ln, m.group(0))
            using = []
            um = re.search(r"\bUSING\s+(.*)", u[m.end():])
            if um:
                for w in re.findall(_WORD, um.group(1)):
                    if w in _KEYWORD_STOP:
                        break
                    if w in ("BY", "REFERENCE", "VALUE", "CONTENT", "ADDRESS", "OF", "LENGTH"):
                        continue
                    using.append({"mode": "reference", "text": w, "name": w})
            st.update({"target_literal": lit.upper() if lit else None, "target_var": var,
                       "target_text": ("'%s'" % lit) if lit else var, "using": using})
            line_stmts.append((m.start(), st))
        for m in re.finditer(_NB + r"MOVE\s+('(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|" + _WORD + r"(?:\([^)]*\))?)\s+TO\s+("
                             + _WORD + ")", u):
            if not ok(m):
                continue
            src = m.group(1)
            st = new("move", ln, ln, m.group(0))
            from_lit = None
            from_var = None
            if src[:1] in ("'", '"') or re.match(r"^[+-]?\d", src) or src in (
                    "SPACE", "SPACES", "ZERO", "ZEROS", "ZEROES", "LOW-VALUE", "LOW-VALUES", "HIGH-VALUE",
                    "HIGH-VALUES", "QUOTE", "QUOTES"):
                from_lit = src
            else:
                from_var = src.split("(")[0]
            st.update({"corresponding": False, "from_literal": from_lit, "from_var": from_var,
                       "to": [m.group(2)]})
            st["writes"] = [m.group(2)]
            st["reads"] = [from_var] if from_var else []
            line_stmts.append((m.start(), st))
        for m in re.finditer(_NB + r"GO\s+TO\s+(.*)", u):
            if not ok(m):
                continue
            rest = m.group(1)
            st = new("goTo", ln, ln, m.group(0))
            if re.search(r"\bDEPENDING\b", rest):
                before, _, after = rest.partition("DEPENDING")
                targets = re.findall(_WORD, before)
                dm = re.search(r"(?:ON\s+)?(" + _WORD + ")", after)
                st.update({"targets": targets, "depending": dm.group(1) if dm else None})
            else:
                w = re.match(_WORD, rest)
                st.update({"targets": [w.group(0)] if w else [], "depending": None})
            line_stmts.append((m.start(), st))
        for m in re.finditer(_NB + r"GOBACK\b", u):
            if ok(m):
                line_stmts.append((m.start(), new("goback", ln, ln, "GOBACK")))
        for m in re.finditer(_NB + r"STOP\s+RUN\b", u):
            if ok(m):
                st = new("stop", ln, ln, "STOP RUN")
                st["run"] = True
                line_stmts.append((m.start(), st))
        for m in re.finditer(_NB + r"EXIT\s+PROGRAM\b", u):
            if ok(m):
                st = new("exit", ln, ln, "EXIT PROGRAM")
                st["program"] = True
                line_stmts.append((m.start(), st))
        for m in re.finditer(_NB + r"OPEN\s+(.*)", u):
            if not ok(m):
                continue
            st = new("open", ln, ln, m.group(0))
            modes = []
            for w in re.findall(r"I-O|" + _WORD, m.group(1).split(".")[0]):
                if w in ("INPUT", "OUTPUT", "I-O", "EXTEND"):
                    modes.append({"mode": w, "files": []})
                elif modes and w not in ("WITH", "NO", "REWIND"):
                    modes[-1]["files"].append(w)
            st["modes"] = modes
            line_stmts.append((m.start(), st))
        for m in re.finditer(_NB + r"READ\s+(" + _WORD + ")", u):
            if ok(m):
                st = new("read", ln, ln, m.group(0))
                st.update({"file": m.group(1), "into": _first_group(r"\bINTO\s+(" + _WORD + ")", u[m.end():])})
                line_stmts.append((m.start(), st))
        for kw, typ in (("WRITE", "write"), ("REWRITE", "rewrite")):
            for m in re.finditer(_NB + kw + r"\s+(" + _WORD + ")", u):
                if ok(m):
                    st = new(typ, ln, ln, m.group(0))
                    st.update({"record": m.group(1),
                               "from": _first_group(r"\bFROM\s+(" + _WORD + ")", u[m.end():])})
                    line_stmts.append((m.start(), st))
        for kw, typ in (("DELETE", "delete"), ("START", "start")):
            for m in re.finditer(_NB + kw + r"\s+(" + _WORD + ")", u):
                if ok(m):
                    st = new(typ, ln, ln, m.group(0))
                    st["file"] = m.group(1)
                    line_stmts.append((m.start(), st))
        for m in re.finditer(_NB + r"CLOSE\s+(.*)", u):
            if ok(m):
                st = new("close", ln, ln, m.group(0))
                st["files"] = [w for w in re.findall(_WORD, m.group(1).split(".")[0])
                               if w not in ("WITH", "LOCK", "NO", "REWIND")]
                line_stmts.append((m.start(), st))
        m = re.match(r"\s*IF\s+(.*)", u)
        if m and ok(m):
            st = new("if", ln, ln, u.strip())
            st.update({"condition": m.group(1).strip().rstrip(".").strip()[:1000], "else_pline": None})
            line_stmts.append((m.start(), st))
        m = re.match(r"\s*EVALUATE\s+(.*)", u)
        if m and ok(m):
            st = new("evaluate", ln, ln, u.strip())
            st.update({"subjects": [m.group(1).strip().rstrip(".").strip()], "whens": [], "has_other": False,
                       "other_pline": None})
            last_evaluate = st
            line_stmts.append((m.start(), st))
        m = re.match(r"\s*WHEN\s+(.*)", u)
        if m and ok(m) and last_evaluate is not None:
            rest = m.group(1).strip().rstrip(".").strip()
            if rest.startswith("OTHER"):
                last_evaluate["has_other"] = True
                last_evaluate["other_pline"] = ln
            else:
                last_evaluate["whens"].append({"index": len(last_evaluate["whens"]), "pline": ln,
                                               "conditions": [rest]})
        line_stmts.sort(key=lambda x: x[0])
        for _, st in line_stmts:
            stmts.append(st)
    for i, st in enumerate(stmts, 1):
        st["id"] = i
    return stmts
