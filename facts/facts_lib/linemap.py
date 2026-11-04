"""Maps lines of the preprocessed source back to (file, line) of the original files."""
import os

from . import common

ENTER = "*> @@CPYENTER "
EXIT = "*> @@CPYEXIT "
MISSING = "*> @@CPYMISSING "
WINDOW = 400


def _default_read(path):
    try:
        return common.split_lines(common.read_text(path))
    except (OSError, IOError):
        return []


def _orig_keys(lines, fmt):
    keys = []
    cont = []
    for line in lines:
        ind, content = common.source_area(line, fmt)
        if ind in "*/":
            key = "C:" + common.norm_key(content)
        elif content.lstrip().startswith("*>"):
            key = "C:" + common.norm_key(content.lstrip()[2:])
        else:
            key = common.norm_key(content)
        keys.append(key)
        cont.append(ind == "-")
    return keys, cont


def _pp_key(s):
    """Key of a stripped preprocessed line."""
    if s.startswith("*>EXECSQLIMS"):
        return common.norm_key(s[len("*>EXECSQLIMS"):].replace("}", ""))
    if s.startswith("*>EXECCICS"):
        return common.norm_key(s[len("*>EXECCICS"):].replace("}", ""))
    if s.startswith("*>EXECSQL"):
        return common.norm_key(s[len("*>EXECSQL"):].replace("}", ""))
    if s.startswith("*>CE"):
        return common.norm_key(s[4:])
    if s.startswith("*>"):
        return "C:" + common.norm_key(s[2:])
    return common.norm_key(s)


def _blank(key):
    return key in ("", "C:")


def _match(k, o):
    if _blank(o):
        return False
    if k == o:
        return True
    if len(o) >= 4 and k.startswith(o):
        return True
    if len(k) >= 4 and o.startswith(k):
        return True
    return False


class _Segment(object):
    def __init__(self, file_index, keys, cont):
        self.file_index = file_index
        self.keys = keys
        self.cont = cont
        self.p = 0
        self.last = 1


def _find_copy(seg, name):
    target = "COPY" + common.norm_key(name)
    top = min(seg.p + WINDOW, len(seg.keys))
    for j in range(seg.p, top):
        if not seg.keys[j].startswith("C:") and target in seg.keys[j]:
            k = j
            while k < len(seg.keys) - 1 and "." not in seg.keys[k]:
                k += 1
            seg.p = k + 1
            seg.last = j + 1
            return j + 1
    return None


def build_linemap(pp_lines, program_path, fmt, read_lines=None):
    """See STEP2_BUILD_PLAN.md section 6.2."""
    reader = read_lines or _default_read
    files = []
    index_by_path = {}

    def file_index(path, kind):
        if path in index_by_path:
            return index_by_path[path]
        idx = len(files)
        base = os.path.basename(path.replace("\\", "/"))
        name = os.path.splitext(base)[0].upper()
        files.append({"index": idx, "path": path, "name": name, "kind": kind})
        index_by_path[path] = idx
        return idx

    def make_segment(path, kind):
        idx = file_index(path, kind)
        keys, cont = _orig_keys(reader(path), fmt)
        return _Segment(idx, keys, cont)

    stack = [make_segment(program_path, "program")]
    mapping = []
    copies = []
    nonblank = 0
    exact_nonblank = 0

    for line in pp_lines:
        seg = stack[-1]
        s = line.strip()
        exact = False

        if s.startswith(ENTER):
            rest = s[len(ENTER):]
            name, _, path = rest.partition("|")
            name = name.strip().upper()
            copy_loc = _find_copy(seg, name)
            entry = [seg.file_index, copy_loc or seg.last, copy_loc is not None]
            exact = copy_loc is not None
            new_seg = make_segment(path, "copybook")
            stack.append(new_seg)
            copies.append({"name": name, "path": path, "file_index": new_seg.file_index,
                           "parent_file": seg.file_index, "line": entry[1], "exact": exact,
                           "enter_pline": len(mapping) + 1, "exit_pline": None,
                           "depth": len(stack) - 1, "missing": False})
        elif s.startswith(EXIT):
            if len(stack) > 1:
                done = stack.pop()
                for ev in reversed(copies):
                    if ev["file_index"] == done.file_index and ev["exit_pline"] is None and not ev["missing"]:
                        ev["exit_pline"] = len(mapping) + 1
                        break
            parent = stack[-1]
            entry = [parent.file_index, parent.last, False]
        elif s.startswith(MISSING):
            name = s[len(MISSING):].strip().upper()
            copy_loc = _find_copy(seg, name)
            entry = [seg.file_index, copy_loc or seg.last, copy_loc is not None]
            exact = copy_loc is not None
            copies.append({"name": name, "path": None, "file_index": None,
                           "parent_file": seg.file_index, "line": entry[1], "exact": exact,
                           "enter_pline": len(mapping) + 1, "exit_pline": len(mapping) + 1,
                           "depth": len(stack), "missing": True})
        else:
            key = _pp_key(s)
            if _blank(key):
                if seg.p < len(seg.keys) and _blank(seg.keys[seg.p]):
                    entry = [seg.file_index, seg.p + 1, True]
                    seg.last = seg.p + 1
                    seg.p += 1
                else:
                    entry = [seg.file_index, seg.last, False]
            else:
                found = None
                top = min(seg.p + WINDOW, len(seg.keys))
                for j in range(seg.p, top):
                    if _match(key, seg.keys[j]):
                        found = j
                        break
                if found is not None:
                    entry = [seg.file_index, found + 1, True]
                    seg.last = found + 1
                    seg.p = found + 1
                    while seg.p < len(seg.keys) and seg.cont[seg.p]:
                        seg.p += 1
                else:
                    entry = [seg.file_index, seg.last, False]
            exact = entry[2]

        if s:
            nonblank += 1
            if exact:
                exact_nonblank += 1
        mapping.append(entry)

    ratio = 1.0 if nonblank == 0 else float(exact_nonblank) / nonblank
    return {"files": files, "map": mapping, "copies": copies, "exact_ratio": ratio}


def identity_linemap(program_path, n_lines):
    base = os.path.basename(program_path.replace("\\", "/"))
    files = [{"index": 0, "path": program_path, "name": os.path.splitext(base)[0].upper(), "kind": "program"}]
    return {"files": files, "map": [[0, i + 1, True] for i in range(n_lines)], "copies": [],
            "exact_ratio": 1.0}


def loc(lm, pline):
    """[file_index, line] for a 1-based pline; [0, 0] if unknown."""
    if pline is None or pline < 1 or pline > len(lm["map"]):
        return [0, 0]
    e = lm["map"][pline - 1]
    return [e[0], e[1]]


def is_exact(lm, pline):
    if pline is None or pline < 1 or pline > len(lm["map"]):
        return False
    return bool(lm["map"][pline - 1][2])
