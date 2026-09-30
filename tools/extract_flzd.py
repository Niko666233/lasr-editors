"""
Stage 1 of the LASR asset pipeline: unwrap every FLZD container in the game.

Sources handled
  * every ZIP in the game whose members are FLZD blobs
    (java/classes.zip, maps/*/classes.zip, vehicles/**/classes.zip)
  * loose FLZD files (drivers/*/Main.class, shader.dat)

Each payload is written under  extracted/<mirrored path>/<name>.tufa
plus a chunk map so the TUFA serialised-class format can be tackled next.

Usage:  python tools/extract_flzd.py [--out DIR]
"""
import argparse
import collections
import json
import struct
import sys
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lasr_flzd import FlzdCodec, FlzdError, parse_header   # noqa: E402

GAME = Path(r"C:\Games\LASR")
CHUNK_TAGS = (b"CONS", b"FILD", b"MTHD", b"CLSS", b"TREE", b"CODE", b"ENDF")


def tufa_chunks(data: bytes):
    """Walk the TUFA v4 chunk chain.  Returns (header, [chunks])."""
    if data[:4] != b"TUFA":
        return None, []
    ver, sig = struct.unpack_from("<II", data, 4)
    chunks = []
    off = 12
    while off + 8 <= len(data):
        tag = data[off:off + 4]
        size = struct.unpack_from("<I", data, off + 4)[0]
        if off + 8 + size > len(data):
            chunks.append((tag.decode("latin1"), size, "TRUNCATED"))
            break
        chunks.append((tag.decode("latin1"), size, None))
        off += 8 + size
    return {"version": ver, "signature": sig, "declared_len": off}, chunks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="extracted")
    ap.add_argument("--game", default=str(GAME))
    args = ap.parse_args()

    game = Path(args.game)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    codec = FlzdCodec(game / "LASR.exe")
    print("FLZD codec ready; level table:", dict(zip(range(15), codec.table)))

    manifest = []
    t0 = time.time()
    n_ok = n_fail = 0

    zip_targets = []
    for p in sorted(game.rglob("*.zip")):
        try:
            z = zipfile.ZipFile(p)
        except Exception:
            continue
        if any(z.read(i.filename)[:4] == b"FLZD" for i in z.infolist()[:1]):
            zip_targets.append(p)

    for p in zip_targets:
        rel = p.relative_to(game)
        z = zipfile.ZipFile(p)
        base = out / rel.with_suffix("")
        chunkmap = {}
        for info in z.infolist():
            blob = z.read(info.filename)
            if blob[:4] != b"FLZD":
                continue
            try:
                data = codec.unpack(blob)
            except FlzdError as e:
                n_fail += 1
                manifest.append({"src": f"{rel}!{info.filename}", "error": str(e)})
                print(f"  FAIL {rel}!{info.filename}: {e}")
                continue
            dst = base / info.filename
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(data)
            n_ok += 1
            hdr, chunks = tufa_chunks(data)
            if hdr:
                chunkmap[info.filename] = {"header": hdr,
                                           "chunks": [[c[0], c[1]] for c in chunks]}
                manifest.append({"src": f"{rel}!{info.filename}",
                                 "out": str(dst), "size": len(data),
                                 "compressed": len(blob), "kind": "TUFA",
                                 "chunks": [c[0] for c in chunks]})
            else:
                manifest.append({"src": f"{rel}!{info.filename}",
                                 "out": str(dst), "size": len(data),
                                 "compressed": len(blob), "kind": "raw"})
        if chunkmap:
            (base / "_chunkmap.json").write_text(json.dumps(chunkmap, indent=1))
        print(f"{rel}: {len(z.infolist())} members")

    # loose FLZD files
    for p in sorted(game.rglob("*")):
        if not p.is_file() or p.suffix.lower() == ".zip":
            continue
        head = p.open("rb").read(4)
        if head != b"FLZD":
            continue
        blob = p.read_bytes()
        rel = p.relative_to(game)
        try:
            data = codec.unpack(blob)
        except FlzdError as e:
            n_fail += 1
            manifest.append({"src": str(rel), "error": str(e)})
            print(f"  FAIL {rel}: {e}")
            continue
        dst = out / "_loose" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
        n_ok += 1
        hdr, chunks = tufa_chunks(data)
        manifest.append({"src": str(rel), "out": str(dst), "size": len(data),
                         "compressed": len(blob),
                         "kind": "TUFA" if hdr else "raw",
                         "chunks": [c[0] for c in chunks] if hdr else []})
        print(f"{rel}: {len(blob)} -> {len(data)} bytes")

    (out / "_manifest.json").write_text(json.dumps(manifest, indent=1))
    kinds = collections.Counter(m.get("kind") for m in manifest if "kind" in m)
    print(f"\n{n_ok} decoded, {n_fail} failed, {time.time() - t0:.1f}s")
    print("kinds:", dict(kinds))
    ch = collections.Counter()
    for m in manifest:
        for c in m.get("chunks", []):
            ch[c] += 1
    print("chunk tags seen:", dict(ch))


if __name__ == "__main__":
    main()
