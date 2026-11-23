#!/usr/bin/env python3
"""Generate an HmiMain address profile for AAPlugin from another CIC software build.

AAPlugin calls private HmiMain code at fixed addresses. They are written in the
source for the E9x build it was developed on (HmiMain 9283417A, SHA256 dbeef804...).
Other builds of the same CIC software (for example the E60 LCI build
"CIC_L6_1107_Release B1107-501-1121A Build 11") contain the same code, shifted
by a few KB. This tool finds every address the plugin uses in another HmiMain
and prints a profile table for src/plugin/iba_profiles.h.

How to get HmiMain from a car: HmiMain is not a file on the running CIC, it lives in
the second boot image (memifs2 -o 0x00740000 in /etc/starter.cfg). Copy the raw
flash over telnet (read only):   cp /dev/fs0 /fs/usb0/fs0.img
then extract it with:            hmi_profile.py --extract fs0.img HmiMain

Usage:
  hmi_profile.py --extract fs0.img HmiMain        extract HmiMain from a flash dump
  hmi_profile.py HmiMain [--name "E60 ..."]       print a profile for iba_profiles.h

Method:
  * every code fingerprint (kIbaAnchors, kIbaMarshalSigs: 32 bytes each) is searched
    in the new HmiMain; bytes inside the fingerprint that are absolute addresses
    (literal pool words) are masked, because they move with the code;
  * fingerprints found more than once are resolved with the shift of their
    neighbours (code moves by a constant amount inside a region);
  * data addresses (vtables, one static) are moved by the data shift measured on
    the masked literal words, and every vtable is checked through its C++ typeinfo
    name.
Anything that cannot be resolved unambiguously is reported and the profile is
not printed.
"""
import bisect
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "src" / "plugin"


# ---------------------------------------------------------------- ELF helpers
class Image:
    def __init__(self, data):
        if data[:4] != b"\x7fELF" or data[4] != 1 or data[5] != 1:
            raise SystemExit("not a 32-bit little-endian ELF")
        self.d = data
        phoff, = struct.unpack_from("<I", data, 28)
        phentsize, phnum = struct.unpack_from("<HH", data, 42)
        self.loads = []
        for i in range(phnum):
            p_type, off, vaddr, _, filesz, _, flags, _ = struct.unpack_from("<8I", data, phoff + i * phentsize)
            if p_type == 1:
                self.loads.append((vaddr, off, filesz, flags))
        self.text = next(l for l in self.loads if l[3] & 1)
        self.data_seg = next(l for l in self.loads if not l[3] & 1)

    def off(self, va):
        for vaddr, off, size, _ in self.loads:
            if vaddr <= va < vaddr + size:
                return va - vaddr + off
        return None

    def va(self, off):
        for vaddr, o, size, _ in self.loads:
            if o <= off < o + size:
                return off - o + vaddr
        return None

    def word(self, va):
        o = self.off(va)
        return None if o is None else struct.unpack_from("<I", self.d, o)[0]

    def cstr(self, va, maxlen=128):
        o = self.off(va)
        if o is None:
            return None
        end = self.d.find(b"\0", o, o + maxlen)
        if end < 0:
            return None
        s = self.d[o:end]
        return s.decode() if s and all(32 <= c < 127 for c in s) else None

    def in_text(self, va):
        return self.text[0] <= va < self.text[0] + self.text[2]


def is_addr(w):
    return 0x08000000 <= w < 0x0A000000


# ---------------------------------------------------------- plugin inputs
def plugin_inputs():
    hdr = (PLUGIN / "iba_firmware.h").read_text() + (PLUGIN / "iba_marshal.h").read_text()
    sigs = {}
    for m in re.finditer(r"\{0x([0-9a-fA-F]+)UL,\{([^}]*)\}\}", hdr):
        sigs[int(m.group(1), 16)] = bytes(int(x, 16) for x in m.group(2).split(","))
    src = (PLUGIN / "AAPlugin.cpp").read_text()
    used = set(int(x, 16) for x in re.findall(r"0x0?([89][0-9a-fA-F]{6})UL", src))
    used |= set(int(x, 16) for x in re.findall(r"=0x([0-9a-fA-F]+)UL;", hdr))
    used -= {0x08000000, 0x09000000, 0x0A000000}
    return sigs, used


# ---------------------------------------------------------------- search
def find_all(img, pattern, mask):
    """Offsets in the text segment where pattern matches (mask[i] False = ignore byte)."""
    t0, tsz = img.text[1], img.text[2]
    hay = img.d[t0:t0 + tsz]
    fixed = max(range(0, 32 - 7), key=lambda k: sum(mask[k:k + 8]))   # longest unmasked run of 8
    key = bytes(pattern[fixed:fixed + 8])
    hits, start = [], 0
    while True:
        i = hay.find(key, start)
        if i < 0:
            break
        s = i - fixed
        if s >= 0 and s % 2 == 0 and all(not mask[j] or hay[s + j] == pattern[j] for j in range(32)):
            hits.append(img.va(t0 + s))
        start = i + 1
    return hits


def literal_mask(addr, sig):
    mask = [True] * 32
    for k in range(32):
        if (addr + k) % 4 == 0 and k + 4 <= 32 and is_addr(struct.unpack_from("<I", sig, k)[0]):
            mask[k:k + 4] = [False] * 4
    return mask


def resolve(img, sigs):
    hits, masks = {}, {}
    for a, b in sigs.items():
        m = literal_mask(a, b)
        masks[a] = m
        hits[a] = find_all(img, b, m)
    missing = [a for a, h in hits.items() if not h]
    anchors = sorted((a, h[0] - a) for a, h in hits.items() if len(h) == 1)
    if not anchors:
        raise SystemExit("no fingerprint found exactly once: this is not a compatible HmiMain")
    changed = True
    while changed:
        changed = False
        xs = [x for x, _ in anchors]
        for a, h in hits.items():
            if a in xs or not h:
                continue
            i = bisect.bisect(xs, a)
            lo = anchors[i - 1][1] if i > 0 else anchors[0][1]
            hi = anchors[i][1] if i < len(anchors) else anchors[-1][1]
            c = [x for x in h if min(lo, hi) <= x - a <= max(lo, hi)]
            if len(c) > 1:      # several inside the range: take the one with a neighbour's exact shift
                c = [x for x in c if x - a in (lo, hi)]
            if len(c) == 1:
                anchors.append((a, c[0] - a))
                anchors.sort()
                changed = True
                break
    resolved = dict(anchors)
    unresolved = {a: h for a, h in hits.items() if h and a not in resolved}
    return {a: a + d for a, d in resolved.items()}, masks, unresolved, missing


def data_shift(img, sigs, masks, tmap):
    deltas = {}
    for a, new in tmap.items():
        for k in range(0, 32, 4):
            if not masks[a][k]:
                old_w = struct.unpack_from("<I", sigs[a], k)[0]
                new_w = img.word(new + k)
                if new_w is not None and old_w >= img.data_seg[0]:
                    deltas[new_w - old_w] = deltas.get(new_w - old_w, 0) + 1
    return max(deltas, key=deltas.get) if deltas else None


def vtable_class(img, vp):
    try:
        if img.word(vp - 8) != 0:
            return None
        return img.cstr(img.word(img.word(vp - 4) + 4))
    except TypeError:
        return None


def text_shift_near(tmap, a):
    xs = sorted(tmap)
    i = bisect.bisect(xs, a)
    ds = {tmap[x] - x for x in xs[max(0, i - 1):i + 1]}
    return ds.pop() if len(ds) == 1 else None


# ---------------------------------------------------------------- main
def extract(fs0, out):
    d = Path(fs0).read_bytes()
    base = 0x00740000
    if d[base:base + 7] != b"imagefs":
        raise SystemExit("no imagefs at 0x740000 in this dump")
    dir_off, = struct.unpack_from("<I", d, base + 16)
    p = base + dir_off
    while True:
        size, _, _, mode = struct.unpack_from("<HHII", d, p)
        if size == 0:
            break
        if mode & 0o170000 == 0o100000:
            off, fsz = struct.unpack_from("<II", d, p + 24)
            name = d[p + 32:p + size].split(b"\0")[0].decode()
            if name == "usr/Hmi/bin/HmiMain":
                Path(out).write_bytes(d[base + off:base + off + fsz])
                print("extracted %s (%d bytes)" % (out, fsz))
                return
        p += size
    raise SystemExit("usr/Hmi/bin/HmiMain not found in the image")


def main(argv):
    if len(argv) == 4 and argv[1] == "--extract":
        return extract(argv[2], argv[3])
    if len(argv) < 2:
        raise SystemExit(__doc__)
    name = argv[argv.index("--name") + 1] if "--name" in argv else Path(argv[1]).name
    img = Image(Path(argv[1]).read_bytes())
    sigs, used = plugin_inputs()
    m = re.search(rb"CIC_L6_[ -~]{10,90}", img.d)
    build = m.group().decode() if m else "unknown build"
    tmap, masks, unresolved, missing = resolve(img, sigs)
    ok = not unresolved and not missing
    for a in missing:
        print("ERROR fingerprint %#x not found" % a, file=sys.stderr)
    for a, h in unresolved.items():
        print("ERROR fingerprint %#x ambiguous: %s" % (a, [hex(x) for x in h[:8]]), file=sys.stderr)

    dshift = data_shift(img, sigs, masks, tmap)
    xlat = dict(tmap)
    notes = {}
    for a in sorted(used - set(tmap)):
        if a >= img.data_seg[0] - 0x00100000 and a >= 0x09000000:
            if dshift is None:
                print("ERROR no data shift for %#x" % a, file=sys.stderr); ok = False; continue
            n = a + dshift
            cls = vtable_class(img, n)
            xlat[a] = n
            notes[a] = ("vtable " + cls) if cls else "data (static, not verifiable by type)"
        else:
            d = text_shift_near(tmap, a)
            if d is None:
                print("ERROR no unambiguous code shift for %#x" % a, file=sys.stderr); ok = False; continue
            xlat[a] = a + d
            notes[a] = "code, shift of neighbours (no fingerprint)"
    # fingerprints whose literal words moved: give the bytes of the new build
    fixes = {a: img.d[img.off(n):img.off(n) + 32] for a, n in tmap.items()
             if img.d[img.off(n):img.off(n) + 32] != sigs[a]}

    print("/* %s: %s */" % (name, build))
    print("/* generated by tools/hmi_profile.py: %d fingerprints, data shift %s */"
          % (len(tmap), hex(dshift) if dshift is not None else "?"))
    print("static const IbaXlat kXlat_X[] = {")
    for a in sorted(xlat):
        c = (" /* %s */" % notes[a]) if a in notes else ""
        print("    {0x%08xUL, 0x%08xUL},%s" % (a, xlat[a], c))
    print("};")
    print("static const IbaSigFix kSigFix_X[] = {")
    for a in sorted(fixes):
        print("    {0x%08xUL, {%s}}," % (a, ",".join("0x%02x" % x for x in fixes[a])))
    print("};")
    if not ok:
        raise SystemExit("profile incomplete: do not use")


if __name__ == "__main__":
    main(sys.argv)
