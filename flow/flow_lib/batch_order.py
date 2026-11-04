"""Job order from dataset definition and use."""
import collections

from . import common


def build_batch(graph):
    nodes = dict((n["id"], n) for n in graph["nodes"])
    edges = graph["edges"]
    jobs = set()
    step_job = {}
    step_program = collections.defaultdict(set)
    for e in edges:
        if e["type"] == "JOB_STEP":
            jobs.add(nodes[e["source"]]["name"])
    for nid, n in nodes.items():
        if n["type"] == "step":
            step_job[nid] = n["attrs"].get("job")
    for e in edges:
        if e["type"] == "STEP_RUNS" and e["source"] in step_job:
            t = nodes[e["target"]]
            a = t["attrs"]
            if not a.get("utility") and not a.get("system"):
                step_program[step_job[e["source"]]].add(t["name"])

    definers = collections.defaultdict(set)
    users = collections.defaultdict(set)
    for e in edges:
        if e["type"] not in ("IDCAMS_DEFINE", "IDCAMS_DELETE", "STEP_DATASET"):
            continue
        if e["source"] not in step_job:
            continue
        d = nodes[e["target"]]
        if d["attrs"].get("temp") or d["attrs"].get("unresolved"):
            continue
        job = step_job[e["source"]]
        if job not in jobs:
            continue
        if e["type"] == "IDCAMS_DEFINE":
            definers[d["name"]].add(job)
        else:
            users[d["name"]].add(job)

    order = collections.defaultdict(set)
    multi = []
    external = []
    for ds in sorted(set(definers) | set(users)):
        defs = definers.get(ds, set())
        use = users.get(ds, set()) - defs
        if len(defs) == 1:
            a = next(iter(defs))
            for b in use:
                order[(a, b)].add(ds)
        elif len(defs) >= 2:
            multi.append({"dataset": ds, "definers": sorted(defs), "users": sorted(use)})
        elif use:
            external.append({"dataset": ds, "users": sorted(use)})

    pairs = sorted(order)
    level, _cyc = common.scc_levels(jobs, pairs)
    preds = collections.defaultdict(list)
    succs = collections.defaultdict(list)
    for (a, b) in pairs:
        preds[b].append({"job": a, "datasets": sorted(order[(a, b)])})
        succs[a].append({"job": b, "datasets": sorted(order[(a, b)])})
    defines = collections.defaultdict(set)
    for ds, js in definers.items():
        for j in js:
            defines[j].add(ds)
    job_records = []
    for j in jobs:
        job_records.append({"job": j, "level": level[j], "predecessors": sorted(preds[j], key=lambda x: x["job"]),
                            "successors": sorted(succs[j], key=lambda x: x["job"]),
                            "defines": sorted(defines[j]), "runs_programs": sorted(step_program[j])})
    job_records.sort(key=lambda x: (x["level"], x["job"]))

    required = collections.defaultdict(set)
    one_of = []
    ext = []
    for store in (graph.get("analysis") or {}).get("data_stores", []):
        if not store.get("online_programs"):
            continue
        ds = store["dsn"]
        defs = definers.get(ds, set())
        if len(defs) == 1:
            required[next(iter(defs))].add(ds)
        elif len(defs) >= 2:
            one_of.append({"jobs": sorted(defs), "datasets": [ds]})
        else:
            ext.append(ds)
    return {"jobs": job_records,
            "order_edges": [{"from": a, "to": b, "datasets": sorted(order[(a, b)])} for (a, b) in pairs],
            "multi_definer": multi, "external_inputs": external,
            "online_prerequisites": {
                "required_jobs": [{"job": j, "datasets": sorted(d)} for j, d in sorted(required.items())],
                "one_of": sorted(one_of, key=lambda x: (x["jobs"], x["datasets"])), "external": sorted(ext)}}
