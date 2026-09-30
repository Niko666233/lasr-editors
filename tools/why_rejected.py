"""Explain exactly why verify_all.py rejected each file (no silent failures)."""
import collections
import struct
from pathlib import Path

ROOT = Path("extracted_rpak")

dds_why = collections.Counter()
dds_ex = {}
for p in ROOT.rglob("*.dds"):
    d = p.read_bytes()
    if d[:4] != b"DDS ":
        why = f"not 'DDS ' (got {d[:4]!r})"
    elif len(d) < 128:
        why = f"too short ({len(d)} B)"
    else:
        h = struct.unpack_from("<31I", d, 4)
        if h[0] != 124:
            why = f"dwSize={h[0]} (not 124)"
        elif h[19] != 0x4:
            why = f"ddspf.dwFlags={h[19]:#x} (not DDPF_FOURCC)"
        else:
            why = "OK"
    if why != "OK":
        dds_why[why] += 1
        dds_ex.setdefault(why, p.name)

msh_why = collections.Counter()
msh_ex = {}
for p in ROOT.rglob("*.iscx"):
    d = p.read_bytes()
    if d[:4] != b"INVO":
        why = f"not INVO (got {d[:4]!r})"
    else:
        ver, n = struct.unpack_from("<2I", d, 4)
        if ver != 4:
            why = f"version={ver}"
        elif n == 0 or n > 64:
            why = f"N={n}"
        elif struct.unpack_from("<2I", d, 0x0C)[1] != 0x0C + 8 * n:
            why = "offset[0] != 12+8N"
        else:
            pr = [struct.unpack_from("<2I", d, 0x0C + 8 * i) for i in range(n)]
            offs = sorted({o for _, o in pr if 0 < o < len(d)} | {len(d)})
            why = "OK"
            for i, (kind, o) in enumerate(pr):
                if kind != 4:
                    continue
                nxt = next((b for b in offs if b > o), len(d))
                blk = d[o:nxt]
                if len(blk) < 16:
                    why = f"kind4 block only {len(blk)} B"
                    break
                _, size, nv, _ = struct.unpack_from("<4I", blk, 0)
                if nv == 0:
                    why = "vertexCount == 0"
                    break
                if (size - 16) % nv:
                    why = f"(size-16) % nv != 0  (nv={nv} size={size})"
                    break
                st = (size - 16) // nv
                if st % 4 or not 32 <= st <= 128:
                    why = f"stride {st} out of range"
                    break
                if 16 + nv * st != size:
                    why = "16 + nv*stride != size"
                    break
                bad = False
                for kind2, o2 in pr[i + 1:]:
                    if kind2 != 5:
                        continue
                    n2 = next((b for b in offs if b > o2), len(d))
                    blk2 = d[o2:n2]
                    if len(blk2) < 12:
                        why = "index block too short"
                        bad = True
                        break
                    _, size2, ni, _ = struct.unpack_from("<4I", blk2, 0)
                    if size2 != 12 + ni * 2:
                        why = f"size2 {size2} != 12 + {ni}*2"
                        bad = True
                        break
                    idx = struct.unpack_from("<%dH" % ni, blk2, 12)
                    if idx and max(idx) >= nv:
                        why = (f"max(index) {max(idx)} >= vertexCount {nv}")
                        bad = True
                        break
                    break
                if bad:
                    break
    if why != "OK":
        msh_why[why] += 1
        msh_ex.setdefault(why, p.name)

print(f"--- DDS rejected: {sum(dds_why.values())}")
for w, c in dds_why.most_common():
    print(f"   {c:5d}  {w}      e.g. {dds_ex[w]}")
print(f"\n--- INVO rejected: {sum(msh_why.values())}")
for w, c in msh_why.most_common():
    print(f"   {c:5d}  {w}      e.g. {msh_ex[w]}")
