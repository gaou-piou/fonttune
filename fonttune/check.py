"""Check built fonts for the problems fonttune has measured on this desktop.

Every check is tied to a measurement (README, `fonttune xheight`/`darken`):
  overlap   glyphs flagged OVERLAP_SIMPLE/COMPOUND: FreeType renders them with
            4x4 oversampling (Adwaita Sans, same outlines, flag only: 30-42% of
            the pixels change at 13-20 px, +0.5% ink)
  vf-hints  a variable font with hinting functions (fpgm): the hints fit the default instance
            and distort the others under hintmedium/full (Inter wght 100: +64% ink)
  gasp      a ttfautohint font whose gasp lacks symmetric smoothing in some
            range: under hintmedium/full FreeType 2.15 runs its bytecode
            differently (Noto Sans: 0x3 everywhere moves pixels up to 20 px,
            0x3 from 21 ppem only or 0x7 at every size tested up to 48 px;
            not when the 2nd and 3rd stem-mode letters match, e.g. nnn/sss,
            which the font does not record; other hinters were not measured)
  names     the typographic family (nameID 16, else 1) is empty

--fontbakery also runs `fontbakery check-universal` when it is installed
(pip install fontbakery). Font collections (.ttc) are checked font by font.
Exit status: 0 clean, 1 warnings, 2 usage errors or unreadable files.
"""
import argparse
import os
import shutil
import subprocess
import sys

from fontTools.ttLib import TTCollection, TTFont

OVERLAP_SIMPLE = 0x40       # glyf flag on the first point
OVERLAP_COMPOUND = 0x0400   # component flag
SYMMETRIC_SMOOTHING = 0x0008


def overlap_glyphs(font):
    """Glyphs FreeType oversamples: flagged ones, and composites of flagged parts
    (the flag travels with the component's points into the composite)."""
    if "glyf" not in font:
        return []
    glyf = font["glyf"]
    order = font.getGlyphOrder()
    flagged = set()
    for name in order:
        g = glyf[name]
        if g.isComposite():
            if any(c.flags & OVERLAP_COMPOUND for c in g.components):
                flagged.add(name)
        elif g.numberOfContours > 0 and g.flags[0] & OVERLAP_SIMPLE:
            flagged.add(name)
    grew = True
    while grew:
        grew = False
        for name in order:
            g = glyf[name]
            if name not in flagged and g.isComposite() and \
                    any(c.glyphName in flagged for c in g.components):
                flagged.add(name)
                grew = True
    return [n for n in order if n in flagged]


def gasp_small_ranges(gasp):
    """-> ["0-8 ppem", "17+ ppem", ...]: ranges whose behaviour lacks symmetric smoothing."""
    out, low = [], 0
    for ppem, v in sorted(gasp.gaspRange.items()):
        if not v & SYMMETRIC_SMOOTHING:
            out.append(f"{low}+ ppem" if ppem == 0xFFFF else f"{low}-{ppem} ppem")
        low = ppem + 1
    return out


def family(name):
    for i in (16, 1):
        v = name.getDebugName(i)
        if v and v.strip():
            return v
    return None


def check(path, number=0):
    """-> list of (check, message) warnings for one font (number: index in a .ttc)."""
    with TTFont(path, fontNumber=number) as f:
        return check_font(f)


def check_font(f):
    warn = []
    flagged = overlap_glyphs(f)
    if flagged:
        fix = ("merge the overlaps in the source" if "fvar" in f else
               "cut statics with overlaps removed (fontTools instancer OverlapMode.REMOVE, "
               "fonttune statics)")
        warn.append(("overlap", f"{len(flagged)} glyphs flagged as overlapping ({', '.join(flagged[:3])}"
                                f"{', ...' if len(flagged) > 3 else ''}): FreeType oversamples them; {fix}"))
    if "fvar" in f and "fpgm" in f:
        warn.append(("vf-hints", "variable font with bytecode: the other instances distort under "
                                 "hintmedium/full; fonttune does not hint VFs (strip: ttfautohint --dehint)"))
    version = (f["name"].getDebugName(5) or "") if "name" in f else ""
    if "fpgm" in f and "gasp" in f and "ttfautohint" in version:
        bad = gasp_small_ranges(f["gasp"])
        if bad:
            warn.append(("gasp", f"gasp leaves symmetric smoothing off ({', '.join(bad)}): under "
                                 "hintmedium/full FreeType 2.15 runs ttfautohint's bytecode "
                                 "differently unless its stem mode is nnn/sss-like "
                                 "(fonttune gasp=smooth)"))
    if "name" not in f or not family(f["name"]):
        warn.append(("names", "no family name (nameID 16 or 1)"))
    return warn


def faces(path):
    """-> [(label, number)] for a font file or a collection."""
    with open(path, "rb") as fh:
        if fh.read(4) != b"ttcf":
            return [(os.path.basename(path), 0)]
    with TTCollection(path, lazy=True) as c:
        return [(f"{os.path.basename(path)}#{i}", i) for i in range(len(c.fonts))]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="fonttune check", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("fonts", nargs="+")
    ap.add_argument("--fontbakery", action="store_true", help="also run fontbakery check-universal")
    a = ap.parse_args(argv)
    missing = [p for p in a.fonts if not os.path.isfile(p)]
    if missing:
        ap.error(f"not a font file: {', '.join(missing)}")
    fb = shutil.which("fontbakery") if a.fontbakery else None
    if a.fontbakery and not fb:
        ap.error("--fontbakery: fontbakery is not installed (pip install fontbakery)")
    status = 0
    for p in a.fonts:
        try:
            items = faces(p)
        except Exception as e:  # noqa: BLE001 - fontTools raises many types on broken fonts
            items, status = [], 2
            print(f"{os.path.basename(p)}: cannot read ({type(e).__name__}: {e})")
        for label, n in items:
            try:
                warn = check(p, n)
            except Exception as e:  # noqa: BLE001
                print(f"{label}: cannot read ({type(e).__name__}: {e})")
                status = 2
                continue
            print(f"{label}: {'ok' if not warn else f'{len(warn)} warning(s)'}")
            for c, msg in warn:
                print(f"  [{c}] {msg}")
            status = max(status, int(bool(warn)))
    if fb:
        sys.stdout.flush()
        r = subprocess.run([fb, "check-universal", *a.fonts], stdin=subprocess.DEVNULL)
        if r.returncode:
            status = max(status, 1)
    return status


if __name__ == "__main__":
    sys.exit(main())
