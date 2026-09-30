"""FLZD container codec - decode/encode with the GAME'S OWN routines.

LASR ships its class/asset files inside a private container ("FLZD") that is
compressed with a bespoke Huffman + tree-matcher coder.  Rather than
re-implementing that coder (and risking a stream the game rejects), this module
runs the real machine code out of `LASR.exe` in the Unicorn CPU emulator:

    LASR.exe+0x1D50  flzd_unpack(src, srcLen, dst, dstCap, level) -> size | <0
    LASR.exe+0x1D00  flzd_pack  (src, srcLen, dst, dstCap, level) -> container size
    LASR.exe+0x1570  table init (level -> code-table size)

Container (13-byte header, little endian):

    offset 0   "FLZD"
    offset 4   u32  payloadSize + 4   (== fileSize - 9)
    offset 8   u32  uncompressedSize
    offset 12  u8   level (9..13)
    offset 13  ...  coded payload

`flzd_pack` was verified to round-trip through `unpack` byte-for-byte on real
class files, and to reproduce the original stored bytes exactly.
"""
import struct
from pathlib import Path

from unicorn import (
    Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE,
)
from unicorn.x86_const import (
    UC_X86_REG_ESP, UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EIP,
)

# 容器头的读写是纯 Python 的（放 flzd_head，别把 unicorn 拖进不需要它的场合）
from .flzd_head import (          # noqa: F401  (对外仍然从 flzd import)
    MAGIC, HEADER, LEVELS, DEFAULT_LEVEL, FlzdError, is_flzd, parse_header,
    build_header,
)

IMAGE_BASE = 0x400000
STACK_BASE = 0x10000000
STACK_SIZE = 0x00100000
HEAP_BASE = 0x20000000
HEAP_SIZE = 0x0C000000
BUFFER_OFFSET = 0x04000000
RET_MAGIC = 0x7FFFFFF0

ADDR_INIT = IMAGE_BASE + 0x1570
ADDR_UNPACK = IMAGE_BASE + 0x1D50
ADDR_PACK = IMAGE_BASE + 0x1D00
ADDR_MALLOC = IMAGE_BASE + 0x26659D
ADDR_FREE = IMAGE_BASE + 0x2665AF

TABLE_RVA = 0x35D394
TABLE_EXPECTED = (1, 3, 5, 11, 17, 37, 67, 131, 257, 521, 1031, 2053, 5021,
                  9029, 18041)


class _PeImage:
    def __init__(self, path):
        self.raw = Path(path).read_bytes()
        d = self.raw
        pe = struct.unpack_from("<I", d, 0x3C)[0]
        if d[pe:pe + 4] != b"PE\0\0":
            raise FlzdError("%s is not a PE executable" % path)
        self.image_base = struct.unpack_from("<I", d, pe + 0x34)[0]
        self.size_of_image = struct.unpack_from("<I", d, pe + 0x50)[0]
        nsec = struct.unpack_from("<H", d, pe + 6)[0]
        optsz = struct.unpack_from("<H", d, pe + 20)[0]
        self.sections = []
        base = pe + 24 + optsz
        for i in range(nsec):
            o = base + 40 * i
            name = d[o:o + 8].rstrip(b"\0").decode(errors="replace")
            vsize, vaddr, rawsize, rawptr = struct.unpack_from("<IIII", d, o + 8)
            self.sections.append((name, vaddr, vsize, rawptr, rawsize))
        self.header_size = struct.unpack_from("<I", d, pe + 0x54)[0]

    def mapped(self):
        blob = bytearray(self.raw[: self.header_size])
        blob += b"\0" * (max(self.header_size, 0x1000) - len(blob))
        yield self.image_base, blob
        for name, vaddr, vsize, rawptr, rawsize in self.sections:
            need = max(vsize, rawsize)
            blob = bytearray(self.raw[rawptr:rawptr + rawsize])
            if len(blob) < need:
                blob += b"\0" * (need - len(blob))
            yield self.image_base + vaddr, blob


class FlzdCodec:
    """Emulated FLZD codec backed by the real LASR.exe machine code."""

    def __init__(self, exe_path):
        self.pe = _PeImage(exe_path)
        if self.pe.image_base != IMAGE_BASE:
            raise FlzdError("unexpected ImageBase %#x, expected %#x"
                            % (self.pe.image_base, IMAGE_BASE))
        self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        self.uc.mem_map(IMAGE_BASE, (self.pe.size_of_image + 0xFFF) & ~0xFFF)
        for vaddr, blob in self.pe.mapped():
            self.uc.mem_write(vaddr, bytes(blob))
        self.uc.mem_map(STACK_BASE, STACK_SIZE)
        self.uc.mem_map(HEAP_BASE, HEAP_SIZE)
        self._heap_ptr = HEAP_BASE + 0x1000
        self.uc.hook_add(UC_HOOK_CODE, self._hook_code,
                         begin=ADDR_MALLOC, end=ADDR_MALLOC + 1)
        self.uc.hook_add(UC_HOOK_CODE, self._hook_code,
                         begin=ADDR_FREE, end=ADDR_FREE + 1)
        self._run_init()
        self._src = HEAP_BASE + BUFFER_OFFSET
        self._dst = HEAP_BASE + BUFFER_OFFSET + 0x800000

    def _hook_code(self, uc, address, size, user_data):
        if address == ADDR_MALLOC:
            n = struct.unpack("<I", uc.mem_read(self._stack_arg(0), 4))[0]
            ptr = self._heap_ptr
            self._heap_ptr = (ptr + n + 15) & ~0xF
            if self._heap_ptr >= HEAP_BASE + HEAP_SIZE:
                raise FlzdError("emulated heap exhausted")
            uc.mem_write(ptr, b"\0" * (((n + 0xFFF) & ~0xFFF) or 0x1000))
            self._do_ret(uc, ptr)
        elif address == ADDR_FREE:
            self._do_ret(uc, 0)

    def _stack_arg(self, index):
        return self.uc.reg_read(UC_X86_REG_ESP) + 4 + 4 * index

    def _do_ret(self, uc, retval):
        esp = uc.reg_read(UC_X86_REG_ESP)
        ret = struct.unpack("<I", uc.mem_read(esp, 4))[0]
        uc.reg_write(UC_X86_REG_EAX, retval & 0xFFFFFFFF)
        uc.reg_write(UC_X86_REG_ESP, esp + 4)
        uc.reg_write(UC_X86_REG_EIP, ret)

    def _reset_stack(self):
        esp = STACK_BASE + STACK_SIZE - 0x1000
        self.uc.mem_write(esp, b"\0" * 0x1000)
        return esp

    def _call(self, func, args, timeout=0):
        esp = self._reset_stack()
        frame = struct.pack("<I", RET_MAGIC) + b"".join(
            struct.pack("<I", a & 0xFFFFFFFF) for a in args)
        self.uc.mem_write(esp, frame)
        self.uc.reg_write(UC_X86_REG_ESP, esp)
        self.uc.reg_write(UC_X86_REG_EBP, 0)
        self.uc.emu_start(func, RET_MAGIC, timeout=timeout, count=0)
        return self.uc.reg_read(UC_X86_REG_EAX)

    def _signed(self, v):
        return v - (1 << 32) if v & 0x80000000 else v

    def _run_init(self):
        self._call(ADDR_INIT, [])
        got = struct.unpack("<15I", self.uc.mem_read(IMAGE_BASE + TABLE_RVA, 60))
        if tuple(got) != TABLE_EXPECTED:
            raise FlzdError("init produced an unexpected table: %s" % (got,))
        self.table = got

    # ---- public API -------------------------------------------------------
    def unpack(self, blob, max_out=0):
        level, usize, _payload = parse_header(blob)
        cap = max(usize, max_out)
        if cap == 0:
            return b""
        self.uc.mem_write(self._src, blob)
        self.uc.mem_write(self._dst, b"\0" * cap)
        ret = self._signed(self._call(ADDR_UNPACK, [self._src, len(blob),
                                                    self._dst, cap, 0]))
        if ret < 0:
            raise FlzdError("flzd_unpack returned %d (level=%d, usize=%d)"
                            % (ret, level, usize))
        if ret != usize:
            raise FlzdError("size mismatch: header %d, codec wrote %d"
                            % (usize, ret))
        return bytes(self.uc.mem_read(self._dst, ret))

    def pack(self, data, level=DEFAULT_LEVEL):
        """Compress `data` into a valid FLZD container (header included)."""
        n = len(data)
        cap = n + max(0x1000, n // 2)
        self.uc.mem_write(self._src, data)
        self.uc.mem_write(self._dst, b"\0" * (cap + 13))
        ret = self._signed(self._call(ADDR_PACK, [self._src, n, self._dst,
                                                  cap, level]))
        if ret <= 0:
            raise FlzdError("flzd_pack failed (ret=%d)" % ret)
        return bytes(self.uc.mem_read(self._dst, ret))
