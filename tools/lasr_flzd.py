"""
LASR FLZD decompressor driver.

The .class files inside `java/classes.zip`, every `*.zip` payload class, and
`shader.dat` are NOT plain Java bytecode.  They are wrapped in a private
container with the magic `FLZD` (0x445A4C46) and compressed with a custom
Huffman+dictionary coder implemented in LASR.exe.

Instead of re-implementing that coder in Python, this module loads LASR.exe
into the Unicorn x86-32 CPU emulator and calls the game's own routines:

    LASR.exe+0x1D50   flzd_unpack(const void* src, int srcLen,
                                  void* dst, int dstCap, int level)
    LASR.exe+0x1570   init routine that fills the level -> table-size array
                      at 0x75D394 (table[9..13] = 521, 1031, 2053, 5021, 9029)
    LASR.exe+0x1850   flzd_pack(...)   (same table, kept for reference)

Container layout (13-byte header, little endian):

    offset 0   char[4]  "FLZD"
    offset 4   u32      payloadSize + 4      (== filesize - 9)
    offset 8   u32      uncompressedSize
    offset 12  u8       level, must be 9..13
    offset 13  ...      compressed payload

Verified against LASR.exe machine code:
  0x1D31  mov dword ptr [esi], 0x445A4C46      ; 'FLZD'
  0x1D37  mov dword ptr [esi+4], ecx           ; ecx = payloadSize+4
  0x1D3A  mov dword ptr [esi+8], edi           ; edi = srcSize
  0x1D3D  mov byte  ptr [esi+0xC], bl          ; bl  = level
"""

import struct
import sys
from pathlib import Path

from unicorn import (
    Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE, UC_HOOK_MEM_READ_UNMAPPED,
    UC_HOOK_MEM_WRITE_UNMAPPED, UC_HOOK_MEM_FETCH_UNMAPPED,
)
from unicorn.x86_const import (
    UC_X86_REG_ESP, UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EIP,
    UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_EBX, UC_X86_REG_ESI,
    UC_X86_REG_EDI,
)

IMAGE_BASE = 0x400000
STACK_BASE = 0x10000000
STACK_SIZE = 0x00100000
HEAP_BASE = 0x20000000
HEAP_SIZE = 0x0C000000          # 192 MiB: codec scratch at the bottom,
                                # our own i/o buffers at BUFFER_OFFSET
BUFFER_OFFSET = 0x04000000      # 64 MiB mark - comfortably clear of codec allocs
RET_MAGIC = 0x7FFFFFF0

ADDR_INIT = IMAGE_BASE + 0x1570
ADDR_UNPACK = IMAGE_BASE + 0x1D50
ADDR_PACK = IMAGE_BASE + 0x1D00
ADDR_MALLOC = IMAGE_BASE + 0x26659D
ADDR_FREE = IMAGE_BASE + 0x2665AF

TABLE_RVA = 0x35D394             # level -> table size (u32 x 15)
LEVELS = (9, 10, 11, 12, 13)

MAGIC = b"FLZD"


class FlzdError(Exception):
    pass


def parse_header(blob: bytes):
    """Return (level, uncompressed_size, payload) or raise FlzdError."""
    if len(blob) < 13 or blob[:4] != MAGIC:
        raise FlzdError("not an FLZD container (bad magic)")
    a, b = struct.unpack_from("<II", blob, 4)
    level = blob[12]
    if a - 4 > len(blob) - 13:
        raise FlzdError(f"declared payload {a - 4} > available {len(blob) - 13}")
    if not (9 <= level < 14):
        raise FlzdError(f"unsupported level {level} (valid 9..13)")
    return level, b, blob[13:]


class _PeImage:
    """Minimal PE loader: map headers + sections at their virtual addresses."""

    def __init__(self, path: Path):
        self.raw = path.read_bytes()
        d = self.raw
        pe = struct.unpack_from("<I", d, 0x3C)[0]
        assert d[pe:pe + 4] == b"PE\0\0", "not a PE file"
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
        """Yield (vaddr, bytearray) tuples to map into the emulator."""
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
        self.pe = _PeImage(Path(exe_path))
        if self.pe.image_base != IMAGE_BASE:
            raise FlzdError(
                f"unexpected ImageBase {self.pe.image_base:#x}, expected {IMAGE_BASE:#x}")
        self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        # one contiguous mapping for the whole image; pages not backed by file
        # data stay zero (that is what the loader would do for .bss)
        self.uc.mem_map(IMAGE_BASE, (self.pe.size_of_image + 0xFFF) & ~0xFFF)
        for vaddr, blob in self.pe.mapped():
            self.uc.mem_write(vaddr, bytes(blob))
        self.uc.mem_map(STACK_BASE, STACK_SIZE)
        self.uc.mem_map(HEAP_BASE, HEAP_SIZE)
        self._heap_ptr = HEAP_BASE + 0x1000
        self._alloc_live = {}
        self.uc.hook_add(UC_HOOK_CODE, self._hook_code,
                         begin=ADDR_MALLOC, end=ADDR_MALLOC + 1)
        self.uc.hook_add(UC_HOOK_CODE, self._hook_code,
                         begin=ADDR_FREE, end=ADDR_FREE + 1)
        self._run_init()

    # ---- emulator plumbing -------------------------------------------------
    def _hook_code(self, uc, address, size, user_data):
        if address == ADDR_MALLOC:
            size = struct.unpack("<I", uc.mem_read(self._stack_arg(0), 4))[0]
            ptr = self._heap_ptr
            self._heap_ptr = (ptr + size + 15) & ~0xF
            if self._heap_ptr >= HEAP_BASE + HEAP_SIZE:
                raise FlzdError("emulated heap exhausted")
            self._alloc_live[ptr] = size
            uc.mem_write(ptr, b"\0" * (((size + 0xFFF) & ~0xFFF) or 0x1000))
            self._do_ret(uc, ptr)
        elif address == ADDR_FREE:
            self._do_ret(uc, 0)

    def _stack_arg(self, index):
        esp = self.uc.reg_read(UC_X86_REG_ESP)
        return esp + 4 + 4 * index

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
        # count=0 -> run until the sentinel return address is hit; the codec is
        # guaranteed to terminate (decompress handles the whole payload).
        self.uc.emu_start(func, RET_MAGIC, timeout=timeout, count=0)
        return self.uc.reg_read(UC_X86_REG_EAX)

    def _run_init(self):
        """Fill the global level -> table-size array exactly like the game does."""
        self._call(ADDR_INIT, [])
        got = struct.unpack("<15I", self.uc.mem_read(
            IMAGE_BASE + TABLE_RVA, 60))
        expected = (1, 3, 5, 11, 17, 37, 67, 131, 257, 521, 1031, 2053, 5021, 9029, 18041)
        if tuple(got) != expected:
            raise FlzdError(f"init produced unexpected table: {got}")
        self.table = got

    # ---- public API --------------------------------------------------------
    def unpack(self, blob: bytes, max_out: int = 0) -> bytes:
        level, usize, payload = parse_header(blob)
        cap = max(usize, max_out)
        if cap == 0:
            return b""
        src_ptr = HEAP_BASE + BUFFER_OFFSET
        dst_ptr = src_ptr + ((len(blob) + 0xFFF) & ~0xFFF) + 0x1000
        if dst_ptr + cap > HEAP_BASE + HEAP_SIZE:
            raise FlzdError(f"buffers do not fit: cap={cap}")
        self.uc.mem_write(src_ptr, blob)
        self.uc.mem_write(dst_ptr, b"\0" * cap)
        ret = self._call(ADDR_UNPACK, [src_ptr, len(blob), dst_ptr, cap, 0])
        if ret < 0:
            raise FlzdError(f"flzd_unpack returned {ret} (level={level}, usize={usize})")
        if ret != usize:
            raise FlzdError(
                f"size mismatch: header says {usize}, codec wrote {ret}")
        return bytes(self.uc.mem_read(dst_ptr, ret))


if __name__ == "__main__":
    import zipfile
    exe = Path(r"C:\Games\LASR\LASR.exe")
    codec = FlzdCodec(exe)
    print("level -> table size:", dict(zip(range(15), codec.table)))
    z = zipfile.ZipFile(r"C:\Games\LASR\java\classes.zip")
    ok = True
    for name in sys.argv[1:] or ["game/Bet.class", "game/Bot.class", "util/Vector.class"]:
        data = codec.unpack(z.read(name))
        good = data[:4] in (b"TUFA", b"\xca\xfe\xba\xbe")
        ok &= good
        print(f"{name}: {len(data)} bytes -> {data[:8].hex()} "
              f"{'OK' if good else 'BAD'}")
    sys.exit(0 if ok else 1)
