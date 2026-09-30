"""Probe the FLZD *encoder* (0x401850 / wrapper 0x401D00) with tiny inputs.

Goal: learn whether the bitstream has a trivially reproducible "literal only"
form, which would let us write a pure-python encoder (no Unicorn in the
shipped tool).
"""
import struct
import sys

sys.path.insert(0, "tools")
from lasr_flzd import FlzdCodec, HEAP_BASE, BUFFER_OFFSET, ADDR_PACK

EXE = r"C:\Games\LASR\LASR.exe"


def bits(b):
    return "".join(format(x, "08b") for x in b)


def main():
    codec = FlzdCodec(EXE)
    base = HEAP_BASE + BUFFER_OFFSET
    src = base + 0x400000
    dst = base + 0x800000
    cases = [
        b"",
        b"A",
        b"AB",
        b"ABC",
        bytes(range(16)),
        b"A" * 16,
        b"A" * 64,
        bytes(range(256)),
        b"A" * 256,
    ]
    for data in cases:
        n = len(data)
        codec.uc.mem_write(src, data + b"\0" * 8)
        codec.uc.mem_write(dst, b"\xcc" * (max(n, 1) * 4 + 0x2000))
        size = codec._call(ADDR_PACK, [src, n, dst, max(n, 1) * 4 + 0x2000, 11])
        if size <= 0:
            print("%-4d -> pack returned %d" % (n, size))
            continue
        blob = bytes(codec.uc.mem_read(dst, size))
        payload = blob[13:]
        ok = "-"
        try:
            ok = codec.unpack(blob) == data
        except Exception as e:  # noqa: BLE001
            ok = "unpack error %s" % e
        print("in=%-4d container=%-5d payload=%-5d roundtrip=%s\n    head=%s"
              % (n, size, len(payload), ok, payload[:24].hex(" ")))
        if n <= 4:
            print("    bits=%s" % bits(payload)[:64])


if __name__ == "__main__":
    main()
