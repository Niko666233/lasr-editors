"""Dump the java.game.Replay native-method registration block (0x42acb0..0x42afff).

Schema (observed): push <fn>; push <name-str>; push <sig-str?>; push <class-str>;
                   call 0x652910   (registerNatives)
Resolve every immediate that points into .rdata as a C string.
"""
import sys

sys.path.insert(0, r"C:\Users\niko6\Desktop\Work\LASR_Reverse_Engineering\tools")
import calls_to as ct

start, end = 0x42acb0, 0x42b010
buf = ct.read(start, end - start)
ins = list(ct.MD.disasm(buf, start))

REGISTER = 0x652910
rows = []
for x in ins:
    txt = f"{x.mnemonic} {x.op_str}"
    if x.mnemonic == "push" and x.op_str.startswith("0x"):
        v = int(x.op_str, 16)
        s = ct.cstr(v)
        if s:
            txt += f"   ; \"{s}\""
    rows.append((x.address, txt))

cur = []
for addr, txt in rows:
    cur.append(f"  0x{addr:x}  {txt}")
    if "call 0x%x" % REGISTER in txt:
        print(f"--- register @0x{addr:x} ---")
        print("\n".join(cur[-5:]))
        cur = []
print(f"\n({len(ins)} instructions, {end-start} bytes disassembled)")
