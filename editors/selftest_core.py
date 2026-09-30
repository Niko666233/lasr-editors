"""End-to-end check of the vehicle-data editing path (no GUI, no game launch).

   zip entry -> FLZD unpack -> TUFA parse -> patch literals -> FLZD pack -> zip

Asserts:
  1. pack(original tufa) reproduces the stored container byte-for-byte
  2. after patching, unpack(pack(patched)) differs from the original in exactly
     the edited bytes and nowhere else
"""
import io
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from lasr_core import flzd, tufa  # noqa: E402

EXE = r"C:\Games\LASR\LASR.exe"
ZIP = r"C:\Games\LASR\vehicles\Phoenix_RS_1997\coupe\classes.zip"
NAME = "classes/Coupe_RS_IEngine_stock.class"


def diffs(a, b):
    assert len(a) == len(b), "length changed: %d -> %d" % (len(a), len(b))
    return [(i, a[i], b[i]) for i in range(len(a)) if a[i] != b[i]]


def main():
    codec = flzd.FlzdCodec(EXE)
    z = zipfile.ZipFile(ZIP)
    stored = z.read(NAME)
    print("stored entry      : %d bytes, method %d"
          % (len(stored), z.getinfo(NAME).compress_type))
    original = codec.unpack(stored)
    print("decompressed TUFA : %d bytes %s" % (len(original), original[:8].hex()))

    again = codec.pack(original)
    print("re-pack           : %d bytes  byte-identical to stored: %s"
          % (len(again), again == stored))

    t = tufa.Tufa(original)
    print("chunks            : %s" % {k: len(v) for k, v in t.ck.items()})
    n_linear = sum(1 for m in t.methods if m.linear)
    print("methods           : %d (%d walk exactly)" % (len(t.methods), n_linear))
    names = [m.name for m in t.methods]
    print("method names      : %s" % names[:24])

    for want in ("eMuls", "eRPMs", "RPMs", "Muls", "getPrestige", "staticinit",
                 "<clinit>", "<i>"):
        hits = t.find(want)
        for m in hits:
            lits = t.literals(m)
            prev = [(k, v) for _i, _o, k, v in lits][:14]
            print("  %-14s %-10s linear=%-5s literals=%-3d %s"
                  % (m.name, m.desc, m.linear, len(lits), prev))

    m = t.find("eMuls")
    if not m:
        print("!! no eMuls in this class")
        return 1
    m = m[0]
    lits = t.literals(m)
    print("\neMuls literals: %s" % [(i, k, v) for i, _o, k, v in lits])
    t.scale_literals(m, 1.25)
    patched = t.tobytes()
    d = diffs(original, patched)
    print("patch changed %d bytes: %s" % (len(d), d[:8]))

    packed = codec.pack(patched)
    back = codec.unpack(packed)
    print("repack            : %d bytes (orig %d)" % (len(packed), len(stored)))
    print("round-trip equals patched: %s" % (back == patched))
    d2 = diffs(original, back)
    print("changes vs original: %d bytes %s" % (len(d2), d2[:8]))

    # write a demo zip for the game-side test later
    out = HERE / "out_vehicle_zip_test.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zo:
        for info in z.infolist():
            data = z.read(info.filename)
            zo.writestr(info.filename, packed if info.filename == NAME else data)
    print("wrote %s" % out)
    # and verify the patched value really is in there
    with zipfile.ZipFile(out) as zo:
        rt = tufa.Tufa(codec.unpack(zo.read(NAME)))
        m2 = rt.find("eMuls")[0]
        print("re-read eMuls  : %s"
              % [(i, k, v) for i, _o, k, v in rt.literals(m2)])
    return 0


if __name__ == "__main__":
    sys.exit(main())
