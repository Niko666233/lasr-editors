"""Find where node types are written into the node struct field at +0x14 (u16)."""
import collections
import re
import struct

d = open(r"C:\Games\LASR\LASR.exe", "rb").read()
IB = 0x400000
VALID = (set(range(0x2E, 0x3E)) | set(range(0x42, 0x56))
         | {0x0C, 0xA6, 0xAC, 0xAE, 0xAF, 0xB1, 0xB5, 0x108E})

found = collections.Counter()
sites = []
TEXT = d[0x1000:0x2E6000]
for m in re.finditer(rb"\x66\xc7", TEXT):
    o = 0x1000 + m.start()
    modrm = d[o + 2]
    if (modrm >> 6) == 1 and (modrm & 7) == 0 and d[o + 3] == 0x14:
        imm = struct.unpack_from("<H", d, o + 4)[0]
        found[imm] += 1
        sites.append((o, imm))
print("=== 'mov word ptr [reg+0x14], imm16' ===")
for k, v in found.most_common(30):
    print(f"   {k:#06x}  x{v}   {'VALID node type' if k in VALID else ''}")
print(f"total sites: {len(sites)}")

c = collections.Counter()
for m in re.finditer(rb"\x66\x89", TEXT):
    o = 0x1000 + m.start()
    if d[o + 3] == 0x14:
        c[(d[o + 2] >> 3) & 7] += 1
print("\n=== 'mov [reg+0x14], r16' register operands ===")
print(dict(c), "total", sum(c.values()))

if sites:
    sites.sort()
    clusters = []
    cur = [sites[0]]
    for s in sites[1:]:
        if s[0] - cur[-1][0] < 0x400:
            cur.append(s)
        else:
            clusters.append(cur)
            cur = [s]
    clusters.append(cur)
    print("\n=== write-site clusters (candidate node factories) ===")
    for cl in sorted(clusters, key=len, reverse=True)[:10]:
        print(f"  rva {cl[0][0]:#x}..{cl[-1][0]:#x}  {len(cl)} writes; "
              f"values {[hex(v) for _, v in cl[:24]]}")
