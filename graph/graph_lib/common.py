"""Shared helpers for the graph builder. Python 3.8, standard library only."""
import io
import json
import os


def load_json(path):
    with io.open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path, obj):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)


def write_text(path, text):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def member_of(path):
    """Upper case base name of a path without the last extension."""
    base = os.path.basename(path.replace("\\", "/"))
    return os.path.splitext(base)[0].upper()


def strip_prefix(node_id):
    """'program:ABC' -> 'ABC'"""
    return node_id.split(":", 1)[1] if ":" in node_id else node_id
