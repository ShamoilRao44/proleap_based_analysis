"""Shared helpers for the facts extractor. Python 3.8, standard library only."""
import io
import json
import os
import re

NAME_RE = r"[A-Z0-9][A-Z0-9-]*"  # COBOL word (upper)


def read_text(path):
    """Read a file as text: try utf-8, on UnicodeDecodeError use latin-1."""
    with open(path, "rb") as f:
        raw = f.read()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def split_lines(text):
    """Split on newlines (CRLF / CR normalised). Drops one trailing empty element."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def source_area(line, fmt):
    """Return (indicator, content) of a source line."""
    if fmt == "FIXED":
        ind = line[6] if len(line) > 6 else " "
        return ind, line[7:72]
    if fmt == "VARIABLE":
        ind = line[6] if len(line) > 6 else " "
        return ind, line[7:]
    return " ", line


def is_comment(indicator, content):
    """True for comment lines: indicator * or /, or a floating *> comment."""
    return indicator in "*/" or content.lstrip().startswith("*>")


def norm_key(s):
    """Upper case and remove all whitespace."""
    return re.sub(r"\s+", "", s.upper())


def est_tokens(chars):
    """Token estimate used everywhere."""
    return (chars + 2) // 3


def relpath(path, root):
    """Path relative to root with forward slashes if inside root, else absolute with forward slashes."""
    try:
        ap = os.path.abspath(path)
        ar = os.path.abspath(root)
        if os.path.commonpath([ap, ar]) == ar:
            return os.path.relpath(ap, ar).replace("\\", "/")
    except ValueError:
        pass
    return os.path.abspath(path).replace("\\", "/")


def write_json(path, obj):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)


def load_json(path):
    with io.open(path, "r", encoding="utf-8") as f:
        return json.load(f)
