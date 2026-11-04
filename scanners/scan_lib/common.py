"""Shared helpers for the scanners. Python 3.8, standard library only."""
import io
import json
import os
import re


def read_text(path):
    with open(path, "rb") as f:
        raw = f.read()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def split_lines(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def write_json(path, obj):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)


def load_json(path):
    with io.open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def member_name(path):
    base = os.path.basename(path.replace("\\", "/"))
    return os.path.splitext(base)[0].upper()


def unquote(s):
    t = s.strip()
    if len(t) >= 2 and t[0] == t[-1] and t[0] in ("'", '"'):
        q = t[0]
        return t[1:-1].replace(q + q, q)
    return t


def split_top(text, sep=","):
    """Split at sep outside parentheses and quotes. Empty pieces are kept; pieces are not stripped."""
    if not text.strip():
        return []
    pieces = []
    cur = []
    depth = 0
    quote = None
    for ch in text:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
            cur.append(ch)
        elif ch == "(":
            depth += 1
            cur.append(ch)
        elif ch == ")":
            depth -= 1
            cur.append(ch)
        elif ch == sep and depth <= 0:
            pieces.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    pieces.append("".join(cur))
    return pieces


def take_operand_field(text):
    """Text before the first whitespace outside quotes and parentheses."""
    depth = 0
    quote = None
    for i, ch in enumerate(text):
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch.isspace() and depth <= 0:
            return text[:i]
    return text


_KEY_RE = re.compile(r"^([A-Za-z0-9#@$&._-]+)=(.*)$", re.S)


def parse_params(text):
    out = []
    for piece in split_top(text):
        p = piece.strip()
        if not p:
            continue
        m = _KEY_RE.match(p)
        if m:
            out.append((m.group(1).upper(), m.group(2).strip()))
        else:
            out.append((None, p))
    return out


_WORD_RE = re.compile(r"[A-Za-z0-9#@$_-]+")


def paren_args(text):
    """[(WORD_UPPER, arg_or_None)] with balanced arguments."""
    words = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c.isspace() or c == ",":
            i += 1
            continue
        m = _WORD_RE.match(text, i)
        if not m:
            i += 1
            continue
        word = m.group(0).upper()
        i = m.end()
        j = i
        while j < n and text[j].isspace():
            j += 1
        arg = None
        if j < n and text[j] == "(":
            depth = 0
            quote = None
            k = j
            while k < n:
                ch = text[k]
                if quote:
                    if ch == quote:
                        quote = None
                elif ch in ("'", '"'):
                    quote = ch
                elif ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        break
                k += 1
            arg = text[j + 1:k].strip()
            i = k + 1
        words.append((word, arg))
    return words


def sub_params(value):
    v = value.strip()
    if v.startswith("(") and v.endswith(")"):
        depth = 0
        quote = None
        ok = True
        for i, ch in enumerate(v):
            if quote:
                if ch == quote:
                    quote = None
                continue
            if ch in ("'", '"'):
                quote = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0 and i != len(v) - 1:
                    ok = False
                    break
        if ok:
            return [p.strip() for p in split_top(v[1:-1])]
    return [v]


def cap(s, n):
    return s if len(s) <= n else s[:n] + "..."
