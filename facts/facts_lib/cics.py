"""Reader for EXEC CICS commands."""
import re
from collections import OrderedDict

TWO_WORD = {
    "SEND": {"MAP", "TEXT", "CONTROL", "PAGE"},
    "RECEIVE": {"MAP"},
    "WRITEQ": {"TS", "TD"},
    "READQ": {"TS", "TD"},
    "DELETEQ": {"TS", "TD"},
    "HANDLE": {"ABEND", "AID", "CONDITION"},
    "IGNORE": {"CONDITION"},
    "GET": {"CONTAINER"},
    "PUT": {"CONTAINER"},
    "DELETE": {"CONTAINER"},
}

_WORD_RE = re.compile(r"[A-Za-z0-9-]+")


def _read_words(t):
    """Returns a list of (word_upper, argument_or_None)."""
    words = []
    i = 0
    n = len(t)
    while i < n:
        c = t[i]
        if c.isspace() or c == ",":
            i += 1
            continue
        m = _WORD_RE.match(t, i)
        if not m:
            i += 1
            continue
        word = m.group(0).upper()
        i = m.end()
        j = i
        while j < n and t[j].isspace():
            j += 1
        arg = None
        if j < n and t[j] == "(":
            depth = 0
            quote = None
            k = j
            while k < n:
                ch = t[k]
                if quote:
                    if ch == quote:
                        quote = None
                elif ch in "'\"":
                    quote = ch
                elif ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        break
                k += 1
            arg = t[j + 1:k].strip()
            i = k + 1
        words.append((word, arg))
    return words


def _classify(arg):
    """Option value dict for an argument string (None = flag)."""
    if arg is None:
        return {"flag": True}
    a = arg.strip()
    if a[:1] in ("'", '"'):
        q = a[0]
        inner = a[1:-1] if len(a) >= 2 and a.endswith(q) else a[1:]
        return {"literal": inner.replace(q + q, q)}
    if a.isdigit():
        return {"number": a}
    m = re.match(r"(?i)^LENGTH\s+OF\s+(.*)$", a)
    if m:
        a2 = m.group(1)
    else:
        a2 = a
    v = re.search(r"[A-Za-z0-9][A-Za-z0-9-]*", a2)
    return {"var": v.group(0).upper() if v else a2.upper(), "text": a}


def split_commands(exec_text):
    """ProLeap merges consecutive EXEC blocks into one statement. Split them on END-EXEC.
    Returns a list of command texts, each ending with END-EXEC."""
    parts = re.split(r"(?i)\bEND-EXEC\b\s*\.?", exec_text or "")
    out = [p.strip() + " END-EXEC" for p in parts if p.strip()]
    return out or [exec_text or ""]


def parse(exec_text):
    """Parse an EXEC CICS command into {'command', 'options', 'raw'}."""
    t = exec_text.strip()
    t = re.sub(r"(?i)^EXEC\s+CICS\b", "", t)
    t = re.sub(r"(?i)\bEND-EXEC\s*\.?\s*$", "", t).strip()
    words = _read_words(t)
    options = OrderedDict()
    if not words:
        return {"command": "", "options": options, "raw": exec_text}

    first, first_arg = words[0]
    rest = words[1:]
    command = first

    if first_arg is not None:
        options["_ARG"] = _classify(first_arg)
    elif rest:
        second, second_arg = rest[0]
        if first in ("INQUIRE", "SET"):
            if second_arg is None:
                command = first + " " + second
                rest = rest[1:]
        elif first in TWO_WORD and second in TWO_WORD[first]:
            command = first + " " + second
            if second_arg is not None:
                options.setdefault(second, _classify(second_arg))
            rest = rest[1:]

    for word, arg in rest:
        if word not in options:
            options[word] = _classify(arg)
    return {"command": command, "options": options, "raw": exec_text}


_NON_DATA = {"PROGRAM", "TRANSID", "FILE", "DATASET", "MAP", "MAPSET", "QUEUE", "QNAME", "LABEL"}
_WRITE_OPTS = {"INTO", "SET", "RESP", "RESP2"}


def _var(o):
    return o.get("var") if o else None


def _text(o):
    if not o:
        return None
    if "literal" in o:
        return o["literal"]
    if "number" in o:
        return o["number"]
    if "var" in o:
        return o["text"]
    return None


def interpret(parsed):
    """Turn a parsed command into transfers / resources / error handling / labels / reads / writes."""
    cmd = parsed["command"]
    o = parsed["options"]
    transfers = []
    resources = []
    errors = []
    labels = []
    reads = []
    writes = []

    def commarea():
        return _var(o.get("COMMAREA"))

    def length():
        return _text(o.get("LENGTH"))

    def file_opt():
        return o.get("FILE") or o.get("DATASET")

    if cmd in ("XCTL", "LINK"):
        transfers.append({"kind": cmd, "target": o.get("PROGRAM"), "commarea": commarea(), "length": length()})
    elif cmd == "RETURN":
        if "TRANSID" in o:
            transfers.append({"kind": "RETURN_TRANSID", "target": o.get("TRANSID"), "commarea": commarea(),
                              "length": length()})
        else:
            transfers.append({"kind": "RETURN", "target": None, "commarea": commarea(), "length": length()})
    elif cmd == "START":
        transfers.append({"kind": "START_TRANSID", "target": o.get("TRANSID"), "commarea": None, "length": None})
    elif cmd == "READ":
        op = "read_update" if "UPDATE" in o else "read"
        resources.append({"kind": "cics_file", "name": file_opt(), "op": op, "command": cmd, "mapset": None,
                          "extra": {"ridfld": _var(o.get("RIDFLD"))}})
    elif cmd in ("READNEXT", "READPREV", "STARTBR", "RESETBR", "ENDBR"):
        resources.append({"kind": "cics_file", "name": file_opt(), "op": "browse", "command": cmd,
                          "mapset": None, "extra": {}})
    elif cmd in ("WRITE", "REWRITE", "DELETE", "UNLOCK"):
        op = {"WRITE": "write", "REWRITE": "update", "DELETE": "delete", "UNLOCK": "unlock"}[cmd]
        resources.append({"kind": "cics_file", "name": file_opt(), "op": op, "command": cmd, "mapset": None,
                          "extra": {}})
    elif cmd in ("SEND MAP", "RECEIVE MAP"):
        mapset = o.get("MAPSET") or o.get("MAP")
        resources.append({"kind": "map", "name": o.get("MAP"), "op": "send" if cmd == "SEND MAP" else "receive",
                          "command": cmd, "mapset": mapset, "extra": {}})
    elif cmd in ("SEND TEXT", "SEND CONTROL", "SEND PAGE"):
        resources.append({"kind": "terminal", "name": None, "op": cmd.lower().replace(" ", "_"), "command": cmd,
                          "mapset": None, "extra": {}})
    elif cmd in ("WRITEQ TS", "READQ TS", "DELETEQ TS", "WRITEQ TD", "READQ TD", "DELETEQ TD"):
        kind = "ts_queue" if cmd.endswith("TS") else "td_queue"
        name = (o.get("QUEUE") or o.get("QNAME")) if kind == "ts_queue" else o.get("QUEUE")
        op = {"WRITEQ": "write", "READQ": "read", "DELETEQ": "delete"}[cmd.split()[0]]
        resources.append({"kind": kind, "name": name, "op": op, "command": cmd, "mapset": None, "extra": {}})
    elif cmd == "HANDLE ABEND":
        detail = _text(o.get("PROGRAM")) or _text(o.get("LABEL"))
        errors.append({"kind": "HANDLE_ABEND", "detail": detail})
        if "PROGRAM" in o:
            transfers.append({"kind": "HANDLE_ABEND", "target": o.get("PROGRAM"), "commarea": None,
                              "length": None})
        elif "LABEL" in o and _var(o.get("LABEL")):
            labels.append(_var(o.get("LABEL")))
    elif cmd == "HANDLE CONDITION":
        parts = []
        for name, val in o.items():
            if "var" in val:
                parts.append("%s(%s)" % (name, val["var"]))
                labels.append(val["var"])
            else:
                parts.append(name)
        errors.append({"kind": "HANDLE_CONDITION", "detail": ", ".join(parts)})
    elif cmd == "HANDLE AID":
        errors.append({"kind": "HANDLE_AID", "detail": ", ".join(o.keys())})
        for val in o.values():
            if "var" in val:
                labels.append(val["var"])
    elif cmd == "ABEND":
        errors.append({"kind": "ABEND", "detail": _text(o.get("ABCODE"))})
    elif cmd in ("GET CONTAINER", "PUT CONTAINER"):
        resources.append({"kind": "container", "name": o.get("CONTAINER"),
                          "op": "get" if cmd.startswith("GET") else "put", "command": cmd, "mapset": None,
                          "extra": {"channel": _text(o.get("CHANNEL"))}})

    if "RESP" in o:
        errors.append({"kind": "RESP_CHECK", "detail": "%s RESP(%s)" % (cmd, _var(o["RESP"]))})

    if not cmd.startswith("HANDLE") and not cmd.startswith("IGNORE"):
        for name, val in o.items():
            v = val.get("var")
            if not v:
                continue
            if name in _WRITE_OPTS:
                writes.append(v)
            elif name not in _NON_DATA:
                reads.append(v)

    return {"transfers": transfers, "resources": resources, "error_handling": errors, "labels": labels,
            "reads": reads, "writes": writes}
