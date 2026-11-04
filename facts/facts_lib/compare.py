"""Comparison of the parser result with the text-scan result for the same program."""

CATEGORIES = ["copybooks", "call_targets", "cics_programs", "transids", "cics_files", "maps", "db2_tables",
              "batch_dd"]

_RESOURCE_CATEGORY = {"cics_file": "cics_files", "map": "maps", "db2_table": "db2_tables", "batch_file": "batch_dd"}


def _values(items):
    return [v["value"] for v in items or []]


def dep_sets(final):
    """{category: set of upper names}."""
    out = {c: set() for c in CATEGORIES}
    for cb in final["copybooks"]:
        if cb["depth"] == 1:
            out["copybooks"].add(cb["name"])
    for t in final["transfers"]:
        vals = _values(t["resolved_targets"])
        if t["kind"] == "CALL":
            out["call_targets"].update(vals)
        elif t["kind"] in ("XCTL", "LINK"):
            out["cics_programs"].update(vals)
        elif t["kind"] in ("RETURN_TRANSID", "START_TRANSID"):
            out["transids"].update(vals)
    for r in final["resources"]:
        cat = _RESOURCE_CATEGORY.get(r["kind"])
        if cat:
            out[cat].update(_values(r["name_resolved"]))
    return out


def compare(final_proleap, final_text):
    """{category: {'proleap_only': [...], 'text_only': [...]}} for categories that differ."""
    a = dep_sets(final_proleap)
    b = dep_sets(final_text)
    diff = {}
    for c in CATEGORIES:
        po = sorted(a[c] - b[c])
        to = sorted(b[c] - a[c])
        if po or to:
            diff[c] = {"proleap_only": po, "text_only": to}
    return diff


def merge_text_only(final_proleap, final_text, diff):
    """Copy entries for text_only values into the parser result (marked source 'text_only')."""
    copied = set()

    def add(kind, entry):
        key = (kind, entry["id"] if "id" in entry else entry["name"])
        if key in copied:
            return
        copied.add(key)
        e = dict(entry)
        e["source"] = "text_only"
        if kind == "copybooks":
            final_proleap["copybooks"].append(e)
        elif kind == "transfers":
            e["id"] = "T%d" % (len(final_proleap["transfers"]) + 1)
            final_proleap["transfers"].append(e)
        else:
            e["id"] = "R%d" % (len(final_proleap["resources"]) + 1)
            final_proleap["resources"].append(e)

    for cat, d in diff.items():
        wanted = set(d["text_only"])
        if not wanted:
            continue
        if cat == "copybooks":
            for cb in final_text["copybooks"]:
                if cb["depth"] == 1 and cb["name"] in wanted:
                    add("copybooks", cb)
        elif cat in ("call_targets", "cics_programs", "transids"):
            kinds = {"call_targets": ("CALL",), "cics_programs": ("XCTL", "LINK"),
                     "transids": ("RETURN_TRANSID", "START_TRANSID")}[cat]
            for t in final_text["transfers"]:
                if t["kind"] in kinds and wanted & set(_values(t["resolved_targets"])):
                    add("transfers", t)
        else:
            kind = {v: k for k, v in _RESOURCE_CATEGORY.items()}[cat]
            for r in final_text["resources"]:
                if r["kind"] == kind and wanted & set(_values(r["name_resolved"])):
                    add("resources", r)
    return final_proleap
