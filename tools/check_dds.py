"""Validate the DDS textures carved out of an RPAK archive."""
import collections
import glob
import os
import struct
import sys

D = sys.argv[1] if len(sys.argv) > 1 else \
    r"C:\Users\niko6\Desktop\Work\LASR_Reverse_Engineering\extracted_rpak\vehicles\Hornet_Wega_2006"

f = sorted(glob.glob(os.path.join(D, "*.dds")))
print(f"{len(f)} DDS files in {D}")

ok = 0
fmts = collections.Counter()
sizes = collections.Counter()
bad = []
for p in f:
    d = open(p, "rb").read()
    if d[:4] != b"DDS " or len(d) < 128:
        bad.append((p, "magic/short", len(d)))
        continue
    h = struct.unpack_from("<31I", d, 4)
    hgt, wd, mips = h[2], h[3], h[6]
    fourcc = d[4 + 0x54:4 + 0x58]
    flagged = (h[19] & 0x4) != 0
    ok += 1
    fmts[fourcc.decode("latin1", "replace") if flagged else "(RGB masks)"] += 1
    sizes[(wd, hgt, mips)] += 1

print(f"valid DDS headers: {ok}/{len(f)}")
print("pixel formats:", fmts.most_common())
print("\nlargest by area:")
for (w, hh, m), c in sorted(sizes.items(), key=lambda kv: -kv[0][0] * kv[0][1])[:12]:
    print(f"   {w}x{hh} mips={m}  x{c}")
tot = sum(os.path.getsize(p) for p in f)
print(f"\ntotal {tot:,} bytes")

big = max(f, key=os.path.getsize)
d = open(big, "rb").read()
h = struct.unpack_from("<31I", d, 4)
print(f"largest: {os.path.basename(big)} {len(d):,} B  "
      f"{h[3]}x{h[2]} mips={h[6]} fourCC={d[4+0x54:4+0x58]}")
if bad:
    print("\nnon-DDS payloads (first 10):")
    for p, why, n in bad[:10]:
        print(f"   {os.path.basename(p)}  {why}  {n} B")
