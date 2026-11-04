"""Load the inventory and the facts of steps 2 and 3."""
import glob
import os

from . import common

FOLDERS = ["csd", "jcl", "proc", "bms", "ddl", "ims", "control"]


def _load_folder(path):
    out = []
    for p in sorted(glob.glob(os.path.join(path, "*.json"))):
        if os.path.basename(p).startswith("_"):
            continue
        out.append(common.load_json(p))
    return out


def load_all(out_dir, inventory_path):
    inv = common.load_json(inventory_path)
    data = {"root": inv["meta"]["codebase_root"], "inventory": inv["files"], "cobol": {}}
    for f in _load_folder(os.path.join(out_dir, "facts", "cobol")):
        data["cobol"][f["name"]] = f
    for kind in FOLDERS:
        data[kind] = _load_folder(os.path.join(out_dir, "facts", kind))
    return data
