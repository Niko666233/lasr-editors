"""TUFA v4 class container: parse, inspect method bytecode, patch literals.

Container (verified against the whole corpus, docs/02, docs/08):

    TUFA | u32 version | u32 signature(0x0001451E)
    then a chain of chunks: <4cc tag> <u32 size> <size bytes>
      CONS  constant pool
      FILD  field table
      MTHD  method table  = u32 n + n x 16 bytes (flags, nameIdx, descIdx, nLocals)
      CLSS  class header
      TREE  u32 n + n x (u32 size, size bytes)   -- one record per method

Instruction shape: <u8 opcode> [<u32 payload>]  (payload width per opcode)

Editing rule: **only ever overwrite the 4 payload bytes of an existing
instruction in place**.  The file length never changes, so nothing about the
container has to be re-serialised - the only risk would be a wrong opcode
width, which is why every edit refuses to touch a record that does not walk
exactly to its own end.
"""
import struct

MAGIC = b"TUFA"

# Opcodes that carry no payload.  From tools/lasr_vm.py's hill-climb (99.8% of
# 14,796 records walk exactly with this set) cross-checked against
# docs/08_VM_OPCODES.md.
NO_PAYLOAD = frozenset((
    0x00, 0x03, 0x0C, 0x0E, 0x16, 0x1B, 0x1E, 0x23, 0x26, 0x29, 0x2A, 0x2C,
    0x2D, 0x2E, 0x2F, 0x30, 0x31, 0x32, 0x33, 0x34, 0x35, 0x36, 0x37, 0x38,
    0x3D, 0x3F, 0x40, 0x41, 0x42, 0x43, 0x46, 0x47, 0x48, 0x4A, 0x4B, 0x4C,
    0x4D, 0x4E, 0x4F, 0x50, 0x51, 0x52, 0x54,
))
MAX_OP = 0x54

OP_INT_LITERAL = 0x05
OP_FLOAT_LITERAL = 0x06
OP_RETURN = 0x16
# the only opcodes whose payload is a plain value we can safely rewrite:
# INT LITERAL (pushed as int), FLOAT LITERAL (pushed as f32)
EDITABLE_OPS = {OP_INT_LITERAL: "int", OP_FLOAT_LITERAL: "float"}


class TufaError(Exception):
    pass


def chunks(buf):
    """{tag: [(body_offset, body_bytes)]} for a TUFA buffer (validates magic)."""
    if buf[:4] != MAGIC:
        raise TufaError("not a TUFA class (%r)" % buf[:4])
    out = {}
    p = 12
    while p + 8 <= len(buf):
        tag = buf[p:p + 4]
        size, = struct.unpack_from("<I", buf, p + 4)
        if p + 8 + size > len(buf):
            raise TufaError("chunk %r overruns file" % tag)
        out.setdefault(tag.decode("latin1"), []).append((p + 8, buf[p + 8:p + 8 + size]))
        p += 8 + size
    return out


def cstr(pool, idx):
    """Read a UTF8 pool entry by index."""
    return pool.utf8(idx)


class Pool:
    """The CONS constant pool: <u32 count> + entries <u8 tag><payload>.

    tag 0 = UTF-8 string, tag 4 = 1 index (class -> name), tag 5 / 7 = 2
    indices (references / name-and-type).  These are the only tags the compiler
    ever emits; layout verified exact on all 2,224 classes (tools/resolve_pool.py).
    """
    SIZES = {4: 4, 5: 8, 7: 8}

    def __init__(self, blob):
        self.blob = blob
        self.count = struct.unpack_from("<I", blob, 0)[0] if len(blob) >= 4 else 0
        self.entries = {}
        self.offsets = {}      # idx -> utf8 字节在**本 pool blob 内**的偏移（tag 0）
        pos, i, n = 4, 0, len(blob)
        while pos < n:
            tag = blob[pos]
            if tag == 0:
                end = blob.find(b"\x00", pos + 1)
                if end < 0:
                    break
                self.entries[i] = (tag, blob[pos + 1:end].decode("latin-1"))
                self.offsets[i] = pos + 1
                pos = end + 1
            else:
                s = self.SIZES.get(tag)
                if s is None:
                    break
                self.entries[i] = (tag, tuple(
                    struct.unpack_from("<%dI" % (s // 4), blob, pos + 1)))
                pos += 1 + s
            i += 1
        self.n = i
        self.exact = (pos == n and i == self.count)

    def tag(self, idx):
        e = self.entries.get(idx)
        return e[0] if e else None

    def utf8(self, idx):
        e = self.entries.get(idx)
        return e[1] if e and e[0] == 0 else None

    def ref(self, idx):
        """(owner, name, descriptor, kind) for a reference entry."""
        e = self.entries.get(idx)
        if e is None:
            return None
        tag, val = e
        if tag == 0:
            return None
        if tag == 4:
            s = self.utf8(val[0])
            return (s, None, None, "class") if s is not None else None
        if tag == 7:
            return (None, self.utf8(val[0]), self.utf8(val[1]), "nametype")
        if tag == 5:
            a, b = val
            owner = None
            if self.tag(a) == 4:
                owner = self.utf8(self.entries[a][1][0])
            nm = de = None
            if self.tag(b) == 7:
                nm, de = (self.utf8(x) for x in self.entries[b][1])
            elif self.tag(b) == 0:
                nm = self.utf8(b)
            return (owner, nm, de, "ref")
        return None


class Method:
    __slots__ = ("index", "name", "desc", "flags", "n_locals", "rec_off",
                 "body_off", "body", "prog", "linear")

    def __iter__(self):
        return iter((self.index, self.name, self.desc, self.prog))

    def size(self):
        return len(self.body)


class Tufa:
    def __init__(self, data):
        if data[:4] != MAGIC:
            raise TufaError("not a TUFA class (%r)" % data[:4])
        self.data = bytearray(data)
        self.ck = chunks(bytes(self.data))
        self.pool = Pool(self.ck.get("CONS", [(0, b"\0")])[0][1])
        self.methods = self._methods()

    # ------------------------------------------------------------------ parse
    def _methods(self):
        tree = self.ck.get("TREE")
        if not tree:
            return []
        tree_off, body = tree[0]
        blob = bytes(self.data)
        meta = self._method_meta()
        n, = struct.unpack_from("<I", body, 0)
        out = []
        p = 4
        for i in range(n):
            if p + 4 > len(body):
                break
            sz, = struct.unpack_from("<I", body, p)
            rec_off = tree_off + p
            body_off = rec_off + 4
            rec = body[p + 4:p + 4 + sz]
            m = Method()
            m.index = i
            m.body_off = body_off
            m.rec_off = rec_off
            m.body = rec
            mm = meta.get(i)
            m.flags, m.n_locals = (mm[0], mm[3]) if mm else (0, 0)
            m.name = self.pool.utf8(mm[1]) if mm else "<clinit>"
            m.desc = self.pool.utf8(mm[2]) if mm else "()V"
            if m.name is None:
                m.name = "<unknown>"
            m.prog = walk(rec)
            m.linear = m.prog is not None
            out.append(m)
            p += 4 + sz
        return out

    def _method_meta(self):
        """MTHD -> {1-based tree record index: (flags, name_idx, desc_idx, n_locals)}.

        Layout is two groups with the second count *between* them:

            <u32 n1> + n1 x <flags, name_idx, desc_idx, tree_idx, n_locals>
            <u32 n2> + n2 x <same 20-byte record>

        group 1 = static methods, group 2 = instance methods.  TREE record 0 is
        the compiler's `<clinit>` and has no MTHD entry, hence the 1-based index.
        """
        mthd = self.ck.get("MTHD")
        if not mthd:
            return {}
        blob = mthd[0][1]
        out = {}
        pos = 0
        for _ in range(2):
            if pos + 4 > len(blob):
                break
            n, = struct.unpack_from("<I", blob, pos)
            pos += 4
            for _ in range(n):
                if pos + 20 > len(blob):
                    return out
                flags, name_i, desc_i, slot, n_locals = struct.unpack_from(
                    "<5I", blob, pos)
                out[slot] = (flags, name_i, desc_i, n_locals)
                pos += 20
        return out

    # ------------------------------------------------------------- inspection
    def find(self, name, desc=None):
        """All methods called `name` (optionally with an exact descriptor)."""
        hits = [m for m in self.methods if m.name == name]
        if desc:
            exact = [m for m in hits if m.desc == desc]
            if exact:
                return exact
        return hits

    def literals(self, method):
        """[(list_index, file_offset, kind, value)] for an editable method.

        The value is re-read from `self.data` every call, so the list reflects
        in-place edits made by set_literal()/scale_literals().
        """
        if method.prog is None:
            return []
        out = []
        for o, op, w, pay in method.prog:
            if op not in EDITABLE_OPS:
                continue
            off = method.body_off + o + 1
            raw, = struct.unpack_from("<I", self.data, off)
            if op == OP_FLOAT_LITERAL:
                val = struct.unpack("<f", struct.pack("<I", raw))[0]
            else:
                val = raw if raw < 0x80000000 else raw - 0x100000000
            out.append((len(out), off, EDITABLE_OPS[op], val))
        return out

    # ----------------------------------------------------------------- editing
    def set_literal(self, file_offset, kind, value):
        if kind == "float":
            raw = struct.pack("<f", float(value))
        else:
            raw = struct.pack("<I", int(value) & 0xFFFFFFFF)
        self.data[file_offset:file_offset + 4] = raw

    def set_literals(self, method, edits):
        """edits = {list_index: new_value}.  Returns the number applied."""
        lits = self.literals(method)
        n = 0
        for idx, off, kind, _old in lits:
            if idx in edits:
                self.set_literal(off, kind, edits[idx])
                n += 1
        return n

    def scale_literals(self, method, factor, kinds=("float", "int"),
                       only_nonzero=False):
        """Multiply every literal of `method` by `factor` (ints are rounded)."""
        lits = self.literals(method)
        n = 0
        for idx, off, kind, old in lits:
            if kind not in kinds:
                continue
            if only_nonzero and old == 0:
                continue
            if kind == "float":
                self.set_literal(off, kind, float(old) * factor)
            else:
                self.set_literal(off, kind, int(round(old * factor)))
            n += 1
        return n

    def tobytes(self):
        return bytes(self.data)


def walk(body):
    """[(offset, opcode, width, payload)] or None when the record does not
    decode exactly to its own end (then we refuse to edit it)."""
    pos, out, n = 0, [], len(body)
    while pos < n:
        op = body[pos]
        if op > MAX_OP:
            return None
        if op in NO_PAYLOAD:
            out.append((pos, op, 1, None))
            pos += 1
            continue
        if pos + 5 > n:
            return None
        pay, = struct.unpack_from("<I", body, pos + 1)
        out.append((pos, op, 5, pay))
        pos += 5
    return out if pos == n else None
