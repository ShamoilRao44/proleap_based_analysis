"""Shared helpers for the flow analysis. Python 3.8, standard library only."""
import collections
import io
import json
import os
import re

_TOKEN = re.compile(r"[A-Z0-9][A-Z0-9-]*")


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


def tokens(text):
    """Upper-cased COBOL-word tokens of a text."""
    return _TOKEN.findall((text or "").upper())


def strip_prefix(node_id):
    """'program:ABC' -> 'ABC'"""
    return node_id.split(":", 1)[1] if ":" in node_id else node_id


def tarjan(nodes, adj):
    """Iterative Tarjan SCC. Returns components (lists) in reverse topological order: a component
    is emitted after every component reachable from it."""
    index = {}
    low = {}
    on_stack = set()
    stack = []
    result = []
    counter = [0]
    for root in nodes:
        if root in index:
            continue
        index[root] = low[root] = counter[0]
        counter[0] += 1
        stack.append(root)
        on_stack.add(root)
        work = [(root, iter(sorted(adj.get(root, ()))))]
        while work:
            v, it = work[-1]
            advanced = False
            for w in it:
                if w not in index:
                    index[w] = low[w] = counter[0]
                    counter[0] += 1
                    stack.append(w)
                    on_stack.add(w)
                    work.append((w, iter(sorted(adj.get(w, ())))))
                    advanced = True
                    break
                elif w in on_stack:
                    low[v] = min(low[v], index[w])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[v])
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                result.append(comp)
    return result


def scc_levels(nodes, edges):
    """edges: (a, b) meaning a must come before b. Returns (level per node, set of nodes in a cycle).
    Level 0 = no predecessor; otherwise 1 + the largest predecessor level (components of a cycle share one)."""
    nodes = sorted(set(nodes))
    adj = collections.defaultdict(set)
    for a, b in edges:
        if a in nodes and b in nodes and a != b:
            adj[a].add(b)
    comps = tarjan(nodes, adj)
    comp_of = {}
    for i, c in enumerate(comps):
        for n in c:
            comp_of[n] = i
    cpreds = collections.defaultdict(set)
    for a, bs in adj.items():
        for b in bs:
            if comp_of[a] != comp_of[b]:
                cpreds[comp_of[b]].add(comp_of[a])
    clevel = {}
    for ci in reversed(range(len(comps))):
        ps = cpreds.get(ci)
        clevel[ci] = 0 if not ps else 1 + max(clevel[p] for p in ps)
    cyclic = set()
    for c in comps:
        if len(c) > 1:
            cyclic.update(c)
    return dict((n, clevel[comp_of[n]]) for n in nodes), cyclic
