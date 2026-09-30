"""Probe LASR.exe's FLZD pack/unpack routines inside Unicorn.

Questions to answer:
  A) What does flzd_unpack (0x401D50) do when handed a *raw* TUFA buffer
     (no FLZD magic)?  -> tells us whether the game would accept an
     uncompressed .class dropped into a zip.
  B) Does flzd_pack (0x401D00) work standalone?  -> gives us a compressor
     for the edited class files.
"""
import struct
import sys
import zipfile

sys.path.insert(0, "tools")
from lasr_flzd import FlzdCodec, IMAGE_BASE, HEAP_BASE, BUFFER_OFFSET, ADDR_PACK

EXE = r"C:\Games\LASR\LASR.exe"
ZIP = r"C:\Games\LASR\java\classes.zip"


def main():
    codec = FlzdCodec(EXE)
    z = zipfile.ZipFile(ZIP)
    name = sys.argv[1] if len(sys.argv) > 1 else "game/Bet.class"
    raw = z.read(name)
    tufa = codec.unpack(raw)
    print("class %s: container=%d bytes -> tufa=%d bytes %s"
          % (name, len(raw), len(tufa), tufa[:8].hex()))

    base = HEAP_BASE + BUFFER_OFFSET
    src_ptr = base + 0x400000
    dst_ptr = base + 0x800000
    codec.uc.mem_write(src_ptr, tufa)
    codec.uc.mem_write(dst_ptr, b"\xcc" * (len(tufa) + 0x1000))

    # --- A: raw TUFA into the decompressor -------------------------------
    ret = codec._call(0x401D50, [src_ptr, len(tufa), dst_ptr,
                                 len(tufa) + 0x1000, 11])
    print("A) flzd_unpack(raw TUFA) -> ret=%d %s"
          % (ret, "FAIL" if ret < 0 else ""))
    if ret > 0:
        out = bytes(codec.uc.mem_read(dst_ptr, min(ret, 64)))
        print("   first bytes:", out[:32].hex(" "))
        print("   identical to input:", out[:min(ret, len(tufa))] == tufa[:ret])

    # --- B: pack it ------------------------------------------------------
    codec.uc.mem_write(dst_ptr, b"\xcc" * (len(tufa) + 0x10000))
    size = codec._call(ADDR_PACK, [src_ptr, len(tufa), dst_ptr,
                                   len(tufa) + 0x10000, 11])
    print("B) flzd_pack -> ret=%d" % size)
    if size > 0:
        blob = bytes(codec.uc.mem_read(dst_ptr, size))
        print("   header:", blob[:13].hex(" "))
        magic, plus4, usize = struct.unpack_from("<4sII", blob, 0)
        print("   magic=%r payload+4=%d usize=%d level=%d  (tufa=%d)"
              % (magic, plus4, usize, blob[12], len(tufa)))
        try:
            back = codec.unpack(blob)
            print("   round-trip OK:", back == tufa, "len", len(back))
        except Exception as e:  # noqa: BLE001
            print("   round-trip FAILED:", e)
        open("out_flzd_test.bin", "wb").write(blob)
        print("   wrote out_flzd_test.bin (%d bytes)" % len(blob))


if __name__ == "__main__":
    main()
