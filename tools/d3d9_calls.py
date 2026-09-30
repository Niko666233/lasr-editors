"""Find and order the game's Direct3D 9 render calls (pass order recovery).

`d3d9.dll` is reached through COM, so every call is an indirect
`call dword ptr [reg + 4*slot]` and nothing shows up in the import table. But the
IDirect3DDevice9 vtable slot numbers are fixed, so scanning `.text` for those
indirect-call encodings recovers the sequence.

Slot numbers below were parsed from the real d3d9.h (apitrace/dxsdk mirror), NOT
from memory - an off-by-three guess about the IUnknown prefix is enough to make a
whole pass-order analysis nonsense.

    python tools/d3d9_calls.py --slots
    python tools/d3d9_calls.py --scan
    python tools/d3d9_calls.py --frame          # sequence inside the frame function
    python tools/d3d9_calls.py --fn 0x4ea000
"""
import argparse
import re
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXE = Path(r"C:\Games\LASR\LASR.exe")

# --- IDirect3DDevice9 slots (3..121; everything above belongs to the interfaces
# --- MS declares nested inside the same block: StateBlock, SwapChain, textures...)
SLOTS = {
    3: "QueryInterface", 4: "AddRef", 5: "Release", 6: "TestCooperativeLevel",
    7: "GetAvailableTextureMem", 8: "EvictManagedResources", 9: "GetDirect3D",
    10: "GetDeviceCaps", 11: "GetDisplayMode", 12: "GetCreationParameters",
    13: "SetCursorProperties", 14: "SetCursorPosition", 15: "ShowCursor",
    16: "CreateAdditionalSwapChain", 17: "GetSwapChain", 18: "GetNumberOfSwapChains",
    19: "Reset", 20: "Present", 21: "GetBackBuffer", 22: "GetRasterStatus",
    23: "SetDialogBoxMode", 24: "SetGammaRamp", 25: "GetGammaRamp",
    26: "CreateTexture", 27: "CreateVolumeTexture", 28: "CreateCubeTexture",
    29: "CreateVertexBuffer", 30: "CreateIndexBuffer", 31: "CreateRenderTarget",
    32: "CreateDepthStencilSurface", 33: "UpdateSurface", 34: "UpdateTexture",
    35: "GetRenderTargetData", 36: "GetFrontBufferData", 37: "StretchRect",
    38: "ColorFill", 39: "CreateOffscreenPlainSurface", 40: "SetRenderTarget",
    41: "GetRenderTarget", 42: "SetDepthStencilSurface", 43: "GetDepthStencilSurface",
    44: "BeginScene", 45: "EndScene", 46: "Clear", 47: "SetTransform",
    48: "GetTransform", 49: "MultiplyTransform", 50: "SetViewport", 51: "GetViewport",
    52: "SetMaterial", 53: "GetMaterial", 54: "SetLight", 55: "GetLight",
    56: "LightEnable", 57: "GetLightEnable", 58: "SetClipPlane", 59: "GetClipPlane",
    60: "SetRenderState", 61: "GetRenderState", 62: "CreateStateBlock",
    63: "BeginStateBlock", 64: "EndStateBlock", 65: "SetClipStatus",
    66: "GetClipStatus", 67: "GetTexture", 68: "SetTexture",
    69: "GetTextureStageState", 70: "SetTextureStageState", 71: "GetSamplerState",
    72: "SetSamplerState", 73: "ValidateDevice", 74: "SetPaletteEntries",
    75: "GetPaletteEntries", 76: "SetCurrentTexturePalette",
    77: "GetCurrentTexturePalette", 78: "SetScissorRect", 79: "GetScissorRect",
    80: "SetSoftwareVertexProcessing", 81: "GetSoftwareVertexProcessing",
    82: "SetNPatchMode", 83: "GetNPatchMode", 84: "DrawPrimitive",
    85: "DrawIndexedPrimitive", 86: "DrawPrimitiveUP", 87: "DrawIndexedPrimitiveUP",
    88: "ProcessVertices", 89: "CreateVertexDeclaration", 90: "SetVertexDeclaration",
    91: "GetVertexDeclaration", 92: "SetFVF", 93: "GetFVF", 94: "CreateVertexShader",
    95: "SetVertexShader", 96: "GetVertexShader", 97: "SetVertexShaderConstantF",
    98: "GetVertexShaderConstantF", 99: "SetVertexShaderConstantI",
    100: "GetVertexShaderConstantI", 101: "SetVertexShaderConstantB",
    102: "GetVertexShaderConstantB", 103: "SetStreamSource", 104: "GetStreamSource",
    105: "SetStreamSourceFreq", 106: "GetStreamSourceFreq", 107: "SetIndices",
    108: "GetIndices", 109: "CreatePixelShader", 110: "SetPixelShader",
    111: "GetPixelShader", 112: "SetPixelShaderConstantF",
    113: "GetPixelShaderConstantF", 114: "SetPixelShaderConstantI",
    115: "GetPixelShaderConstantI", 116: "SetPixelShaderConstantB",
    117: "GetPixelShaderConstantB", 118: "DrawRectPatch", 119: "DrawTriPatch",
    120: "DeletePatch", 121: "CreateQuery",
}
# slots that mark frame/pass structure rather than per-draw setup
DRAW = {84, 85, 86, 87}
FRAME = {20, 44, 45, 46, 40, 42}


def pe_text(path):
    d = path.read_bytes()
    e_lfanew = struct.unpack_from("<I", d, 0x3C)[0]
    assert d[e_lfanew:e_lfanew + 4] == b"PE\0\0", "not a PE"
    nsec = struct.unpack_from("<H", d, e_lfanew + 6)[0]
    optsz = struct.unpack_from("<H", d, e_lfanew + 20)[0]
    base = struct.unpack_from("<I", d, e_lfanew + 24 + 28)[0]
    sec = e_lfanew + 24 + optsz
    for i in range(nsec):
        o = sec + i * 40
        name = d[o:o + 8].rstrip(b"\0").decode("latin1")
        vsz, va, rsz, ra = struct.unpack_from("<IIII", d, o + 8)
        if name == ".text":
            return d, base, va, d[ra:ra + rsz], rsz
    raise SystemExit(".text not found")


def scan():
    """Return [(va, slot, reg, kind)] for indirect calls / vtable-pointer loads.

    MSVC caches the vtable entry (`mov ebx,[esi+0xf0]`) and then does a register
    indirect `call ebx`, so `call [reg+disp]` alone misses most render calls.
    """
    d, base, text_va, text, size = pe_text(EXE)
    hits = []
    i = 0
    while i < size - 7:
        b = text[i]
        if b == 0xFF and 0x50 <= text[i + 1] <= 0x57:        # call [reg+disp8]
            disp = text[i + 2]
            if disp % 4 == 0 and disp // 4 in SLOTS:
                hits.append((base + text_va + i, disp // 4, text[i + 1] & 7, "call"))
            i += 3
            continue
        if b == 0xFF and 0x90 <= text[i + 1] <= 0x97:        # call [reg+disp32]
            disp = struct.unpack_from("<I", text, i + 2)[0]
            if disp < 0x400 and disp % 4 == 0 and disp // 4 in SLOTS:
                hits.append((base + text_va + i, disp // 4, text[i + 1] & 7, "call"))
            i += 6
            continue
        if b == 0x8B:
            m = text[i + 1]
            mod, rm = m >> 6, m & 7
            if rm == 4:                                      # SIB form: skip
                i += 1
                continue
            if mod == 1:                                     # mov r32,[reg+disp8]
                disp = text[i + 2]
                if disp % 4 == 0 and disp // 4 in SLOTS:
                    hits.append((base + text_va + i, disp // 4, rm, "load"))
                i += 3
                continue
            if mod == 2:                                     # mov r32,[reg+disp32]
                disp = struct.unpack_from("<I", text, i + 2)[0]
                if disp < 0x400 and disp % 4 == 0 and disp // 4 in SLOTS:
                    hits.append((base + text_va + i, disp // 4, rm, "load"))
                i += 6
                continue
        i += 1
    return hits


REG = ["eax", "ecx", "edx", "ebx", "esp", "ebp", "esi", "edi"]
# slots that only a real IDirect3DDevice9 would be asked for
CORE = {60, 68, 72, 90, 92, 95, 97, 103, 107, 110, 112, 40, 42} | DRAW
# slots a real renderer must touch often - a group without them is not a device
MUST = {60, 68} | DRAW


def device_groups(hits):
    """Group (function, register) pairs and keep the ones that behave like a device."""
    d, base, text_va, text, size = pe_text(EXE)
    g = defaultdict(list)
    for va, slot, reg, kind in hits:
        f = prologue_before(text, text_va, base, va - base - text_va)
        g[(f, reg)].append((va, slot, kind))
    good = {}
    for k, lst in g.items():
        slots = {s for _, s, _ in lst}
        if len(slots) >= 3 and len(slots & CORE) >= 3 and (slots & MUST):
            good[k] = sorted(lst)
    return good


def prologue_before(text, text_va, base, off, window=0x2000):
    """Heuristic function start: nearest 'push ebp; mov ebp,esp' / SEH prologue."""
    lo = max(0, off - window)
    best = None
    i = off
    while i > lo:
        i -= 1
        if text[i] == 0x55 and text[i + 1] == 0x8B and text[i + 2] == 0xEC:
            best = i
            break
        if text[i] == 0x6A and text[i + 1] == 0xFF and text[i + 2] == 0x68:
            best = i
            break
    return base + text_va + (best if best is not None else lo)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slots", action="store_true")
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--frame", action="store_true")
    ap.add_argument("--draws", action="store_true")
    a = ap.parse_args()

    if a.slots:
        for s in sorted(SLOTS):
            print(f"  {s:>3} 0x{s*4:03x}  {SLOTS[s]}")
        return 0

    hits = scan()
    good = device_groups(hits)
    if a.scan or not (a.frame or a.fn or a.draws):
        print(f"设备 vtable 间接调用命中 {len(hits)} 处；"
              f"按（函数,寄存器）分组并筛出像设备的 {len(good)} 组")
        c = Counter(SLOTS[s] for g in good.values() for _, s, _ in g)
        print("=== 筛后按槽位统计 ===")
        for name, n in c.most_common():
            slot = next(s for s, v in SLOTS.items() if v == name)
            tag = " ★DRAW" if slot in DRAW else (" ◆FRAME" if slot in FRAME else "")
            print(f"  {n:>5}x  {name}{tag}")
        print(f"\n=== 像设备的（函数,寄存器）组 {len(good)} 个 ===")
        for (fva, reg), lst in sorted(good.items(), key=lambda kv: -len(kv[1])):
            ndraw = sum(1 for _, s, _ in lst if s in DRAW)
            mark = "◆帧" if any(s in (20, 44, 45) for _, s, _ in lst) else ("★画" if ndraw else "  ")
            print(f" {mark} 0x{fva:06x} [{REG[reg]}] 调用{len(lst):>3}（DRAW {ndraw}）: "
                  + ", ".join(f"{name}×{n}" for name, n in Counter(SLOTS[s] for _, s, _ in lst).most_common(8)))
    if a.frame or a.draws:
        want = (lambda lst: any(s in (20, 44, 45) for _, s, _ in lst)) if a.frame else \
               (lambda lst: any(s in DRAW for _, s, _ in lst))
        for (fva, reg), lst in sorted(good.items()):
            if not want(lst):
                continue
            print(f"\n### 0x{fva:06x} [{REG[reg]}] 共 {len(lst)} 次设备访问")
            for va, s, kind in lst:
                print(f"   0x{va:06x}  {SLOTS[s]:<26} {kind}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
