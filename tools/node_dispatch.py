"""Find the node-type dispatcher: load `word [node+0x14]` then jmp via a table."""
import re
import struct

d = open(r"C:\Games\LASR\LASR.exe", "rb").read()
IB = 0x400000
TL, TH = 0x1000, 0x2E5809
REGS = ["eax", "ecx", "edx", "ebx", "esp", "ebp", "esi", "edi"]
MOD = 0xC7
SCALE4 = 0x85

sites = [0x1000 + m.start() for m in re.finditer(rb"\x0f\xb7(.)\x14", d[0x1000:0x2E6009], re.S)]
print(f"{len(sites)} 'movzx r32, word ptr [reg+0x14]' sites (node type loads)\n")

print("=== jump tables reached within 0x140 bytes of a node-type load ===")
n = 0
for s in sites:
    for j in range(s, min(s + 0x140, TH)):
        if d[j:j + 2] == b"\xff\x24" and (d[j + 2] % 256) % 64 == MOD % 64:
            modrm = d[j + 2]
            if (modrm % 256) // 8 % 8 == (SCALE4 % 8):
                tva = struct.unpack_from("<I", d, j + 3)[0]
                print(f"  node-type load @ {s:#x} -> jmp [{REGS[(modrm>>3)%8]}*4+{tva:#x}] "
                      f"@ {j:#x}   table rva {tva-IB:#x}")
                n += 1
print(f"  ({n} found)\n")

print("=== every 'jmp [reg*4+disp32]' whose table lies in .text (SIB scale must be 4) ===")
for m in re.finditer(rb"\xff\x24", d[0x1000:0x2E6009]):
    o = 0x1000 + m.start()
    modrm = d[o + 2]
    if modrm // 8 % 8 != 4:
        continue
    if modrm // 64 % 4 != 0:
        continue
    tva = struct.unpack_from("<I", d, o + 3)[0]
    rva = tva - IB
    if TL <= rva < TH:
        print(f"  {o:#x}: jmp [{REGS[modrm % 8]}*4+{tva:#x}]  table_rva {rva:#x}")
