"""Size-aware stem darkening: a FREETYPE_PROPERTIES curve fitted to one font.

FreeType's stem darkening (autofitter and CFF drivers; it only acts under
hinting=slight, i.e. FT_LOAD_TARGET_LIGHT) emboldens a glyph by an amount
read off a curve of four points x1,y1 .. x4,y4: x is the font's standard stem
width in 1/1000 px at the current size, y the darkening in 1/1000 px. Below
x1 the amount stays y1, above x4 it is 0. The stock curve
(500,400,1000,275,1667,275,2333,0) adds about 9% ink to a regular UI font at
16 px: more than the stem gain it is meant for, and it is all-or-nothing per
monitor because the property is global.

This fits the curve to one font instead:
  * the stem is measured on the system FreeType from 'o' (the glyph the
    autofitter takes its standard width from for Latin),
  * the curve is flat at y0 up to the stem at --ppem, falls linearly and
    reaches 0 at the stem at --zero-at (HiDPI: nothing changes there),
  * y0 is searched until the text gains --ink percent of ink at --ppem.

It prints the FREETYPE_PROPERTIES line; it never writes a file. Only fonts
drawn under hintslight are affected (GTK4 with hinting none, and Chromium,
are not), and every autofitted/CFF font on the system gets the same curve.
"""
import argparse
import math
import os
import sys

from .ftrender import TEXT, Renderer

BASE = "truetype:interpreter-version=40"
DOTTED = "ijäöüÄÖÜïϊΐΰ;:!?"


def props(curve):
    if curve is None:
        return f"{BASE} autofitter:no-stem-darkening=1 cff:no-stem-darkening=1"
    c = ",".join(map(str, curve))
    return (f"{BASE} autofitter:no-stem-darkening=0 autofitter:darkening-parameters={c}"
            f" cff:no-stem-darkening=0 cff:darkening-parameters={c}")


def renderer(curve):
    """A Renderer whose library was created under the curve (FreeType reads the env then)."""
    old = os.environ.get("FREETYPE_PROPERTIES")
    os.environ["FREETYPE_PROPERTIES"] = props(curve)
    try:
        return Renderer()
    finally:
        if old is None:
            del os.environ["FREETYPE_PROPERTIES"]
        else:
            os.environ["FREETYPE_PROPERTIES"] = old


def stem_per_ppem(font, glyph="o", size=1000):
    """Width of the left bowl of glyph on its middle row, in px per ppem."""
    with renderer(None) as r:
        for _, rows, width, data in r.glyphs(font, size, glyph, mode="none"):
            row = data[rows // 2 * width:(rows // 2 + 1) * width]
            ink = [i for i, v in enumerate(row) if v >= 128]
            if not ink:
                break
            run = 1
            while ink[0] + run < width and row[ink[0] + run] >= 128:
                run += 1
            return run / size
    raise SystemExit(f"darken: no '{glyph}' to measure in {font}")


def make_curve(y0, a, b):
    """Flat y0 up to stem a (1/1000 px), linear down to 0 at stem b.

    Valid for y0 <= 3/4 (b - a) with b - a >= 30 (see check())."""
    d = b - a
    return [a, y0, a + d // 3, y0 - y0 // 3, a + 2 * d // 3, y0 // 3, b, 0]


def check(curve):
    """FreeType's own rules for darkening-parameters (ftdriver.h)."""
    xs, ys = curve[0::2], curve[1::2]
    if not all(x0 < x1 for x0, x1 in zip(xs, xs[1:])):
        return "x must increase"
    if not all(y0 >= y1 for y0, y1 in zip(ys, ys[1:])):
        return "y must not increase"
    if not all(0 <= y <= 500 for y in ys):
        return "y must lie in 0..500"
    for (x0, y0), (x1, y1) in zip(zip(xs, ys), zip(xs[1:], ys[1:])):
        if y0 - y1 >= x1 - x0:
            return "a segment is steeper than -1"
    return ""


def gaps(r, font, ppem):
    """Dotted glyphs that keep an empty row between dot and body."""
    out = set()
    for ch, rows, width, data in r.glyphs(font, ppem, DOTTED):
        lines = [max(data[i * width:(i + 1) * width], default=0) for i in range(rows)]
        inked = [i for i, v in enumerate(lines) if v >= 64]
        if inked and any(lines[i] < 64 for i in range(inked[0], inked[-1])):
            out.add(ch)
    return out


def fit(font, ppem, zero_at, target, text=TEXT):
    s = stem_per_ppem(font)
    a, b = round(s * ppem * 1000 * 1.1), round(s * zero_at * 1000 * 0.95)
    if b - a < 30:
        raise SystemExit(f"darken: --zero-at {zero_at:g} is too close to --ppem {ppem:g} "
                         f"(stems {s * ppem:.2f} vs {s * zero_at:.2f} px)")
    ymax = min(500, (b - a) * 3 // 4)
    with renderer(None) as off:
        base = off.ink(font, ppem, text)
    if not base:
        raise SystemExit(f"darken: {font} draws none of the sample text")
    lo, hi, best = 0, ymax, None
    while lo <= hi:
        y0 = (lo + hi) // 2
        c = make_curve(y0, a, b)
        if check(c):
            hi = y0 - 1
            continue
        with renderer(c) as r:
            gain = r.ink(font, ppem, text) / base - 1
        best = (c, gain) if best is None or abs(gain - target) < abs(best[1] - target) else best
        if gain < target:
            lo = y0 + 1
        else:
            hi = y0 - 1
    return s, best[0], best[1]


def report(fonts, curve, sizes, text=TEXT):
    rows = []
    with renderer(None) as off, renderer(curve) as on:
        for f in fonts:
            lost = sorted(gaps(off, f, min(sizes)) - gaps(on, f, min(sizes)))
            gains = [on.ink(f, p, text) / (off.ink(f, p, text) or 1) - 1 for p in sizes]
            rows.append((f, gains, lost))
    return rows


def main(argv=None):
    from .system import auto_ppem
    ap = argparse.ArgumentParser(prog="fonttune darken", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("fonts", nargs="+", help="fit on the first; report on all")
    ap.add_argument("--ppem", type=float, help="size to darken at (default: GNOME UI font size)")
    ap.add_argument("--zero-at", type=float, help="ppem where darkening reaches 0 (default: 2 x --ppem)")
    ap.add_argument("--ink", type=float, default=2.5, help="ink gain at --ppem, percent (default 2.5)")
    ap.add_argument("--quiet", action="store_true", help="print only the FREETYPE_PROPERTIES value")
    a = ap.parse_args(argv)
    if any(v is not None and not (math.isfinite(v) and v > 0) for v in (a.ppem, a.zero_at)):
        ap.error("--ppem and --zero-at must be positive numbers")
    with Renderer() as r:
        bad = [f"{f} ({why})" for f in a.fonts if (why := r.unreadable(f))]
    if bad:
        ap.error(f"cannot read {', '.join(bad)}")
    ppem = a.ppem or auto_ppem()
    zero = a.zero_at or 2 * ppem
    if zero <= ppem:
        ap.error("--zero-at must be larger than --ppem")
    if ppem < 1 or zero >= 10000:
        ap.error("--ppem must be at least 1 and --zero-at below 10000")
    if not 0 < a.ink <= 20:
        ap.error("--ink is a percentage in (0, 20]")
    s, curve, gain = fit(a.fonts[0], ppem, zero, a.ink / 100)
    if err := check(curve):
        raise SystemExit(f"darken: internal error, curve {curve}: {err}")
    far = abs(gain * 100 - a.ink) > 1.0
    if far:
        print(f"darken: closest reachable gain is {gain * 100:.1f}%, not {a.ink:g}% "
              f"(--zero-at too close to --ppem, or the steps are coarse)", file=sys.stderr)
    if a.quiet:
        print(props(curve))
        return 0
    sizes = sorted({ppem, round(ppem * 1.25, 2), round(ppem * 1.5, 2), zero})
    print(f"stem ('o'): {s * ppem:.2f} px at {ppem:g} ppem, {s * zero:.2f} px at {zero:g} ppem")
    print(f"curve: {','.join(map(str, curve))}\n")
    print("ink gain    " + "".join(f"{p:>8g}" for p in sizes) + "   dots that merge")
    for f, gains, lost in report(a.fonts, curve, sizes):
        print(f"{os.path.basename(f)[:40]:40}\n            " + "".join(f"{g * 100:>7.1f}%" for g in gains)
              + "   " + ("".join(lost) or "none"))
    print("\nonly hintslight text is affected, every autofitted/CFF font gets this curve. "
          "Put this in ~/.config/environment.d/*.conf and log in again:\n")
    print(f"FREETYPE_PROPERTIES={props(curve)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
