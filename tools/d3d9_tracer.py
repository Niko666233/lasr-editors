"""Dynamic render-trace: recover the pass order with only Python (no compiler).

There is no C toolchain / debugger on this machine, so this is a miniature Windows
debugger built on ctypes:

  1. launch LASR.exe with DEBUG_ONLY_THIS_PROCESS;
  2. hardware-execute breakpoint on d3d9.dll!Direct3DCreate9 (RVA from the PE export
     table, base from the debug LOAD_DLL event);
  3. at its return, EAX = IDirect3D9* -> read the vtable -> slot 16 = CreateDevice;
  4. at CreateDevice's return, read ppDevice (arg 6) -> IDirect3DDevice9* ;
  5. read the device vtable and arm execute breakpoints on 4 slots
     (Present / BeginScene / Clear / DrawIndexedPrimitive);
  6. every hit logs `[esp]` = the RETURN ADDRESS, which is exactly the engine
     function that issued the call - that is the pass order;
  7. kill after a wall-clock budget so it does not hold the screen.

Hardware breakpoints need no code injection and no memory patching: they live in the
thread context (Dr0..Dr3 + Dr7), so a read-only target stays untouched.

    python tools/d3d9_tracer.py --run --seconds 25
    python tools/d3d9_tracer.py --symbolize
"""
import argparse
import ctypes
import json
import struct
import sys
import time
from ctypes import wintypes as wt
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXE = r"C:\Games\LASR\LASR.exe"
GAME_DIR = r"C:\Games\LASR"
D3D9 = r"C:\Windows\SysWOW64\d3d9.dll"
LOG = ROOT / "out_tracer.jsonl"

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)

DEBUG_ONLY_THIS_PROCESS = 0x00000002
DBG_CONTINUE = 0x00010002
DBG_EXCEPTION_NOT_HANDLED = 0x80010001
EXCEPTION_BREAKPOINT = 0x80000003

CONTEXT_i386 = 0x00010000
CONTEXT_CONTROL = CONTEXT_i386 | 0x1
CONTEXT_INTEGER = CONTEXT_i386 | 0x2
CONTEXT_SEGMENTS = CONTEXT_i386 | 0x4
CONTEXT_DEBUG_REGISTERS = CONTEXT_i386 | 0x10

# IDirect3DDevice9 slots (from d3d9.h, verified)
# IDirect3DDevice9 vtable slots.
# The earlier d3d9.h parse was systematically +3 (it counted three extra entries), so
# Present read as 20 instead of 17 and DrawIndexedPrimitive as 85 instead of 82 - which
# silently broke every hook. These are the canonical values; the run itself verifies
# them (Present must fire once per frame).
SLOT = {"Present": 17, "BeginScene": 41, "EndScene": 42, "Clear": 43,
        "SetRenderTarget": 37, "SetDepthStencilSurface": 39,
        "DrawPrimitive": 81, "DrawIndexedPrimitive": 82,
        "DrawPrimitiveUP": 83, "DrawIndexedPrimitiveUP": 84}
WATCH = ["Present", "BeginScene", "Clear", "DrawIndexedPrimitive"]   # only 4 hw slots


# Only 4 hardware execute slots exist, so the watch set is rotated between frames:
# group A gives the frame skeleton, group B gives render-target/depth switches.
GROUP_A = ["Present", "BeginScene", "Clear", "DrawIndexedPrimitive"]
GROUP_B = ["SetRenderTarget", "SetDepthStencilSurface", "DrawIndexedPrimitive", "Present"]
ROTATE_EVERY = 12      # frames per group
NOHOOK = False         # --nohook: attach as debugger but arm nothing (control run)


class STARTUPINFO(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("lpReserved", wt.LPWSTR), ("lpDesktop", wt.LPWSTR),
                ("lpTitle", wt.LPWSTR), ("dwX", wt.DWORD), ("dwY", wt.DWORD),
                ("dwXSize", wt.DWORD), ("dwYSize", wt.DWORD),
                ("dwXCountChars", wt.DWORD), ("dwYCountChars", wt.DWORD),
                ("dwFillAttribute", wt.DWORD), ("dwFlags", wt.DWORD),
                ("wShowWindow", wt.WORD), ("cbReserved2", wt.WORD),
                ("lpReserved2", ctypes.c_void_p), ("hStdInput", wt.HANDLE),
                ("hStdOutput", wt.HANDLE), ("hStdError", wt.HANDLE)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", wt.HANDLE), ("hThread", wt.HANDLE),
                ("dwProcessId", wt.DWORD), ("dwThreadId", wt.DWORD)]


class CONTEXT(ctypes.Structure):
    """x86 CONTEXT; full size 0x2CC, only the debug/control parts are used."""
    _fields_ = [("ContextFlags", wt.DWORD),
                ("Dr0", wt.DWORD), ("Dr1", wt.DWORD), ("Dr2", wt.DWORD),
                ("Dr3", wt.DWORD), ("Dr6", wt.DWORD), ("Dr7", wt.DWORD),
                ("FloatSave", ctypes.c_byte * 112),
                ("SegGs", wt.DWORD), ("SegFs", wt.DWORD), ("SegEs", wt.DWORD),
                ("SegDs", wt.DWORD), ("Edi", wt.DWORD), ("Esi", wt.DWORD),
                ("Ebx", wt.DWORD), ("Edx", wt.DWORD), ("Ecx", wt.DWORD),
                ("Eax", wt.DWORD), ("Ebp", wt.DWORD), ("Eip", wt.DWORD),
                ("SegCs", wt.DWORD), ("EFlags", wt.DWORD), ("Esp", wt.DWORD),
                ("SegSs", wt.DWORD), ("ExtendedRegisters", ctypes.c_byte * 512)]


class DEBUG_U(ctypes.Union):
    """DEBUG_EVENT's union: 8-byte aligned, so there are 4 bytes of padding after
    dwThreadId on a 64-bit debugger - the payload starts at offset 16, not 12."""
    _fields_ = [("align", ctypes.c_ulonglong), ("buf", ctypes.c_byte * 168)]


class DEBUG_EVENT(ctypes.Structure):
    _fields_ = [("dwDebugEventCode", wt.DWORD), ("dwProcessId", wt.DWORD),
                ("dwThreadId", wt.DWORD), ("u", DEBUG_U)]


# debug event codes (winbase.h) - getting these wrong is silent and total
EV_EXCEPTION = 1
EV_CREATE_THREAD = 2
EV_CREATE_PROCESS = 3
EV_EXIT_THREAD = 4
EV_EXIT_PROCESS = 5
EV_LOAD_DLL = 6
EV_UNLOAD_DLL = 7
EV_OUTPUT_DEBUG_STRING = 8


k32.CreateProcessW.argtypes = [wt.LPCWSTR, wt.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
                               wt.BOOL, wt.DWORD, ctypes.c_void_p, wt.LPCWSTR,
                               ctypes.POINTER(STARTUPINFO), ctypes.POINTER(PROCESS_INFORMATION)]
k32.WaitForDebugEvent.argtypes = [ctypes.POINTER(DEBUG_EVENT), wt.DWORD]
k32.ContinueDebugEvent.argtypes = [wt.DWORD, wt.DWORD, wt.DWORD]
k32.OpenThread.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.OpenThread.restype = wt.HANDLE
k32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                  ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.ReadProcessMemory.restype = wt.BOOL
k32.TerminateProcess.argtypes = [wt.HANDLE, wt.UINT]
k32.Wow64GetThreadContext.argtypes = [wt.HANDLE, ctypes.POINTER(CONTEXT)]
k32.Wow64SetThreadContext.argtypes = [wt.HANDLE, ctypes.POINTER(CONTEXT)]
k32.GetThreadContext.argtypes = [wt.HANDLE, ctypes.POINTER(CONTEXT)]
k32.SetThreadContext.argtypes = [wt.HANDLE, ctypes.POINTER(CONTEXT)]
k32.GetFinalPathNameByHandleW.argtypes = [wt.HANDLE, wt.LPWSTR, wt.DWORD, wt.DWORD]
k32.GetFinalPathNameByHandleW.restype = wt.DWORD
psapi.EnumProcessModules.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD,
                                     ctypes.POINTER(wt.DWORD)]
psapi.EnumProcessModulesEx.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD,
                                       ctypes.POINTER(wt.DWORD), wt.DWORD]
psapi.GetModuleFileNameExW.argtypes = [wt.HANDLE, wt.HMODULE, wt.LPWSTR, wt.DWORD]

# 64-bit debugger vs 32-bit target: GetThreadContext does not work across WOW64,
# Wow64GetThreadContext is mandatory (and it carries the Dr registers).
WOW64 = ctypes.sizeof(ctypes.c_void_p) == 8
_getctx = k32.Wow64GetThreadContext if WOW64 else k32.GetThreadContext
_setctx = k32.Wow64SetThreadContext if WOW64 else k32.SetThreadContext
DIAG = {"events": {}, "ctx_fail": 0, "exceptions": {}}


def read_mem(h, addr, size):
    buf = (ctypes.c_ubyte * size)()          # c_byte is signed: >=0x80 would make
    got = ctypes.c_size_t(0)                 # bytes(...) raise
    if not k32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, size, ctypes.byref(got)):
        return None
    return bytes(buf[:got.value])


def u32(h, addr):
    b = read_mem(h, addr, 4)
    return struct.unpack("<I", b)[0] if b and len(b) == 4 else None


def export_rva(path, name):
    d = Path(path).read_bytes()
    e = struct.unpack_from("<I", d, 0x3C)[0]
    nsec = struct.unpack_from("<H", d, e + 6)[0]
    optsz = struct.unpack_from("<H", d, e + 20)[0]
    opt = e + 24
    exp_rva, exp_sz = struct.unpack_from("<II", d, opt + 96)
    secs = []
    for i in range(nsec):
        o = opt + optsz + i * 40
        vsz, va, rsz, ra = struct.unpack_from("<IIII", d, o + 8)
        secs.append((va, vsz, ra, rsz))

    def off(r):
        for va, vsz, ra, rsz in secs:
            if va <= r < va + max(vsz, rsz):
                return ra + (r - va)
        return None

    b = off(exp_rva)
    nnames = struct.unpack_from("<I", d, b + 24)[0]
    names_rva, ords_rva = struct.unpack_from("<II", d, b + 32)
    for i in range(nnames):
        nr = struct.unpack_from("<I", d, off(names_rva) + i * 4)[0]
        s = d[off(nr):d.index(b"\0", off(nr))].decode("latin1")
        if s == name:
            ordi = struct.unpack_from("<H", d, off(ords_rva) + i * 2)[0]
            fr = struct.unpack_from("<I", d, b + 28)[0]
            return struct.unpack_from("<I", d, off(fr) + ordi * 4)[0]
    return None


class Tracer:
    def __init__(self, hproc, pid, main_tid):
        self.h = hproc
        self.pid = pid
        self.main_tid = main_tid
        self.bps = {}          # slot -> tag
        self.tag_addr = {}     # tag -> addr
        self.phase = "wait_dll"
        self.device = None
        self.ppdevice = None
        self.log = []
        self.frames = 0
        self.d3d9_base = None
        self.threads = {main_tid}
        self.start = time.time()
        self.fh = open(LOG, "w", encoding="utf-8")
        self._wrote = 0
        self.groups = [GROUP_A, GROUP_B]
        self.gi = 0
        self.pending = {}      # tid -> (slot, addr) waiting for its WX86 single-step

    def say(self, ev):
        """Append + flush immediately so a long run can be watched live."""
        self.log.append(ev)
        while self._wrote < len(self.log):
            self.fh.write(json.dumps(self.log[self._wrote]) + "\n")
            self._wrote += 1
        self.fh.flush()

    def rotate(self, tid):
        self.gi = (self.gi + 1) % len(self.groups)
        grp = self.groups[self.gi]
        for slot in range(4):
            self.clear(tid, slot)
        for slot, name in enumerate(grp):
            for t in list(self.threads):
                addr = u32(self.h, self.vt + SLOT[name] * 4) if self.vt else None
                if addr:
                    self.arm(t, slot, addr, name)
        self.say({"t": round(time.time() - self.start, 3), "kind": "rotate",
                  "group": grp, "frame": self.frames})

    # ---- breakpoints -------------------------------------------------
    def ctx(self, tid):
        h = k32.OpenThread(0x0008 | 0x0010 | 0x0002, False, tid)   # GET/SET/SUSPEND
        if not h:
            DIAG["ctx_fail"] += 1
            return None, None
        c = CONTEXT()
        c.ContextFlags = CONTEXT_DEBUG_REGISTERS | CONTEXT_CONTROL | CONTEXT_INTEGER
        if not _getctx(h, ctypes.byref(c)):
            DIAG["ctx_fail"] += 1
            k32.CloseHandle(h)
            return None, None
        return h, c

    def arm(self, tid, slot, addr, tag):
        if NOHOOK:
            self.bps[slot] = tag
            self.tag_addr[tag] = addr
            return True
        h, c = self.ctx(tid)
        if not h:
            return False
        setattr(c, f"Dr{slot}", addr)
        # local enable bit = 2*slot ; R/W=00 (exec) ; LEN=00 (1 byte)
        c.Dr7 = (c.Dr7 & ~(0x3 << (16 + 4 * slot))) | (1 << (2 * slot))
        c.Dr6 = 0
        ok = _setctx(h, ctypes.byref(c))
        k32.CloseHandle(h)
        if ok:
            self.bps[slot] = tag
            self.tag_addr[tag] = addr
        return bool(ok)

    def arm_all(self, slot, addr, tag):
        for t in list(self.threads):
            self.arm(t, slot, addr, tag)

    def clear(self, tid, slot):
        h, c = self.ctx(tid)
        if not h:
            return
        setattr(c, f"Dr{slot}", 0)
        c.Dr7 &= ~(0x3 << (2 * slot))
        _setctx(h, ctypes.byref(c))
        k32.CloseHandle(h)

    # ---- module ------------------------------------------------------
    def find_d3d9(self):
        """Locate d3d9.dll in the target.

        On 64-bit Windows, plain EnumProcessModules does not reliably enumerate a
        WOW64 target's modules; EnumProcessModulesEx(LIST_MODULES_ALL) does.
        """
        mods = (wt.HMODULE * 1024)()
        need = wt.DWORD(0)
        ok = psapi.EnumProcessModulesEx(self.h, mods, ctypes.sizeof(mods),
                                        ctypes.byref(need), 0x3)      # LIST_MODULES_ALL
        if not ok:
            ok = psapi.EnumProcessModules(self.h, mods, ctypes.sizeof(mods),
                                          ctypes.byref(need))
        if not ok:
            if not DIAG.get("moderr"):
                DIAG["moderr"] = True
                print("  [诊断] 枚举模块失败, GetLastError =", ctypes.get_last_error())
            return None
        n = need.value // ctypes.sizeof(wt.HMODULE)
        if not DIAG.get("modlist"):
            DIAG["modlist"] = True
            print(f"  [诊断] 模块数 {n}")
        found = None
        for i in range(n):
            p = ctypes.create_unicode_buffer(512)
            if psapi.GetModuleFileNameExW(self.h, mods[i], p, 512):
                if not DIAG.get("modshown") and i < 6:
                    print(f"  [诊断] 模块[{i}] 0x{int(mods[i]):08x} {p.value}")
                if p.value.lower().endswith("d3d9.dll"):
                    found = int(mods[i])
        DIAG["modshown"] = True
        return found

    def dump_threads(self):
        """Where is it stuck? EIP of every thread we know about."""
        for t in sorted(self.threads):
            h, c = self.ctx(t)
            if not h:
                print(f"  线程 {t}: 无法读取上下文")
                continue
            print(f"  线程 {t}: EIP=0x{c.Eip:08x} ({self.describe_addr(c.Eip)}) "
                  f"ESP=0x{c.Esp:08x} Dr0=0x{c.Dr0:08x} Dr6=0x{c.Dr6:08x} Dr7=0x{c.Dr7:08x}")
            k32.CloseHandle(h)

    def describe_addr(self, addr):
        """Which loaded module does this address belong to?"""
        mods = (wt.HMODULE * 1024)()
        need = wt.DWORD(0)
        if not psapi.EnumProcessModules(self.h, mods, ctypes.sizeof(mods),
                                        ctypes.byref(need)):
            return "?"
        n = need.value // ctypes.sizeof(wt.HMODULE)
        best = None
        for i in range(n):
            b = int(mods[i])
            if b <= addr:
                p = ctypes.create_unicode_buffer(512)
                psapi.GetModuleFileNameExW(self.h, mods[i], p, 512)
                if best is None or b > best[0]:
                    best = (b, p.value)
        if not best:
            return "?"
        return f"{best[1]}+0x{addr - best[0]:x}"

    # ---- event handling ---------------------------------------------
    def on_breakpoint(self, tid):
        h, c = self.ctx(tid)
        if not h:
            return
        # On WOW64 a hardware breakpoint produces TWO events: the trap itself, then a
        # WX86 single-step. Re-arming while the single-step is outstanding makes the
        # trap fire again on the same instruction forever (7854 identical records).
        # So: clear the slot on the hit, and only re-arm it on the following event.
        pd = self.pending.pop(tid, None)
        if pd and not (c.Dr6 & (1 << pd[0])):
            self.arm(tid, pd[0], pd[1], self.bps.get(pd[0], ""))
            diag = {"t": round(time.time() - self.start, 3), "kind": "rearm",
                    "slot": pd[0], "tag": self.bps.get(pd[0])}
            self.say(diag)
            k32.CloseHandle(h)
            return
        dr6 = c.Dr6
        slot = next((i for i in range(4) if dr6 & (1 << i)), None)
        ret = u32(self.h, c.Esp)
        if slot is None:
            # initial ntdll breakpoint or a temporary one: just report
            self.say({"t": round(time.time() - self.start, 3), "kind": "bp",
                             "ret": hex(ret) if ret else None, "tid": tid})
            if self.phase == "wait_dll":
                # Race-free hook: Direct3DCreate9 is called the moment d3d9.dll has
                # loaded, so arming on the LOAD_DLL event can miss it. The call site
                # inside LASR.exe has a fixed static address, knowable from the very
                # first debug event.
                self.arm(tid, 1, 0x502a85, "CALLSITE")
                self.phase = "callsite"
                base = self.find_d3d9()
                if base:
                    rva = export_rva(D3D9, "Direct3DCreate9")
                    if rva:
                        self.d3d9_base = base
                        self.arm(tid, 0, base + rva, "Direct3DCreate9")
                        self.phase = "create9"
            k32.CloseHandle(h)
            return
        tag = self.bps.get(slot)
        if tag in ("Direct3DCreate9", "CALLSITE_ret"):
            # returning from it: EAX = IDirect3D9*
            obj = c.Eax
            vt = u32(self.h, obj) if obj else None
            cd = u32(self.h, vt + 16 * 4) if vt else None      # slot 16 = CreateDevice
            self.say({"t": round(time.time() - self.start, 3), "kind": "create9",
                      "id3d9": hex(obj) if obj else None,
                      "createDevice": hex(cd) if cd else None})
            # clear BOTH slots first: leaving this breakpoint armed makes the game spin
            # (breakpoint -> WX86 single-step -> re-execute -> breakpoint ...), which
            # burned the whole event budget. Won the hard way.
            self.clear(tid, 0)
            self.clear(tid, 1)
            if cd:
                self.arm(tid, 0, cd, "CreateDevice")
                self.phase = "createdevice"
        elif tag == "CreateDevice":
            # IDirect3D9::CreateDevice(this, Adapter, DeviceType, hFocusWindow,
            #   BehaviorFlags, pPresentationParameters, ppReturnedDeviceInterface)
            # = 7 stdcall args -> ppReturnedDeviceInterface is at [esp+4+6*4] = [esp+28].
            # Off-by-4 here reads BackBufferWidth instead (0x400 = 1024, which is how
            # this was caught).
            pp = u32(self.h, c.Esp + 28)
            pp_alt = u32(self.h, c.Esp + 24)
            self.ppdevice = pp
            self.say({"t": round(time.time() - self.start, 3),
                      "kind": "createdevice_enter",
                      "ppDevice": hex(pp) if pp else None,
                      "esp24": hex(pp_alt) if pp_alt else None,
                      "esp_esp": hex(c.Esp)})
            self.clear(tid, 0)
            self.arm(tid, 0, ret, "CreateDevice_ret")
            self.phase = "createdevice_ret"
        elif tag == "CreateDevice_ret":
            dev = u32(self.h, self.ppdevice) if self.ppdevice else None
            vt = u32(self.h, dev) if dev else None
            self.device = dev
            self.clear(tid, 0)
            self.say({"t": round(time.time() - self.start, 3), "kind": "device",
                             "device": hex(dev) if dev else None,
                             "vtable": hex(vt) if vt else None})
            if vt:
                self.vt = vt
                slots = {}
                for i, name in enumerate(self.groups[0]):
                    addr = u32(self.h, vt + SLOT[name] * 4)
                    slots[name] = hex(addr) if addr else None
                    self.arm_all(i, addr, name)
                self.say({"t": round(time.time() - self.start, 3), "kind": "slots",
                          "vtable": hex(vt), "d3d9_base": hex(self.d3d9_base) if self.d3d9_base else None,
                          "slots": slots})
                self.phase = "trace"
        elif tag == "CALLSITE":
            # The breakpoint sits ON the `call` instruction, so the top of stack is
            # still the pushed argument (0x20 = D3D_SDK_VERSION) - the return address
            # is the next instruction, a static value. Cross-check it against [esp+4].
            ret_next = 0x502a85 + 5
            pushed = u32(self.h, c.Esp)
            below = u32(self.h, c.Esp + 4)
            self.say({"t": round(time.time() - self.start, 3), "kind": "callsite",
                      "ret": hex(ret_next), "esp_top": hex(pushed) if pushed else None,
                      "esp_plus4": hex(below) if below else None})
            self.clear(tid, 1)
            self.arm(tid, 1, ret_next, "CALLSITE_ret")
            self.phase = "callsite_ret"
        else:
            # a watched device method
            args = [u32(self.h, c.Esp + 4 + 4 * k) for k in range(4)]
            self.say({"t": round(time.time() - self.start, 3), "kind": tag,
                             "slot": slot, "ret": hex(ret) if ret else None, "args": args,
                             "esp": hex(c.Esp)})
            if tag == "Present":
                self.frames += 1
                if self.frames % ROTATE_EVERY == 0:
                    k32.CloseHandle(h)
                    self.rotate(tid)
                    return
            # clear the slot now; the following WX86 single-step re-arms it (see the
            # top of this method). Re-arming here instead causes an endless loop.
            self.clear(tid, slot)
            self.pending[tid] = (slot, self.tag_addr[tag])
            k32.CloseHandle(h)
            return
        k32.CloseHandle(h)


def run(seconds=25, max_events=8000, nohook=False, probe=False):
    si = STARTUPINFO()
    si.cb = ctypes.sizeof(si)
    pi = PROCESS_INFORMATION()
    cmd = ctypes.create_unicode_buffer(EXE)
    ok = k32.CreateProcessW(EXE, cmd, None, None, False,
                            DEBUG_ONLY_THIS_PROCESS, None, GAME_DIR,
                            ctypes.byref(si), ctypes.byref(pi))
    if not ok:
        print("CreateProcess 失败:", ctypes.get_last_error())
        return 1
    print(f"已启动 pid={pi.dwProcessId}（调试模式, nohook={nohook}），预算 {seconds}s")
    ev = DEBUG_EVENT()
    tr = Tracer(pi.hProcess, pi.dwProcessId, pi.dwThreadId)
    deadline = time.time() + seconds
    n = 0
    last_hb = time.time()
    while time.time() < deadline and n < max_events:
        if time.time() - last_hb >= 20:
            last_hb = time.time()
            msg = (f"  [心跳] {int(time.time()-tr.start)}s 事件{n} 阶段={tr.phase} "
                   f"记录{len(tr.log)} 帧{tr.frames}")
            if probe:
                try:
                    sys.path.insert(0, str(ROOT / "tools"))
                    import run_probe as RP
                    cpu = RP.cpu_times(tr.pid)
                    ws = RP.windows_of(tr.pid)
                    vis = [(w["title"], w["class"]) for w in ws if w["visible"]]
                    msg += f" CPU={cpu} 可见窗口={vis}"
                except Exception as e:
                    msg += f" 探活失败: {e}"
            print(msg)
        if not k32.WaitForDebugEvent(ctypes.byref(ev), 500):
            if time.time() > deadline:
                break
            continue
        n += 1
        code = ev.dwDebugEventCode
        DIAG["events"][code] = DIAG["events"].get(code, 0) + 1
        status = DBG_CONTINUE
        if code == EV_EXCEPTION:
            raw = bytes(ev.u.buf)[:32]
            if DIAG.get("shown", 0) < 4:
                DIAG["shown"] = DIAG.get("shown", 0) + 1
                print(f"  [原始] code={code} tid={ev.dwThreadId} u[:32]={raw.hex()}")
            exc_code, _fl, _rp, exc_addr = struct.unpack_from("<IIII", bytes(ev.u.buf), 0)
            DIAG["exceptions"][hex(exc_code)] = DIAG["exceptions"].get(hex(exc_code), 0) + 1
            if exc_code in (EXCEPTION_BREAKPOINT, 0x4000001F, 0x4000001E):
                # 0x80000003 = normal int3; 0x4000001F/0x4000001E = WOW64 breakpoint /
                # single-step, which is what a 64-bit debugger sees from a 32-bit target
                if ev.dwThreadId not in tr.threads:
                    tr.threads.add(ev.dwThreadId)
                tr.on_breakpoint(ev.dwThreadId)
            else:
                status = DBG_EXCEPTION_NOT_HANDLED
        elif code == EV_LOAD_DLL:
            hfile = struct.unpack_from("<Q" if WOW64 else "<I", bytes(ev.u.buf), 0)[0]
            nm = ""
            if hfile:
                p = ctypes.create_unicode_buffer(1024)
                if k32.GetFinalPathNameByHandleW(wt.HANDLE(hfile), p, 1024, 0):
                    nm = p.value
                k32.CloseHandle(wt.HANDLE(hfile))
            tr.say({"t": round(time.time() - tr.start, 3), "kind": "dll",
                           "name": nm.rsplit("\\", 1)[-1]})
            if tr.phase == "wait_dll" and nm.lower().endswith("d3d9.dll"):
                tr.d3d9_base = tr.find_d3d9()
                if tr.d3d9_base:
                    rva = export_rva(D3D9, "Direct3DCreate9")
                    if rva:
                        tr.arm(ev.dwThreadId, 0, tr.d3d9_base + rva, "Direct3DCreate9")
                        tr.phase = "create9"
                        tr.say({"t": round(time.time() - tr.start, 3), "kind": "rotate",
                                "group": tr.groups[0], "frame": 0})
        elif code == EV_OUTPUT_DEBUG_STRING:
            # OUTPUT_DEBUG_STRING_INFO lives at the union's offset 0 (= absolute 16,
            # after the 4-byte alignment padding), laid out as
            # { LPSTR lpDebugStringData; WORD fUnicode; WORD nDebugStringLength } -
            # so pointer at +0, flags at +4, length (in CHARACTERS) at +6.
            sp = struct.unpack_from("<I", bytes(ev.u.buf), 0)[0]
            is_uni, slen = struct.unpack_from("<HH", bytes(ev.u.buf), 4)
            txt = ""
            if sp and slen:
                try:
                    raw = tr.read_mem(sp, slen * 2 if is_uni else slen)
                    if raw:
                        raw = bytes(raw)
                        txt = (raw.decode("utf-16-le", "replace") if is_uni
                               else raw.decode("latin1", "replace"))
                except Exception as e:
                    txt = f"<读取失败 {e}>"
            txt = txt.rstrip("\x00\r\n")
            DIAG["dbgstr"] = DIAG.get("dbgstr", 0) + 1
            tr.say({"t": round(time.time() - tr.start, 3), "kind": "dbgstr",
                    "unicode": bool(is_uni), "ptr": hex(sp), "len": slen, "s": txt[:400]})
            if not DIAG.get("probe_noted") and (not sp or not slen):
                DIAG["probe_noted"] = 1
                print("  [★] 空串 OutputDebugString —— 这是进程在探测「有没有调试器挂载」的"
                      "经典手法；说明本进程能察觉到我的调试器（观察者效应风险）。")
            if DIAG["dbgstr"] <= 40:
                print(f"  [游戏调试输出] {txt[:300]}")
        elif code == EV_CREATE_THREAD:
            tr.threads.add(ev.dwThreadId)
            # copy the current watch set onto the new thread
            for slot, tag in list(tr.bps.items()):
                tr.arm(ev.dwThreadId, slot, tr.tag_addr[tag], tag)
        elif code == 5:                                  # EXIT_PROCESS
            print("进程退出")
            k32.ContinueDebugEvent(ev.dwProcessId, ev.dwThreadId, status)
            break
        k32.ContinueDebugEvent(ev.dwProcessId, ev.dwThreadId, status)

    tr.fh.close()          # records were already streamed to disk as they happened
    k32.TerminateProcess(pi.hProcess, 0)
    print("--- 卡点诊断：各线程 EIP ---")
    tr.dump_threads()
    print(f"事件 {n} 个；抓到 {len(tr.log)} 条记录，帧数 {tr.frames} -> {LOG.name}")
    print("  事件码统计:", DIAG["events"], "  (1=异常 2=载入DLL 3=建线程 5=进程退出 6=建进程)")
    print("  异常码统计:", DIAG["exceptions"], "  (0x80000003=断点)")
    print("  ctx 失败次数:", DIAG["ctx_fail"])
    print("  阶段:", tr.phase, " d3d9 base:", hex(tr.d3d9_base) if tr.d3d9_base else None)
    kinds = {}
    for e in tr.log:
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    print("  分类:", kinds)
    if tr.device:
        print(f"  device=0x{tr.device:08x}")
    return 0


def function_starts():
    """Candidate function starts in LASR.exe: MSVC prologues + the 1523 registered
    native methods. Return addresses are normalized to 'nearest preceding start'."""
    exe = Path(r"C:\Games\LASR\LASR.exe").read_bytes()
    pe = struct.unpack_from("<I", exe, 0x3C)[0]
    nsec = struct.unpack_from("<H", exe, pe + 6)[0]
    optsz = struct.unpack_from("<H", exe, pe + 20)[0]
    base = struct.unpack_from("<I", exe, pe + 24 + 28)[0]
    secs = []
    for i in range(nsec):
        o = pe + 24 + optsz + i * 40
        vsz, va, rsz, ra = struct.unpack_from("<IIII", exe, o + 8)
        secs.append((va, vsz, ra, rsz))
    starts = set()
    text = [s for s in secs if s[1] > 0x1000]
    for va, vsz, ra, rsz in text:
        blob = exe[ra:ra + min(vsz, rsz)]
        # MSVC prologue forms. 55 8b ec alone is NOT enough: release thiscall
        # methods commonly start 'push esi / mov esi,ecx' with no frame pointer,
        # which made 'nearest preceding start' land kilobytes off.
        for i in range(len(blob) - 4):
            if blob[i:i + 3] in (b"\x55\x8b\xec", b"\x55\x8b\x6c", b"\x6a\xff\x68"):
                starts.add(base + va + i)
            elif blob[i] in (0x53, 0x55, 0x56, 0x57) and blob[i + 1] == 0x8b \
                    and blob[i + 2] in (0xf1, 0xf9, 0xfb, 0xd9, 0xe1, 0xe9, 0xec):
                starts.add(base + va + i)
        # Every direct call target IS a function start - the strongest evidence there is.
        for i in range(len(blob) - 5):
            if blob[i] == 0xE8:
                rel = struct.unpack_from("<i", blob, i + 1)[0]
                tgt = base + va + i + 5 + rel
                if base + va <= tgt < base + va + min(vsz, rsz):
                    starts.add(tgt)
    names = {}
    import csv
    with open(ROOT / "out_native_methods.csv", newline="", encoding="latin1") as f:
        for r in csv.DictReader(f):
            try:
                a = int(r["fn"], 16)
                names[a] = f"{r['class']}.{r['name']}"
                starts.add(a)
            except (ValueError, KeyError):
                continue
    xs = sorted(starts)
    from bisect import bisect_right
    def sym(a):
        i = bisect_right(xs, a) - 1
        if i < 0:
            return f"0x{a:08x}"
        s = xs[i]
        nm = names.get(s, "")
        off = a - s
        if not nm and off > 0x800:      # a false start far away is not informative
            return f"0x{a:08x} (最近起点 0x{s:08x}+0x{off:x})"
        return f"{nm or '?'.ljust(1)}{' @' if nm else ' '}0x{s:08x}{'+0x%x' % off if off else ''}"
    return sym, len(xs)


def symbolize():
    sym, nstarts = function_starts()
    entries = [json.loads(l) for l in open(LOG, encoding="utf-8")]
    calls = [e for e in entries if e["kind"] in
             ("Present", "BeginScene", "Clear", "DrawIndexedPrimitive",
              "SetRenderTarget", "SetDepthStencilSurface")]
    print(f"{len(entries)} 条记录（其中渲染调用 {len(calls)}）；函数起始候选 {nstarts} 个")
    if not calls:
        print("✗ 没有抓到渲染调用 —— 游戏没在预算内跑到绘制阶段")
        return 1
    # per-frame ordered sequence
    frame = 0
    per_frame = []
    for e in calls:
        if e["kind"] == "Present":
            frame += 1
            per_frame.append([("Present", int(e["ret"], 16) if e.get("ret") else 0, [])])
            continue
        if not e.get("ret"):
            continue
        if not per_frame:
            per_frame.append([])
        per_frame[-1].append((e["kind"], int(e["ret"], 16), e.get("args") or []))
    for i, fr in enumerate(per_frame[:6], 1):
        print(f"--- 帧 {i}（{len(fr)} 次调用）---")
        for k, a, args in fr:
            extra = ""
            if k == "DrawIndexedPrimitive" and len(args) >= 4:
                extra = f"  primType={args[0]} numVert={args[3]}"
            print(f"   {k:<22} {sym(a)}{extra}")
    # aggregate: who issues the draws
    from collections import Counter
    agg = Counter()
    for k, a, _ in [x for fr in per_frame for x in fr]:
        agg[(k, a)] += 1
    print("--- 聚合：哪个函数发什么调用（前 25）---")
    for (k, a), c in agg.most_common(25):
        print(f"   {c:5d}x {k:<22} {sym(a)}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--symbolize", action="store_true")
    ap.add_argument("--nohook", action="store_true", help="挂调试器但不装断点（对照）")
    ap.add_argument("--probe", action="store_true", help="心跳时从外部探活 CPU/窗口")
    ap.add_argument("--seconds", type=int, default=25)
    a = ap.parse_args()
    if a.symbolize:
        return symbolize()
    if a.run:
        global NOHOOK
        NOHOOK = a.nohook
        return run(a.seconds, nohook=a.nohook, probe=a.probe)
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
