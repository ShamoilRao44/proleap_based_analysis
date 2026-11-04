"""Record layouts: hierarchy, sizes, offsets and initial value images from data items."""
import re


def norm_usage(u):
    if not u:
        return None
    u = u.upper()
    if u == "COMPUTATIONAL":
        return "COMP"
    m = re.match(r"^COMPUTATIONAL-(\d)$", u)
    if m:
        u = "COMP-" + m.group(1)
    if u in ("BINARY", "COMP-4"):
        return "COMP"
    if u == "PACKED-DECIMAL":
        return "COMP-3"
    return u


def _expand(pic):
    prev = None
    p = pic
    while prev != p:
        prev = p
        p = re.sub(r"(.)\((\d+)\)", lambda m: m.group(1) * int(m.group(2)), p)
    return p


def pic_size(pic, usage, sign):
    """Byte size of an elementary item. Returns None if there is no PIC and the size is unknown."""
    u = norm_usage(usage) or "DISPLAY"
    if not pic:
        if u == "COMP-1":
            return 4
        if u == "COMP-2":
            return 8
        if u in ("INDEX", "POINTER", "PROCEDURE-POINTER", "FUNCTION-POINTER"):
            return 4
        return None
    p = _expand(pic.upper())
    digits = p.count("9")
    chars = len(p.replace("S", "").replace("V", "").replace("P", ""))
    if u in ("COMP", "COMP-5"):
        if digits <= 4:
            return 2
        if digits <= 9:
            return 4
        return 8
    if u == "COMP-3":
        return digits // 2 + 1
    if u == "COMP-1":
        return 4
    if u == "COMP-2":
        return 8
    if u in ("INDEX", "POINTER", "PROCEDURE-POINTER", "FUNCTION-POINTER"):
        return 4
    if u == "NATIONAL":
        return chars * 2
    if u == "DISPLAY":
        return chars + (1 if sign and "SEPARATE" in sign.upper() else 0)
    return chars


def build_items(raw_items):
    """See STEP2_BUILD_PLAN.md section 6.5."""
    items = []
    by_id = {}
    for r in raw_items:
        it = dict(r)
        it["parent"] = None
        it["record"] = it["id"]
        it["children"] = []
        it["conditions"] = []
        it["redefines_id"] = None
        items.append(it)
        by_id[it["id"]] = it

    stack = []
    last_record = None
    last_plain = None
    for it in items:
        lvl = it["level"]
        if lvl in (1, 77):
            stack = [it]
            last_record = it
            last_plain = it
        elif lvl == 66:
            it["record"] = last_record["id"] if last_record else it["id"]
        elif lvl == 88:
            if last_plain is not None:
                it["parent"] = last_plain["id"]
                it["record"] = last_plain["record"]
                if it.get("name"):
                    last_plain["conditions"].append(it["name"])
        else:
            while stack and stack[-1]["level"] >= lvl:
                stack.pop()
            parent = stack[-1] if stack else None
            if parent is not None:
                it["parent"] = parent["id"]
                it["record"] = parent["record"]
                parent["children"].append(it["id"])
            stack.append(it)
            last_plain = it

    for it in items:
        it["is_group"] = len(it["children"]) > 0

    # effective usage
    for it in items:
        eff = norm_usage(it.get("usage"))
        cur = it
        while eff is None and cur["parent"] is not None and cur["level"] != 88:
            cur = by_id[cur["parent"]]
            eff = norm_usage(cur.get("usage"))
        it["effective_usage"] = eff or "DISPLAY"

    # sizes (children come after their parent, so go backwards)
    for it in reversed(items):
        it["size_unknown"] = False
        occ = it.get("occurs")
        it["occurs_count"] = occ["max"] if occ else 1
        if it["level"] in (88, 66):
            it["size"] = 0
            it["total_size"] = 0
            continue
        if it["children"]:
            size = 0
            for cid in it["children"]:
                c = by_id[cid]
                if not c.get("redefines"):
                    size += c["total_size"]
        else:
            size = pic_size(it.get("pic"), it["effective_usage"], it.get("sign"))
            if size is None:
                size = 0
                it["size_unknown"] = True
        it["size"] = size
        it["total_size"] = size * it["occurs_count"]

    # offsets
    for it in items:
        it["offset"] = None
    for it in items:
        if it["level"] in (1, 77):
            it["offset"] = 0
            if it["level"] == 1 and it.get("redefines"):
                for other in items:
                    if other["id"] >= it["id"]:
                        break
                    if other["level"] == 1 and other.get("name") == it["redefines"]:
                        it["redefines_id"] = other["id"]
    for it in items:
        if it["children"]:
            cursor = it["offset"] if it["offset"] is not None else 0
            seen = {}
            for cid in it["children"]:
                c = by_id[cid]
                red = c.get("redefines")
                if red:
                    target = seen.get(red)
                    if target is not None:
                        c["offset"] = target["offset"]
                        c["redefines_id"] = target["id"]
                    else:
                        c["offset"] = cursor
                else:
                    c["offset"] = cursor
                    cursor += c["total_size"]
                if c.get("name") and c["name"] not in seen:
                    seen[c["name"]] = c
    for it in items:
        if it["level"] == 88 and it["parent"] is not None:
            it["offset"] = by_id[it["parent"]]["offset"]
    return items


_FIG = [(r"^SPACES?$", "SPACE"), (r"^ZERO(?:S|ES)?$", "ZERO"), (r"^LOW-VALUES?$", "LOW-VALUE"),
        (r"^HIGH-VALUES?$", "HIGH-VALUE"), (r"^QUOTES?$", "QUOTE"), (r"^NULLS?$", "NULL")]


def literal_value(text):
    """Classify a raw VALUE literal."""
    t = (text or "").strip()
    m = re.match(r"(?i)^ALL\s+(.+)$", t)
    if m:
        inner = literal_value(m.group(1))
        return {"kind": "all", "value": inner["value"]}
    m = re.match(r"""(?i)^X(['"])(.*)\1$""", t)
    if m:
        return {"kind": "hex", "value": m.group(2)}
    if len(t) >= 2 and t[0] in ("'", '"') and t[-1] == t[0]:
        q = t[0]
        return {"kind": "string", "value": t[1:-1].replace(q + q, q)}
    if re.match(r"^[+-]?\d*\.?\d+$", t):
        return {"kind": "number", "value": t}
    u = t.upper()
    for pattern, norm in _FIG:
        if re.match(pattern, u):
            return {"kind": "figurative", "value": norm}
    return {"kind": "other", "value": u}


def _in_occurs(it, by_id):
    cur = it
    while cur is not None:
        if cur.get("occurs"):
            return True
        cur = by_id.get(cur["parent"]) if cur["parent"] is not None else None
    return False


def record_image(items, record_id):
    """Initial value image of one record (list with one char or None per byte)."""
    by_id = {it["id"]: it for it in items}
    rec = by_id.get(record_id)
    if rec is None:
        return []
    image = [None] * rec["total_size"]
    for it in items:
        if it["record"] != record_id or it["level"] in (88, 66):
            continue
        vals = it.get("values")
        if not vals or it.get("offset") is None or _in_occurs(it, by_id):
            continue
        size = it["total_size"] if it["is_group"] else it["size"]
        if size <= 0:
            continue
        lv = literal_value(vals[0]["from"])
        kind, value = lv["kind"], lv["value"]
        if kind == "string":
            chars = value[:size].ljust(size)
        elif kind == "number":
            if it["effective_usage"] != "DISPLAY":
                continue
            digits = re.sub(r"[^0-9]", "", value)
            chars = digits[-size:].rjust(size, "0")
        elif kind == "figurative":
            fill = {"SPACE": " ", "ZERO": "0", "LOW-VALUE": "\x00", "HIGH-VALUE": "\xff"}.get(value)
            if fill is None:
                continue
            chars = fill * size
        else:
            continue
        off = it["offset"]
        for k, ch in enumerate(chars):
            if 0 <= off + k < len(image):
                image[off + k] = ch
    return image


def occurrence_values(items, item_id):
    """All initial values of an item inside an OCCURS table."""
    by_id = {it["id"]: it for it in items}
    item = by_id.get(item_id)
    if item is None or item.get("offset") is None:
        return []
    owner = item
    while owner is not None and not owner.get("occurs"):
        owner = by_id.get(owner["parent"]) if owner["parent"] is not None else None
    if owner is None:
        return []
    stride = owner["size"]
    count = owner["occurs"]["max"]
    image = record_image(items, item["record"])
    result = []
    for k in range(count):
        start = item["offset"] + k * stride
        end = start + item["size"]
        if start < 0 or end > len(image):
            continue
        chunk = image[start:end]
        if any(c is None for c in chunk):
            continue
        result.append("".join(chunk).rstrip())
    return result
