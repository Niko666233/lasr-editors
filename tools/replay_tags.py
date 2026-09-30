"""Find every 4-char chunk tag written by the LASR replay/stream recorder.

Idea: every chunk header is written by 0x5602c0(fd, &buf, 8) right after a
`mov dword ptr [esp+X], <4-byte tag>` and `mov dword ptr [esp+X+4], <len>`.
So: take all E8 call sites of 0x5602c0, disassemble backwards with aligned
decoding (reuse calls_to.aligned_back), and pick out immediates that are
4 printable chars.
"""
import re
import sys
import collections

sys.path.insert(0, r"C:\Users\niko6\Desktop\Work\LASR_Reverse_Engineering\tools")
import calls_to as ct

TARGET = 0x5602c0
sites = ct.call_sites(TARGET)
print(f"call sites of 0x{TARGET:x}: {len(sites)}")

def printable_tag(v):
    b = v.to_bytes(4, "little")
    if all(0x20 <= c < 0x7f for c in b):
        return b.decode("ascii")
    if all(c == 0 or 0x20 <= c < 0x7f for c in b) and b[-1] == 0:
        return b[:-1].decode("ascii") + "\\0"
    return None

found = collections.defaultdict(list)
for s in sites:
    try:
        _, ins = ct.aligned_back(s, 18)
    except Exception:
        continue
    if not ins:
        continue
    for x in ins:
        i = f"{x.mnemonic} {x.op_str}"
        m = re.search(r"mov dword ptr \[[^\]]+\], (0x[0-9a-f]+)", i)
        if not m:
            continue
        v = int(m.group(1), 16)
        t = printable_tag(v)
        if t:
            found[t].append((s, i.strip()))
        else:
            # length fields are small ints; keep them per site
            pass

for t, lst in sorted(found.items(), key=lambda kv: -len(kv[1])):
    print(f"\n=== tag {t!r}  ({len(lst)} sites) ===")
    for s, i in lst[:8]:
        print(f"   near 0x{s:x}: {i}")
