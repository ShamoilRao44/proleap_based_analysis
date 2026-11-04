"""Mermaid diagrams of the activity flow."""
import os
import re

from . import common

MAX_EDGES = 300


def mid(name):
    return re.sub(r"[^A-Za-z0-9_]", "_", name)


def lab(s):
    return str(s).replace('"', "'")


def _finish(lines, edges):
    out = list(lines) + list(edges[:MAX_EDGES])
    if len(edges) > MAX_EDGES:
        out.append("%%%% truncated: %d more edges" % (len(edges) - MAX_EDGES))
    return "\n".join(out) + "\n"


def online_process(online):
    lines = ["flowchart TD"]
    roots = set(online["roots"])
    for lv in online["levels"]:
        if lv["level"] is None:
            lines.append('  subgraph LX["Level unknown"]')
        else:
            lines.append('  subgraph L%d["Level %d"]' % (lv["level"], lv["level"]))
        for p in lv["programs"]:
            label = p + (" (entry)" if p in roots else "")
            lines.append('    %s["%s"]' % (mid(p), lab(label)))
        lines.append("  end")
    edges = []
    for e in online["navigation_edges"]:
        a, b = mid(e["source"]), mid(e["target"])
        if e["direction"] == "forward":
            edges.append("  %s --> %s" % (a, b))
        elif e["direction"] == "lateral":
            edges.append("  %s --- %s" % (a, b))
        elif e["direction"] == "back":
            edges.append("  %s -.->|back| %s" % (a, b))
    return _finish(lines, edges)


def batch_order(batch):
    lines = ["flowchart TD"]
    by_level = {}
    for j in batch["jobs"]:
        by_level.setdefault(j["level"], []).append(j["job"])
    for l in sorted(by_level):
        lines.append('  subgraph JL%d["Level %d"]' % (l, l))
        for j in sorted(by_level[l]):
            lines.append('    job_%s["%s"]' % (mid(j), lab(j)))
        lines.append("  end")
    edges = []
    for e in batch["order_edges"]:
        label = ".".join(e["datasets"][0].split(".")[-2:]) if e["datasets"] else ""
        edges.append("  job_%s -->|%s| job_%s" % (mid(e["from"]), lab(label), mid(e["to"])))
    return _finish(lines, edges)


def write_all(out_dir, online, batch):
    d = os.path.join(out_dir, "diagrams")
    common.write_text(os.path.join(d, "online_process.mmd"), online_process(online))
    common.write_text(os.path.join(d, "batch_order.mmd"), batch_order(batch))
