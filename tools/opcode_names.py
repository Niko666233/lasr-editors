"""
The .rdata string table around VA 0x723a98 holds the VM's opcode / node names.
If they are indexed by opcode number there must be a parallel array of pointers
to them.  Find every such pointer and report contiguous runs - the index of a
string inside its run is its opcode number.

Usage: python tools/opcode_names.py
"""
import re
import struct
from pathlib import Path

EXE = r"C:\Games\LASR\LASR.exe"
IB = 0x400000
OUT = Path(__file__).resolve().parent.parent / "docs" / "OPCODE_NAMES.md"

NAMES = [
    "EXCLAMATION", "ANDAND", "SHORTCUT_OR", "SHORTCUT_AND", "DUP_X2", "DUP_X1",
    "DELETE", "ARRAY_ACCESS", "EMPTYDIMS", "ARRAY_INIT", "ARRAY_STORE",
    "NEWARRAY", "PUTFIELD_QUICK", "PUTFIELD_STATIC", "PUTFIELD_INSTANCE",
    "JMP_EQ2", "JMP_EQ", "JMP_NE", "RETURN", "FIELD_REF_QUICK",
    "FIELD_REF_STATIC", "FIELD_REF_INSTANCE", "INVOKESTATIC", "INVOKESPECIAL",
    "INVOKE", "LOCAL_CLEARN", "LOCAL_CLEAR", "LOCAL_STORE", "LOCAL_CREATE",
    "LOCAL_LOAD", "RID LITERAL", "STRING LITERAL", "CHAR LITERAL",
    "FLOAT LITERAL", "INT LITERAL", "BOOL LITERAL", "NULL LITERAL",
    "INSTANCEOF", "vm_get_int_field", "vm_get_float_field",
    "vm_get_instance_field", "vm_fieldcheck", "vm_set_float_field",
    "vm_set_int_field", "vm_set_instance_field", "vm_set_instance_array_field",
    "vm_get_it_field",
]


def main():
    d = open(EXE, "rb").read()
    addr = {}
    for n in NAMES:
        m = re.search(re.escape(n.encode()) + b"\x00", d)
        if m:
            addr[m.start()] = n
    print(f"located {len(addr)}/{len(NAMES)} name strings in .rdata")

    # find dword pointers to each string
    ptr_at = {}
    for off, n in addr.items():
        va = IB + off
        pat = struct.pack("<I", va)
        for m in re.finditer(re.escape(pat), d):
            if m.start() < 0x2E7000 or m.start() >= 0x342000:
                continue          # only inside .rdata / .data pointer arrays
            ptr_at[m.start()] = n

    print(f"found {len(ptr_at)} string-pointer slots")
    if not ptr_at:
        return
    keys = sorted(ptr_at)
    runs = []
    cur = [keys[0]]
    for k in keys[1:]:
        if k - cur[-1] == 4:
            cur.append(k)
        else:
            runs.append(cur)
            cur = [k]
    runs.append(cur)

    lines = ["# Opcode / node name tables recovered from LASR.exe", ""]
    print()
    for r in sorted(runs, key=len, reverse=True):
        if len(r) < 3:
            continue
        print(f"=== pointer table @ file {r[0]:#x} (VA {IB+r[0]:#x}), "
              f"{len(r)} entries ===")
        lines.append(f"## Table at VA {IB+r[0]:#x} - {len(r)} entries\n")
        lines.append("| index | name |")
        lines.append("|---|---|")
        for i, k in enumerate(r):
            print(f"   [{i:3d}] {ptr_at[k]}")
            lines.append(f"| {i} | `{ptr_at[k]}` |")
        lines.append("")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
