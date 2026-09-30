"""
Walk every file in the game and classify it by magic bytes / container type.
Outputs a table used to plan the extraction tooling.
"""
import collections
import struct
import zipfile
import sys
from pathlib import Path

GAME = Path(r"C:\Games\LASR")

MAGICS = {
    b"\x89PNG": "PNG image",
    b"DDS ": "DDS texture",
    b"FLZD": "FLZD container (custom LZ+Huffman)",
    b"RPAK": "RPAK archive (game resource pack)",
    b"FMOD": "FMOD geometry / sound",
    b"FEV1": "FMOD event project",
    b"FSB": "FMOD sound bank (FSB2/3/4/5)",
    b"BIK": "Bink video",
    b"PK\x03\x04": "ZIP archive",
    b"\xca\xfe\xba\xbe": "Java class",
    b"OggS": "Ogg Vorbis audio",
    b"RIFF": "RIFF/WAVE audio",
    b"GTMP": "GTMP",
    b"SCM": "SCM",
    b"shz": "shz",
}


def sniff(data: bytes, name: str) -> str:
    for magic, label in MAGICS.items():
        if data.startswith(magic):
            return label
    if data[:4] == b"FSB2" or data[:4] == b"FSB3" or data[:4] == b"FSB4" or data[:4] == b"FSB5":
        return "FMOD sound bank"
    if data[:8] == b"BIK" or data[8:12] == b"BIK":
        return "Bink video"
    if data[:2] in (b"\x00\x00",):
        return "?"
    return "?"


def main():
    rows = collections.Counter()
    samples = collections.defaultdict(list)
    zips = {}
    n = 0
    for p in sorted(GAME.rglob("*")):
        if not p.is_file():
            continue
        n += 1
        rel = str(p.relative_to(GAME))
        head = p.open("rb").read(16)
        if head[:4] == b"PK\x03\x04":
            try:
                z = zipfile.ZipFile(p)
                zips[rel] = len(z.namelist())
                # classify members
                mc = collections.Counter()
                for info in z.infolist():
                    d = z.read(info.filename)[:16]
                    mc[sniff(d, info.filename)] += 1
                rows[("ZIP[" + url(str(mc)) + "]").strip()] += 1
                samples["ZIP " + rel].append(str(mc))
                continue
            except Exception as e:
                rows["ZIP(broken)"] += 1
                continue
        label = sniff(head, rel)
        rows[label] += 1
        if len(samples[label]) < 6:
            samples[label].append(rel)
    print(f"total files: {n}\n")
    print(f"{'count':>6}  {'type':<45} examples")
    for label, cnt in rows.most_common():
        print(f"{cnt:>6}  {label:<45} {', '.join(samples.get(label, [])[:2])}")
    print("\n--- zip inventories (non-class content) ---")
    for k, v in sorted(samples.items()):
        if k.startswith("ZIP "):
            print(f"{k}: {v[0]}")


def url(s):
    return s


if __name__ == "__main__":
    main()
