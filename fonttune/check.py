"""Check built fonts for the problems fonttune has measured on this desktop.

Every check is tied to a measurement (README, `fonttune xheight`/`darken`):
  overlap   glyphs flagged OVERLAP_SIMPLE/COMPOUND: FreeType renders them with
            4x4 oversampling (Adwaita Sans, same outlines, flag only: 30-42% of
            the pixels change at 13-20 px, +0.5% ink)
  vf-hints  a variable font with bytecode: the hints fit the default instance
            and distort the others under hintmedium/full (Inter wght 100: +64% ink)
  gasp      a hinted font whose gasp lacks symmetric smoothing: FreeType 2.15
            runs ttfautohint's bytecode differently up to ~20 px (not with
            natural stems, which the font does not record)
  names     the typographic family (nameID 16, else 1) is empty

--fontbakery also runs `fontbakery check-universal` when it is installed
(pip install fontbakery). Exit status: 0 clean, 1 warnings, 2 usage errors.
"""
import argparse
import os
import shutil
import subprocess
import sys

from fontTools.ttLib import TTFont

OVERLAP_SIMPLE = 0x40       # glyf flag on the first point
OVERLAP_COMPOUND = 0x0400   # component flag
SYMMETRIC_SMOOTHING = 0x0008


def overlap_glyphs(font):
    if "glyf" not in font:
        return []
    out = []
    glyf = font["glyf"]
    for name in font.getGlyphOrder():
        g = glyf[name]
        if g.isComposite():
            if any(c.flags & OVERLAP_COMPOUND for c in g.components):
                out.append(name)
        elif g.numberOfContours > 0 and g.flags[0] & OVERLAP_SIMPLE:
            out.append(name)
    return out


def check(path):
    """-> list of (check, message) warnings for one font file."""
    warn = []
    with TTFont(path) as f:
        hinted = "fpgm" in f or "prep" in f
        flagged = overlap_glyphs(f)
        if flagged:
            warn.append(("overlap", f"{len(flagged)} glyphs flagged as overlapping ({', '.join(flagged[:3])}"
                                    f"{', ...' if len(flagged) > 3 else ''}): FreeType oversamples them; "
                                    "remove the overlaps (fontTools instancer OverlapMode.REMOVE)"))
        if "fvar" in f and hinted:
            warn.append(("vf-hints", "variable font with bytecode: the other instances distort under "
                                     "hintmedium/full; fonttune does not hint VFs (strip: ttfautohint --dehint)"))
        if hinted and "gasp" in f:
            bad = sorted(ppem for ppem, v in f["gasp"].gaspRange.items()
                         if not v & SYMMETRIC_SMOOTHING)
            if bad:
                where = ", ".join("the rest" if p == 0xFFFF else f"<= {p} ppem" for p in bad)
                warn.append(("gasp", f"gasp leaves symmetric smoothing off ({where}): FreeType "
                                     "2.15 renders ttfautohint's bytecode differently up to ~20 px "
                                     "unless the stems are natural (fonttune gasp=smooth or keep)"))
        name = f["name"]
        fam = name.getDebugName(16) or name.getDebugName(1)
        if not fam or not fam.strip():
            warn.append(("names", "no family name (nameID 16 or 1)"))
    return warn


def main(argv=None):
    ap = argparse.ArgumentParser(prog="fonttune check", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("fonts", nargs="+")
    ap.add_argument("--fontbakery", action="store_true", help="also run fontbakery check-universal")
    a = ap.parse_args(argv)
    missing = [p for p in a.fonts if not os.path.isfile(p)]
    if missing:
        ap.error(f"no such file: {', '.join(missing)}")
    fb = shutil.which("fontbakery") if a.fontbakery else None
    if a.fontbakery and not fb:
        ap.error("--fontbakery: fontbakery is not installed (pip install fontbakery)")
    status = 0
    for p in a.fonts:
        try:
            warn = check(p)
        except Exception as e:  # fontTools raises many types on broken fonts
            warn = [("load", f"cannot read: {e}")]
        print(f"{os.path.basename(p)}: {'ok' if not warn else f'{len(warn)} warning(s)'}")
        for c, msg in warn:
            print(f"  [{c}] {msg}")
        status |= bool(warn)
    if fb:
        r = subprocess.run([fb, "check-universal", *a.fonts], stdin=subprocess.DEVNULL)
        status |= r.returncode != 0
    return int(status)


if __name__ == "__main__":
    sys.exit(main())
