"""Which UI sizes keep a font's x-height: the hinted x-height per size.

Under hintslight (GTK4's default, Chromium, most of the desktop) FreeType's
autofitter rounds the x-height to whole pixels (up from .375, aflatin.c),
rescales the vertical axis to match, then snaps the other heights (capitals,
ascenders) on their own. The lowercase grows or shrinks by a different amount
at every size (Adwaita Sans: +7.7% at 17 px, -3.9% at 13.33 px) and against
the capitals too. Sizes where both stay within --tolerance are listed as clean.

The x-height is read from the top of 'x', the cap height from 'H', on the
system FreeType (outline only: no rasterisation, no anti-aliasing guesswork).
A variable font with an opsz axis is measured at opsz = the size in points,
which is what Pango (1.56.2 and later) uses. --mode full measures the font's
own bytecode (hintmedium/hintfull); a font without one is autohinted there too.
"""
import argparse
import math
import os
import sys

from fontTools.ttLib import TTFont

from .ftrender import Renderer

DEFAULT_PT = [9, 9.5, 10, 10.5, 11, 11.5, 12, 12.5, 13, 13.5, 14]


def has_opsz(font):
    with TTFont(font, lazy=True) as t:
        return "fvar" in t and any(a.axisTag == "opsz" for a in t["fvar"].axes)


def has_bytecode(font):
    with TTFont(font, lazy=True) as t:
        return "fpgm" in t or "prep" in t


def table(font, sizes, mode="slight", r=None, scale=1.0):
    """-> [(ppem, exact x-height, hinted x-height, x change, x/H change)].

    Raises ValueError when the font has no 'x'. opsz (if any) follows ppem
    as points: ppem * 72/96 / scale."""
    own = r is None
    r = r or Renderer()
    opsz = has_opsz(font)
    try:
        rows = []
        for p in sizes:
            axes = {"opsz": p * 72 / 96 / scale} if opsz else None
            ex, eh, hx, hh = (r.extent(font, p, c, m, axes) for m in ("none", mode) for c in "xH")
            if not (ex and hx):
                raise ValueError(f"{font} has no 'x'")
            dx = hx[0] / ex[0] - 1
            dr = (hx[0] / hh[0]) / (ex[0] / eh[0]) - 1 if eh and hh else float("nan")
            rows.append((p, ex[0], hx[0], dx, dr))
        return rows
    finally:
        if own:
            r.close()


def main(argv=None):
    from .system import auto_ppem, text_scale
    ap = argparse.ArgumentParser(prog="fonttune xheight", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("fonts", nargs="+")
    ap.add_argument("--pt", help="comma-separated point sizes (default 9 to 14 in half points)")
    ap.add_argument("--mode", choices=("slight", "full"), default="slight",
                    help="slight: autofitter (default); full: the font's bytecode")
    ap.add_argument("--tolerance", type=float, default=1.5,
                    help="largest x-height and x/H change still clean, percent (default 1.5)")
    a = ap.parse_args(argv)
    try:
        pts = [float(x) for x in a.pt.split(",")] if a.pt else DEFAULT_PT
    except ValueError:
        ap.error("--pt takes numbers separated by commas")
    if any(p <= 0 for p in pts):
        ap.error("--pt sizes must be positive")
    if a.tolerance < 0:
        ap.error("--tolerance must not be negative")
    scale = text_scale()
    now = auto_ppem()
    sizes = [round(p * 96 / 72 * scale, 2) for p in pts]
    print(f"text-scaling-factor {scale:g}, UI font now {now:g} ppem; mode {a.mode}\n")
    with Renderer() as r:
        for f in a.fonts:
            print(os.path.basename(f) + (" (opsz = pt)" if has_opsz(f) else ""))
            if a.mode == "full" and not has_bytecode(f):
                print("  no bytecode (fpgm/prep): FreeType autohints it under full too\n")
                continue
            try:
                rows = table(f, sizes, a.mode, r, scale)
            except ValueError as e:
                print(f"  skipped: {e}\n")
                continue
            print("      pt   ppem   x exact  x hinted  change   x/H")
            clean = []
            for pt, (p, ex, hx, dx, dr) in zip(pts, rows):
                ok = abs(dx) * 100 <= a.tolerance and abs(dr) * 100 <= a.tolerance
                if ok:
                    clean.append(f"{pt:g} pt")
                mark = (" clean" if ok else "") + (" <- now" if abs(p - now) < 0.01 else "")
                ratio = "   n/a" if math.isnan(dr) else f"{dr * 100:+5.1f}%"
                print(f"  {pt:6g} {p:6g}  {ex:8.2f}  {hx:8.2f}  {dx * 100:+5.1f}%  {ratio}{mark}")
            print(f"  clean sizes: {', '.join(clean) or 'none'}\n")
    print("change: hinted against exact x-height; x/H: lowercase against capitals. "
          "(n/a: no 'H'). Only text hinted this way is affected (GTK4 automatic = hintslight).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
