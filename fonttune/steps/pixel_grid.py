#!/usr/bin/env python3
"""Put glyph advances and pair kerning on whole pixels at one target size.

With subpixel positioning every glyph starts at a fractional pixel, so the same
stem is rasterised differently from letter to letter (one dark column here, two
grey ones there) and the weight of a word looks uneven. If every advance and every
kern value is a whole number of pixels at the target size, all glyphs start on the
pixel grid and identical letters render identically, with subpixel positioning on
or off. The grid also holds at whole multiples of the size (32 px at 200%
scaling). At other sizes positions are fractional again, and the rounding shows as
spacing changes: up to half a target pixel per glyph, scaled with the size.

  pixel_grid.py [--ppem 16] -o OUTDIR FONT...

Static TrueType-flavoured fonts only (hmtx is the only place the advances live,
HVAR / CFF widths are not touched): variable and CFF fonts and monospaced fonts are
copied unchanged. Outlines and mark anchors are not moved; the rounding goes into the
right sidebearing, and kerning values are rounded to whole pixels: at the target size a
pair's gap changes by at most half a pixel, and kerns under half a pixel become 0
(Inter at 16 ppem keeps 6 of 15 kerned test pairs).

The grid is exact only when unitsPerEm / ppem is a whole number of font units
(2048 at 16, 1000 at 20). Otherwise every advance is off by a fraction of a unit and
the error adds up along a line (up to 0.5 px over 80 characters); a warning says so.
"""
import argparse, os, shutil
from fontTools.ttLib import TTFont


def rnd(v, unit):
    return int(round(v / unit)) * unit


def kern_values(font):
    gpos = font["GPOS"].table
    for lk in gpos.LookupList.Lookup:
        for st in lk.SubTable:
            if lk.LookupType == 9: st = st.ExtSubTable
            if st.__class__.__name__ != "PairPos": continue
            if st.Format == 1:
                for ps in st.PairSet:
                    for pvr in ps.PairValueRecord:
                        yield pvr.Value1
            else:
                for c1 in st.Class1Record:
                    for c2 in c1.Class2Record:
                        yield c2.Value1


def process(src, dst, ppem):
    f = TTFont(src)
    if "fvar" in f or "glyf" not in f or f["post"].isFixedPitch or "CFF " in f or "CFF2" in f:
        shutil.copy(src, dst); return "skipped"
    if ppem <= 0: raise SystemExit("--ppem must be positive")
    unit = f["head"].unitsPerEm / ppem
    if abs(unit - round(unit)) > 1e-6:
        print(f"  warning: {os.path.basename(src)}: {f['head'].unitsPerEm} units / {ppem:g} ppem "
              f"= {unit:.3f} units per pixel; advances cannot all be whole pixels "
              f"(pick a ppem that divides the units per em)")
    hmtx = f["hmtx"].metrics
    n = 0
    for g, (adv, lsb) in list(hmtx.items()):
        if adv <= 0: continue            # combining marks
        new = max(unit, rnd(adv, unit))
        if new != adv: hmtx[g] = (int(round(new)), lsb); n += 1
    k = 0
    if "GPOS" in f:
        for v in kern_values(f):
            if v is not None and getattr(v, "XAdvance", None):
                nv = int(round(rnd(v.XAdvance, unit)))
                if nv != v.XAdvance: v.XAdvance = nv; k += 1
    f["hhea"].advanceWidthMax = max(a for a, _ in hmtx.values())
    f.save(dst)
    return f"{n} advances, {k} kern values"


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("fonts", nargs="+"); p.add_argument("-o", "--out", required=True)
    p.add_argument("--ppem", type=float, default=16)
    a = p.parse_args()
    os.makedirs(a.out, exist_ok=True)
    for src in a.fonts:
        print(os.path.basename(src), process(src, os.path.join(a.out, os.path.basename(src)), a.ppem))
