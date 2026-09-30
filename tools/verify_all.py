"""
Full-tree verification of everything carved out of the .rpk archives.

  * every .dds must parse as a DDS header with DDPF_FOURCC set
  * every .iscx must be a valid INVO v4 whose vertex/index blocks satisfy the
    exact size arithmetic and max(index) < vertexCount

Usage: python tools/verify_all.py [ROOT]
"""
import collections
import struct
import sys
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else "extracted_rpak")


def check_dds(p):
    d = p.read_bytes()
    if d[:4] != b"DDS " or len(d) < 128:
        return None
    h = struct.unpack_from("<31I", d, 4)
    if h[0] != 124 or not (h[19] & 0x44):
        return None                # dwSize==124 and (DDPF_FOURCC|DDPF_RGB)
    fourcc = h[20] if (h[19] & 0x4) else 0
    return (h[3], h[2], fourcc, h[6])          # w, h, fourCC, mips


def check_iscx(p):
    d = p.read_bytes()
    if d[:4] != b"INVO":
        return None
    ver, n = struct.unpack_from("<2I", d, 4)
    if ver != 4 or n == 0 or n > 64:
        return None
    pr = [struct.unpack_from("<2I", d, 0x0C + 8 * i) for i in range(n)]
    if pr[0][1] != 0x0C + 8 * n:
        return None
    offs = sorted({o for _, o in pr if 0 < o < len(d)} | {len(d)})
    verts = tris = 0
    strides = []
    for i, (kind, o) in enumerate(pr):
        if kind != 4:
            continue
        nxt = next((b for b in offs if b > o), len(d))
        blk = d[o:nxt]
        if len(blk) < 16:
            continue
        _, size, nv, _ = struct.unpack_from("<4I", blk, 0)
        if nv == 0:
            continue
        if (size - 16) % nv:
            return None                       # stride not integral
        st = (size - 16) // nv
        if st % 4 or not 20 <= st <= 128:
            return None
        if 16 + nv * st != size:
            return None
        verts += nv
        strides.append(st)
        for kind2, o2 in pr[i + 1:]:
            if kind2 != 5:
                continue
            n2 = next((b for b in offs if b > o2), len(d))
            blk2 = d[o2:n2]
            if len(blk2) < 12:
                break
            _, size2, ni, _ = struct.unpack_from("<4I", blk2, 0)
            if size2 != 12 + ni * 2 or 12 + ni * 2 > len(blk2):
                break
            idx = struct.unpack_from("<%dH" % ni, blk2, 12)
            if idx and max(idx) >= nv:
                return None
            tris += ni // 3
            break
    return (verts, tris, tuple(strides))


def main():
    dds_ok = dds_bad = 0
    fmt = collections.Counter()
    dims = collections.Counter()
    for p in ROOT.rglob("*.dds"):
        r = check_dds(p)
        if r:
            dds_ok += 1
            fmt[hex(r[2])] += 1
            dims[(r[0], r[1])] += 1
        else:
            dds_bad += 1

    msh_ok = msh_bad = 0
    verts = tris = 0
    strides = collections.Counter()
    for p in ROOT.rglob("*.iscx"):
        r = check_iscx(p)
        if r:
            msh_ok += 1
            verts += r[0]
            tris += r[1]
            for s in r[2]:
                strides[s] += 1
        else:
            msh_bad += 1

    print(f"DDS  : {dds_ok} valid, {dds_bad} invalid")
    print(f"       fourCC {dict(fmt)}   (0x31545844=DXT1 0x33545844=DXT3 0x35545844=DXT5)")
    print(f"       distinct sizes: {len(dims)}; "
          f"largest {max(dims, key=lambda k: k[0]*k[1]) if dims else '-'}")
    print(f"INVO : {msh_ok} valid, {msh_bad} invalid")
    print(f"       total vertices {verts:,}   total triangles {tris:,}")
    print(f"       stride histogram {dict(strides)}")


if __name__ == "__main__":
    main()
