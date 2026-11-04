"""Assembler-style statement reader (BMS macros, IMS DBD / PSB)."""
from . import common


def _col72(line):
    return len(line) >= 72 and line[71] not in (" ", "\t")


def _is_comment(line):
    return line.startswith("*") or line.startswith(".*")


def read_asm_statements(lines):
    out = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if not line.strip() or _is_comment(line):
            i += 1
            continue
        head = line[:71]
        if head[:1] in (" ", "\t"):
            label = ""
            rest = head.strip()
        else:
            parts = head.split(None, 1)
            label = parts[0].upper()
            rest = parts[1].strip() if len(parts) > 1 else ""
        parts = rest.split(None, 1)
        op = parts[0].upper() if parts else ""
        remainder = parts[1].lstrip() if len(parts) > 1 else ""
        piece = common.take_operand_field(remainder)
        operands = piece
        start = i
        j = i

        def continued(cur_line, cur_piece, idx):
            if _col72(cur_line):
                return True
            if cur_piece.endswith(",") and idx + 1 < n:
                nl = lines[idx + 1]
                if nl.strip() and not _is_comment(nl) and not nl[:15].strip():
                    return True
            return False

        cont = continued(line, piece, j)
        while cont and j + 1 < n:
            j += 1
            nl = lines[j]
            if _is_comment(nl):
                break
            seg = nl[15:71] if len(nl) > 15 else nl.strip()
            piece = common.take_operand_field(seg.lstrip())
            operands += piece
            cont = continued(nl, piece, j)
        out.append({"label": label, "op": op, "operands": operands, "line": start + 1, "end_line": j + 1})
        i = j + 1
    return out
