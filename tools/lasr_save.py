"""LASR career savegame (`save/career/NNN.sav`) reader + writer.

Format recovered verbatim from the game's own Java (`java.game.Gamelogic.save`
/ `load`, `java.game.Player.save` / `load`, `java.game.RaceChronicle`) plus the
SDAT container that wraps every LASR save (options / career / controls / replays).

    "SDAT" | u32 0x00030100 | u32 fileSize | payload | 12 B trailer
    payload:
      u32  SAVEFILEID_MAIN        = 0x97654301 (-1754971391)
      u32  SAVEFILEVERSION_MAIN   = 16
      str  lastSaveTime                       ; u32 len(incl NUL) + bytes
      str  nickName
      u32  lastVehicle
      u32  carCount
        carCount x { u32 vehicleId
                     u32 partCount
                     partCount x { u32 partId, u32 status } }
      u32  prestigeValues[15]                 ; written index 14 -> 0
      u32  pubIndex
      u32  driverType
      u32  mainMenuTuningPageIndex
      u32  mainMenuCarsOpen
      u32  mainMenuTuningOpen
      u32  winSum
      u32  raceSum
      u32  retries
      u32  offeredRaces
      f32  aiLevelMul
      u32  chronicleCount
        chronicleCount x 18 values (RaceChronicle.save, bestLapTime = f32)
      u32  bastardRaceFinished
      u32  trialsCompleted
      u32  trialProgress
      u32  trials[30].completed
      u32  prestige
"""
import struct
from pathlib import Path

MAGIC = b"SDAT"
SDAT_VERSION = 0x00030100
TRAILER = 12
SAVEFILEID_MAIN = -1754971391 & 0xFFFFFFFF
SAVEFILEVERSION_MAIN = 16
PRESTIGE_VECTOR_SIZE = 15
TRIAL_COUNT = 30
CHRONICLE_FIELDS = (
    "splineLeft", "crashes", "won", "rescue", "repair", "bestLapTime",
    "pushes", "trackID", "TOD", "laps", "mycar", "mystage", "opcar",
    "opstage", "pinks", "prestige", "opstatus", "oprank",
)
CHRONICLE_FLOAT = "bestLapTime"


class SaveError(Exception):
    pass


class Reader:
    def __init__(self, data, pos=0):
        self.d = data
        self.p = pos

    def u32(self):
        v = struct.unpack_from("<I", self.d, self.p)[0]
        self.p += 4
        return v

    def i32(self):
        v = struct.unpack_from("<i", self.d, self.p)[0]
        self.p += 4
        return v

    def f32(self):
        v = struct.unpack_from("<f", self.d, self.p)[0]
        self.p += 4
        return v

    def string(self):
        n = self.u32()
        if n == 0:
            return ""
        raw = self.d[self.p:self.p + n]
        self.p += n
        return raw.split(b"\0")[0].decode("latin-1")


class Writer:
    def __init__(self):
        self.out = bytearray()

    def u32(self, v):
        self.out += struct.pack("<I", v & 0xFFFFFFFF)

    def f32(self, v):
        self.out += struct.pack("<f", v)

    def string(self, s):
        raw = s.encode("latin-1") + b"\0"
        self.u32(len(raw))
        self.out += raw


def unwrap(blob):
    if blob[:4] != MAGIC:
        raise SaveError("not a LASR SDAT file (magic %r)" % blob[:4])
    ver, size = struct.unpack_from("<II", blob, 4)
    if ver != SDAT_VERSION:
        raise SaveError("unexpected SDAT version 0x%08x" % ver)
    return ver, size, blob[12:len(blob) - TRAILER], blob[-TRAILER:]


def load(path):
    """Parse a career savegame. Returns a dict; raises SaveError if malformed."""
    blob = Path(path).read_bytes()
    ver, size, payload, trailer = unwrap(blob)
    r = Reader(payload)
    fid = r.u32()
    if fid != SAVEFILEID_MAIN:
        raise SaveError("bad SAVEFILEID 0x%08x (expected 0x%08x)"
                        % (fid, SAVEFILEID_MAIN))
    fver = r.u32()
    if fver != SAVEFILEVERSION_MAIN:
        raise SaveError("bad SAVEFILEVERSION %d" % fver)

    s = {"sdat_version": ver, "declared_size": size, "trailer": trailer.hex(" ")}
    s["lastSaveTime"] = r.string()
    s["nickName"] = r.string()
    s["lastVehicle"] = r.u32()
    cars = []
    for _ in range(r.u32()):
        vid = r.u32()
        parts = [(r.u32(), r.u32()) for _ in range(r.u32())]
        cars.append({"vehicle": vid, "parts": parts})
    s["cars"] = cars
    s["prestigeValues"] = [r.u32() for _ in range(PRESTIGE_VECTOR_SIZE)]
    s["pubIndex"] = r.u32()
    s["driverType"] = r.u32()
    s["tuningPageIndex"] = r.u32()
    s["carsOpen"] = r.u32()
    s["tuningOpen"] = r.u32()
    s["winSum"] = r.u32()
    s["raceSum"] = r.u32()
    s["retries"] = r.u32()
    s["offeredRaces"] = r.u32()
    s["aiLevelMul"] = r.f32()
    chron = []
    for _ in range(r.u32()):
        rec = {}
        for k in CHRONICLE_FIELDS:
            rec[k] = r.f32() if k == CHRONICLE_FLOAT else r.u32()
        chron.append(rec)
    s["chronicles"] = chron
    s["bastardRaceFinished"] = r.u32()
    s["trialsCompleted"] = r.u32()
    s["trialProgress"] = r.u32()
    s["trials"] = [r.u32() for _ in range(TRIAL_COUNT)]
    s["prestige"] = r.u32()
    s["consumed"] = r.p
    s["payload_size"] = len(payload)
    return s


def build(s):
    """Serialise the dict returned by load() back into a full SDAT file."""
    w = Writer()
    w.u32(SAVEFILEID_MAIN)
    w.u32(SAVEFILEVERSION_MAIN)
    w.string(s.get("lastSaveTime", ""))
    w.string(s.get("nickName", ""))
    w.u32(s.get("lastVehicle", 0))
    w.u32(len(s["cars"]))
    for c in s["cars"]:
        w.u32(c["vehicle"])
        w.u32(len(c["parts"]))
        for pid, st in c["parts"]:
            w.u32(pid)
            w.u32(st)
    for v in s["prestigeValues"]:
        w.u32(v)
    w.u32(s["pubIndex"])
    w.u32(s["driverType"])
    w.u32(s["tuningPageIndex"])
    w.u32(s["carsOpen"])
    w.u32(s["tuningOpen"])
    w.u32(s["winSum"])
    w.u32(s["raceSum"])
    w.u32(s["retries"])
    w.u32(s["offeredRaces"])
    w.f32(s["aiLevelMul"])
    w.u32(len(s["chronicles"]))
    for rec in s["chronicles"]:
        for k in CHRONICLE_FIELDS:
            (w.f32 if k == CHRONICLE_FLOAT else w.u32)(rec[k])
    w.u32(s["bastardRaceFinished"])
    w.u32(s["trialsCompleted"])
    w.u32(s["trialProgress"])
    for v in s["trials"]:
        w.u32(v)
    w.u32(s["prestige"])

    payload = bytes(w.out)
    head = MAGIC + struct.pack("<II", SDAT_VERSION, len(payload) + 12 + TRAILER)
    trailer = s.get("trailer_bytes") or b"\0" * 8 + struct.pack("<I", 8)
    return head + payload + trailer


def save(s, path):
    blob = build(s)
    backup = Path(str(path) + ".bak")
    if Path(path).exists() and not backup.exists():
        backup.write_bytes(Path(path).read_bytes())
    Path(path).write_bytes(blob)
    return path, backup


if __name__ == "__main__":
    import sys
    for p in sys.argv[1:]:
        d = load(p)
        print("== %s" % p)
        for k in ("lastSaveTime", "nickName", "lastVehicle", "pubIndex",
                  "driverType", "winSum", "raceSum", "retries",
                  "offeredRaces", "aiLevelMul", "trialsCompleted",
                  "trialProgress", "prestige", "consumed", "payload_size"):
            print("   %-16s %s" % (k, d[k]))
        print("   cars            %d" % len(d["cars"]))
        for c in d["cars"]:
            print("      vhc 0x%08x  %d parts" % (c["vehicle"], len(c["parts"])))
            for pid, st in c["parts"]:
                print("          part 0x%08x status %d" % (pid, st))
        print("   prestigeValues  %s" % d["prestigeValues"])
        print("   chronicles      %d" % len(d["chronicles"]))
