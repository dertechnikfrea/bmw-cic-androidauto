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
                                                  (/dev/fs0, or the partition /dev/fs0p2)
  hmi_profile.py HmiMain [--name "E60 ..."]       print a profile for iba_profiles.h
               [--pin 0xOLD=0xNEW ...]            give an address found by hand

Method:
  * every code fingerprint (kIbaAnchors, kIbaMarshalSigs: 32 bytes each) is searched
    in the new HmiMain; bytes inside the fingerprint that are absolute addresses
    (literal pool words) are masked, because they move with the code;
  * fingerprints found more than once are resolved with the shift of their
    neighbours (code moves by a constant amount inside a region); if that fails,
    the hit is taken when exactly one lies between the new addresses of its
    neighbours (functions keep their order), with a warning to check it;
  * data addresses (vtables, one static) are moved by the data shift measured on
    the masked literal words, and every vtable is checked through its C++ typeinfo
    name. The type each vtable must have is read from the "vtable <type>" notes of
    the profiles already in iba_profiles.h. If the shifted address is not that
    type (another CIC software version: the data does not move by one shift), the
    vtable is taken from its dynamic symbol (_ZTV<type> + 8) instead. A data
    address without a type cannot be checked then and has to be pinned;
  * --pin gives the new address of one the tool cannot find: a function whose code
    changed (its fingerprint is not in this HmiMain), an ambiguous fingerprint or a
    static. Pinned addresses are marked in the output; a pinned function gets the
    bytes of this build in the SigFix table.
  * the skip-key hooks (KeyHook in AAPlugin.cpp) are taken from their vtable symbol
    (slot 8 = handler) in the dynamic symbols; the getter moves with the handler and
    must match kKeyGetterSig. If that fails only a warning is printed: the plugin
    keeps those hooks off on that build.
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

    def dynsym(self):
        """{name: value} of the dynamic symbol table (found through PT_DYNAMIC)."""
        phoff, = struct.unpack_from("<I", self.d, 28)
        phentsize, phnum = struct.unpack_from("<HH", self.d, 42)
        dyn = None
        for i in range(phnum):
            p_type, off, _, _, filesz = struct.unpack_from("<5I", self.d, phoff + i * phentsize)
            if p_type == 2:
                dyn = (off, filesz)
        if dyn is None:
            return {}
        tags = {}
        for j in range(dyn[1] // 8):
            tag, val = struct.unpack_from("<iI", self.d, dyn[0] + j * 8)
            if tag == 0:
                break
            tags.setdefault(tag, val)
        if not all(t in tags for t in (4, 5, 6)):        # DT_HASH, DT_STRTAB, DT_SYMTAB
            return {}
        nchain = self.word(tags[4] + 4)
        out = {}
        for i in range(nchain):
            o = self.off(tags[6] + i * 16)
            st_name, st_value = struct.unpack_from("<II", self.d, o)
            n = self.cstr(tags[5] + st_name, 256)
            if n:
                out[n] = st_value
        return out


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


def key_hooks():
    """KeyHook entries of AAPlugin.cpp: (vtable symbol, handler, getter) + getter signature."""
    src = (PLUGIN / "AAPlugin.cpp").read_text()
    hooks = [(m.group(1), int(m.group(2), 16), int(m.group(3), 16)) for m in
             re.finditer(r'\{"(_ZTV\w+)",\s*0x([0-9a-fA-F]+)UL,\s*0x([0-9a-fA-F]+)UL', src)]
    m = re.search(r"kKeyGetterSig\[\d*\]\s*=\s*\{([^}]*)\}", src)
    sig = [int(x, 16) for x in re.findall(r"0x([0-9a-fA-F]+)", m.group(1))] if m else []
    return hooks, sig


KEY_SLOT = 8    # vtable[8] = message handler (see KeyHook in AAPlugin.cpp)


def known_vtable_types():
    """{address in the base build: C++ type name}, from the "vtable <type>" notes of the
    profiles already in iba_profiles.h (written by this tool from other builds)."""
    out, clash = {}, set()
    for m in re.finditer(r"\{0x([0-9a-fA-F]+)UL,\s*0x[0-9a-fA-F]+UL\},\s*/\* vtable (\w+) ",
                         (PLUGIN / "iba_profiles.h").read_text()):
        a = int(m.group(1), 16)
        if out.setdefault(a, m.group(2)) != m.group(2):
            clash.add(a)
    return {a: t for a, t in out.items() if a not in clash}


def resolve_key_hooks(img, hooks, sig, syms):
    """Handler = vtable symbol slot 8 in the new build; getter moves with it and must
    match the getter signature. Returns ({old: new}, notes, errors)."""
    xlat, notes, errors = {}, {}, []
    for name, handler, getter in hooks:
        vt = syms.get(name)
        if vt is None:
            errors.append("vtable %s not in the dynamic symbols" % name); continue
        new_h = img.word(vt + 4 * KEY_SLOT)
        if new_h is None or not img.in_text(new_h):
            errors.append("vtable %s slot %d is not code" % (name, KEY_SLOT)); continue
        new_g = getter + (new_h - handler)
        if [img.word(new_g + 4 * k) for k in range(len(sig))] != sig:
            errors.append("getter of %s at %#x does not match kKeyGetterSig" % (name, new_g)); continue
        short = name[4:-1] if name.endswith("E") else name
        xlat[handler], notes[handler] = new_h, "key handler, %s slot %d" % (short, KEY_SLOT)
        xlat[getter], notes[getter] = new_g, "key getter, moves with the handler (signature checked)"
    return xlat, notes, errors


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


def by_shift(img, anchors, i, a, h):
    """Hits whose shift lies between the shifts of the two neighbours."""
    lo = anchors[i - 1][1] if i > 0 else anchors[0][1]
    hi = anchors[i][1] if i < len(anchors) else anchors[-1][1]
    c = [x for x in h if min(lo, hi) <= x - a <= max(lo, hi)]
    if len(c) > 1:      # several inside the range: take the one with a neighbour's exact shift
        c = [x for x in c if x - a in (lo, hi)]
    return c


def by_order(img, anchors, i, a, h):
    """Hits between the new addresses of the two neighbours (functions keep their order)."""
    lo = sum(anchors[i - 1]) if i > 0 else img.text[0] - 1
    hi = sum(anchors[i]) if i < len(anchors) else img.text[0] + img.text[2]
    return [x for x in h if lo < x < hi]


def resolve(img, sigs, pins):
    """Returns ({old: new}, masks, unresolved, missing, hits, ordered); pins are given
    addresses of fingerprints, ordered the fingerprints resolved by by_order()."""
    hits, masks = {}, {}
    for a, b in sigs.items():
        m = literal_mask(a, b)
        masks[a] = m
        hits[a] = find_all(img, b, m)
    missing = [a for a, h in hits.items() if not h and a not in pins]
    anchors = sorted([(a, h[0] - a) for a, h in hits.items() if len(h) == 1 and a not in pins]
                     + [(a, n - a) for a, n in pins.items()])
    if not anchors:
        raise SystemExit("no fingerprint found exactly once: this is not a compatible HmiMain")
    ordered = set()
    changed = True
    while changed:
        changed = False
        xs = [x for x, _ in anchors]
        for rule in (by_shift, by_order):   # by_order only when by_shift resolves nothing more
            for a, h in hits.items():
                if a in xs or not h:
                    continue
                c = rule(img, anchors, bisect.bisect(xs, a), a, h)
                if len(c) == 1:
                    anchors.append((a, c[0] - a))
                    anchors.sort()
                    if rule is by_order:
                        ordered.add(a)
                    changed = True
                    break
            if changed:
                break
    resolved = dict(anchors)
    unresolved = {a: h for a, h in hits.items() if h and a not in resolved}
    return {a: a + d for a, d in resolved.items()}, masks, unresolved, missing, hits, ordered


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
def find_in_image(d, base, want):
    """(offset, size) of a file in the image filesystem at base, or None."""
    try:
        dir_off, = struct.unpack_from("<I", d, base + 16)
        p = base + dir_off
        while True:
            size, _, _, mode = struct.unpack_from("<HHII", d, p)
            if size < 24:       # 0 = end of the directory; less than an entry header = not a directory
                return None
            if mode & 0o170000 == 0o100000:
                off, fsz = struct.unpack_from("<II", d, p + 24)
                if d[p + 32:p + size].split(b"\0")[0] == want and base + off + fsz <= len(d):
                    return base + off, fsz
            p += size
    except struct.error:        # not an image directory
        return None


def extract(fs0, out):
    d = Path(fs0).read_bytes()
    # /dev/fs0 has the second boot image at 0x740000; in a dump of a partition (/dev/fs0p2)
    # it is somewhere else, so every "imagefs" header is tried after that one.
    bases = [0x00740000] + [m.start() for m in re.finditer(b"imagefs", d)]
    for base in bases:
        if d[base:base + 7] != b"imagefs":
            continue
        hit = find_in_image(d, base, b"usr/Hmi/bin/HmiMain")
        if hit and d[hit[0]:hit[0] + 4] == b"\x7fELF":
            Path(out).write_bytes(d[hit[0]:hit[0] + hit[1]])
            print("extracted %s (%d bytes, image at 0x%x)" % (out, hit[1], base))
            return
    raise SystemExit("usr/Hmi/bin/HmiMain not found in an image filesystem of this dump")


def parse_pins(argv):
    pins = {}
    for i, x in enumerate(argv):
        if x == "--pin":
            try:
                old, new = (int(v, 16) for v in argv[i + 1].split("="))
            except (IndexError, ValueError):
                raise SystemExit("--pin needs 0xOLD=0xNEW (address in the source = address in this HmiMain)")
            pins[old] = new
    return pins


def main(argv):
    if len(argv) == 4 and argv[1] == "--extract":
        return extract(argv[2], argv[3])
    if len(argv) < 2:
        raise SystemExit(__doc__)
    name = argv[argv.index("--name") + 1] if "--name" in argv else Path(argv[1]).name
    img = Image(Path(argv[1]).read_bytes())
    sigs, used = plugin_inputs()
    hooks, getter_sig = key_hooks()
    hook_addrs = {a for _, h, g in hooks for a in (h, g)}
    pins = parse_pins(argv)
    for a, n in pins.items():
        if a in hook_addrs:
            raise SystemExit("--pin %#x: the skip-key hooks are taken from their vtable symbols" % a)
        if a not in used and a not in sigs:
            raise SystemExit("--pin %#x: not an address the plugin uses" % a)
        if img.off(n) is None or (a in sigs and (not img.in_text(n) or n % 2)):
            raise SystemExit("--pin %#x=%#x: not a possible address in this HmiMain" % (a, n))
    m = re.search(rb"CIC_L6_[ -~]{10,90}", img.d)
    build = m.group().decode() if m else "unknown build"
    tmap, masks, unresolved, missing, hits, ordered = resolve(img, sigs, {a: n for a, n in pins.items() if a in sigs})
    ok = not unresolved and not missing
    for a in missing:
        print("ERROR fingerprint %#x not found (code changed in this build? find the function by hand, then --pin)"
              % a, file=sys.stderr)
    for a, h in unresolved.items():
        print("ERROR fingerprint %#x ambiguous: %s (--pin the right one)" % (a, [hex(x) for x in h[:8]]), file=sys.stderr)
    for a in sorted(ordered):
        print("WARNING fingerprint %#x found %d times: %#x taken by its position between its neighbours, check it"
              % (a, len(hits[a]), tmap[a]), file=sys.stderr)

    def new_bytes(a):
        return img.d[img.off(tmap[a]):img.off(tmap[a]) + 32]

    def same_code(a):   # fingerprint matches at the new address (literal pool words aside)
        return all(not masks[a][j] or new_bytes(a)[j] == sigs[a][j] for j in range(32))

    notes = {a: "fingerprint found %d times, taken by its position between its neighbours" % len(hits[a]) for a in ordered}
    for a in pins:
        if a in sigs:
            notes[a] = "pinned by hand: " + ("fingerprint found %d times" % len(hits[a]) if same_code(a)
                                             else "code differs from the fingerprint")
    # a pinned function with other code has no literal words where the fingerprint had them
    dshift = data_shift(img, sigs, masks, {a: n for a, n in tmap.items() if same_code(a)})
    xlat = dict(tmap)
    syms = img.dynsym()
    kx, knotes, kerr = resolve_key_hooks(img, hooks, getter_sig, syms)
    for e in kerr:    # optional feature: the plugin's own checks keep the hook off
        print("WARNING %s: skip keys stay off on this build" % e, file=sys.stderr)
    xlat.update(kx)
    notes.update(knotes)
    types = known_vtable_types()
    by_symbol, untyped = [], []
    for a in sorted(used - set(sigs) - hook_addrs):
        if a in pins:
            cls = vtable_class(img, pins[a])
            xlat[a] = pins[a]
            notes[a] = "pinned by hand" + (": vtable " + cls if cls else "")
        elif a >= img.data_seg[0] - 0x00100000 and a >= 0x09000000:
            n = a + dshift if dshift is not None else None
            cls = vtable_class(img, n) if n is not None else None
            want = types.get(a)
            if want and cls != want:    # not where the common shift puts it: take the vtable by its symbol
                s = syms.get("_ZTV" + want)
                if s is None or vtable_class(img, s + 8) != want:
                    print("ERROR vtable %s (%#x) not found in this HmiMain" % (want, a), file=sys.stderr); ok = False; continue
                n, cls = s + 8, want
                by_symbol.append(a)
            elif n is None:
                print("ERROR no data shift for %#x" % a, file=sys.stderr); ok = False; continue
            xlat[a] = n
            if cls:
                notes[a] = "vtable " + cls + (" (by symbol)" if a in by_symbol else "")
            else:
                notes[a] = "data (static, not verifiable by type)"
                untyped.append(a)
        else:
            d = text_shift_near(tmap, a)
            if d is None:
                print("ERROR no unambiguous code shift for %#x" % a, file=sys.stderr); ok = False; continue
            xlat[a] = a + d
            notes[a] = "code, shift of neighbours (no fingerprint)"
    if by_symbol:   # the data did not move by one shift, so an address without a type cannot be trusted
        for a in untyped:
            print("ERROR %#x has no type to check and the data of this build does not move by one shift "
                  "(%d vtables taken by symbol): find it by hand, then --pin" % (a, len(by_symbol)), file=sys.stderr)
            ok = False
    # fingerprints whose literal words moved (or pinned functions with other code): the bytes of the new build
    fixes = {a: new_bytes(a) for a in tmap if new_bytes(a) != sigs[a]}

    print("/* %s: %s */" % (name, build))
    print("/* generated by tools/hmi_profile.py: %d fingerprints, data shift %s%s */"
          % (len(tmap), hex(dshift) if dshift is not None else "?",
             ", %d vtables by symbol" % len(by_symbol) if by_symbol else ""))
    if pins:
        print("/* pinned by hand (--pin): %s */" % ", ".join("0x%08x" % a for a in sorted(pins)))
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
