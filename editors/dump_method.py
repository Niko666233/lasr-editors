"""Dump one method's bytecode with opcode names (debug helper)."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tools"))

from lasr_core import flzd, tufa                      # noqa: E402
from opcode_table import load_names, sections, opcode_name  # noqa: E402

EXE = r"C:\Games\LASR\LASR.exe"
_names = load_names(open(EXE, "rb").read(), sections(open(EXE, "rb").read()))


def nm(op):
    return opcode_name(_names, op)


def main():
    zip_path = sys.argv[1] if len(sys.argv) > 1 else \
        r"C:\Games\LASR\vehicles\Phoenix_RS_1997\coupe\classes.zip"
    entry = sys.argv[2] if len(sys.argv) > 2 else \
        "classes/Coupe_RS_IEngine_stock.class"
    want = sys.argv[3] if len(sys.argv) > 3 else "eMuls"
    import zipfile
    codec = flzd.FlzdCodec(EXE)
    data = codec.unpack(zipfile.ZipFile(zip_path).read(entry))
    t = tufa.Tufa(data)
    m = t.find(want)
    if not m:
        print("no method", want)
        return
    m = m[0]
    print("%s%s  %d bytes, %d instructions"
          % (m.name, m.desc, len(m.body), len(m.prog)))
    for o, op, w, pay in m.prog:
        extra = ""
        if w == 5:
            import struct
            f = struct.unpack("<f", struct.pack("<I", pay))[0]
            signed = pay - (1 << 32) if pay & 0x80000000 else pay
            extra = "  %d" % signed
            if f == f and abs(f) < 1e7 and 1e-4 < abs(f) < 1e6:
                extra += " | f32 %g" % f
        print("   %05x %02x %-20s%s" % (o, op, nm(op), extra))


if __name__ == "__main__":
    main()
