"""Mermaid diagrams."""
import os
import re

from . import analysis, common

MAX_EDGES = 300


def mid(nid):
    return re.sub(r"[^A-Za-z0-9_]", "_", nid)


def lab(s):
    return str(s).replace('"', "'")


def _finish(lines, edges, total):
    out = list(lines) + list(edges[:MAX_EDGES])
    if total > MAX_EDGES:
        out.append("%%%% truncated: %d more edges" % (total - MAX_EDGES))
    return "\n".join(out) + "\n"


def online_flow(g):
    nodes = {}
    for n in g.nodes.values():
        if n["type"] == "transaction" and g.out_edges(n["id"], ("TRANSACTION_RUNS",)):
            nodes[n["id"]] = 'TRAN %s' % n["name"]
        elif n["type"] == "program" and analysis.is_app(n) and n["attrs"].get("role") in ("online", "both"):
            nodes[n["id"]] = n["name"]
    progs = [k for k in nodes if k.startswith("program:")]
    for e in g.edges.values():
        if e["type"] == "USES_MAP" and e["source"] in nodes:
            nodes[e["target"]] = "MAP %s" % g.nodes[e["target"]]["name"]
    styles = {"TRANSACTION_RUNS": "-->", "XCTL": "-.->|XCTL|", "LINK": "-->|LINK|", "CALL": "-->|CALL|",
              "RETURN_TRANSID": "-.->|RETURN|", "USES_MAP": "---"}
    edges = []
    for e in sorted(g.edges.values(), key=lambda x: (x["type"], x["source"], x["target"])):
        if e["type"] in styles and e["source"] in nodes and e["target"] in nodes:
            edges.append("  %s %s %s" % (mid(e["source"]), styles[e["type"]], mid(e["target"])))
    lines = ["flowchart LR"]
    for k in sorted(nodes):
        lines.append('  %s["%s"]' % (mid(k), lab(nodes[k])))
    return _finish(lines, edges, len(edges))


def batch_flow(g):
    lines = ["flowchart LR"]
    edges = []
    datasets = {}
    for job in sorted(g.nodes_of("job"), key=lambda x: x["name"]):
        steps = [g.nodes[e["target"]] for e in g.out_edges(job["id"], ("JOB_STEP",))]
        if not steps:
            continue
        lines.append('  subgraph %s["%s"]' % (mid(job["id"]), lab(job["name"])))
        for s in steps:
            lines.append('    %s["%s: %s"]' % (mid(s["id"]), lab(s["attrs"].get("step_name")), lab(s["attrs"].get("program"))))
        lines.append("  end")
        for s in steps:
            for e in g.out_edges(s["id"], ("STEP_DATASET", "IDCAMS_DEFINE", "IDCAMS_DELETE")):
                d = g.nodes[e["target"]]
                datasets[d["id"]] = d["name"]
                a = e["access"]
                if a in ("write", "read_write"):
                    edges.append("  %s --> %s" % (mid(s["id"]), mid(d["id"])))
                elif a == "read":
                    edges.append("  %s --> %s" % (mid(d["id"]), mid(s["id"])))
                elif a == "delete":
                    edges.append("  %s -->|delete| %s" % (mid(s["id"]), mid(d["id"])))
                else:
                    edges.append("  %s --- %s" % (mid(s["id"]), mid(d["id"])))
    for k in sorted(datasets):
        lines.append('  %s[("%s")]' % (mid(k), lab(datasets[k])))
    return _finish(lines, edges, len(edges))


def data_access(g):
    types = ("PROGRAM_CICS_FILE", "CICS_FILE_DATASET", "PROGRAM_DATASET", "PROGRAM_DB2_TABLE",
             "PROGRAM_TS_QUEUE", "PROGRAM_TD_QUEUE")
    nodes = {}
    edges = []
    for e in sorted(g.edges.values(), key=lambda x: (x["type"], x["source"], x["target"])):
        if e["type"] not in types:
            continue
        for nid in (e["source"], e["target"]):
            n = g.nodes[nid]
            nodes[nid] = n["name"]
        label = ("|%s|" % e["access"]) if e["access"] else ""
        edges.append("  %s -->%s %s" % (mid(e["source"]), label, mid(e["target"])))
    lines = ["flowchart LR"]
    for k in sorted(nodes):
        lines.append('  %s["%s"]' % (mid(k), lab(nodes[k])))
    return _finish(lines, edges, len(edges))


def write_all(g, out_dir):
    d = os.path.join(out_dir, "diagrams")
    common.write_text(os.path.join(d, "online_flow.mmd"), online_flow(g))
    common.write_text(os.path.join(d, "batch_flow.mmd"), batch_flow(g))
    common.write_text(os.path.join(d, "data_access.mmd"), data_access(g))
