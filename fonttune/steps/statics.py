#!/usr/bin/env python3
"""Cut static instances out of variable fonts, with proper RIBBI naming.

Usage:
  statics.py -o OUTDIR --family NAME [--suffix S] [--weights "300 400 ..."]
             [--axis TAG=VALUE ...] [--regular-wght N|auto] [--no-scale]
             [--fit-ppem 16] [--fit-tolerance 0.25] VF.ttf [VF.ttf ...]

Why
---
font-patcher drops fvar/gvar, some programs cannot use variable fonts, and a
static is hinted on its own: ttfautohint takes its blue zones from that exact
weight instead of from the default master.

fontTools' instancer can name instances from STAT, but static families need the
RIBBI split (nameID 1/2 vs 16/17), so names, style bits and italic metadata are
written here:

  nameID 1/2     RIBBI family + style ("Akt SemiBold" / "Italic")
  nameID 16/17   typographic family + subfamily ("Akt" / "SemiBold Italic")
  nameID 3/4/6   unique ID, full name, PostScript name
  OS/2           usWeightClass, usWidthClass (wdth pin), fsSelection
                 ITALIC/BOLD/REGULAR (USE_TYPO_METRICS / WWS are kept)
  head.macStyle, post.italicAngle and hhea caret slope for italics

--axis pins any other axis (opsz=14, wdth=75, FLAR=100, slnt=-10 ...); axes not
given stay at their default. opsz=auto is the GNOME interface font size in
points, without text-scaling-factor (GTK scales through the resolution):
Pango (1.56.2 and later) sets opsz to the point size when it draws a variable
font, outlines included, so statics cut there look like the VF does in the UI (Roboto
Flex at 12 pt / 16 px: opsz 14 instead of 12 is 2.3% less ink, 1.2% narrower).
A pin outside the axis range is clamped to it. A font counts as italic when slnt is pinned to a
non-zero value or the input font is already italic (fsSelection / italicAngle).
--suffix is appended to the family ("Condensed", "Flare") so fontconfig never
mixes widths or voices in one family.

--regular-wght N (or "auto": measured with fit_weight.py) cuts the Regular at
wght N instead of 400 and, unless --no-scale, re-spaces the weights below 700
linearly (100-400 and 400-700) so the family stays evenly stepped; the files
are still named as the standard weights.
"""
import argparse
import math
import os
import sys

from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import OverlapMode, instantiateVariableFont

WEIGHTS = {100: "Thin", 200: "ExtraLight", 300: "Light", 400: "Regular",
           500: "Medium", 600: "SemiBold", 700: "Bold", 800: "ExtraBold",
           900: "Black", 1000: "ExtraBlack"}
WIDTH_CLASS = {25: 1, 50: 1, 62.5: 2, 75: 3, 87.5: 4, 100: 5, 112.5: 6,
               125: 7, 150: 8, 151: 8}
FS_ITALIC, FS_BOLD, FS_REGULAR = 1 << 0, 1 << 5, 1 << 6


def num(s):
    try:
        v = float(s)
    except ValueError:
        sys.exit(f"statics: not a number: {s!r}")
    return int(v) if v.is_integer() else v


def cut_for(w, regular, scale):
    """wght to cut for the standard weight w when Regular is cut at `regular`."""
    if regular is None or regular == 400:
        return w
    if w == 400:
        return regular
    if not scale or w >= 700:
        return w
    if w < 400:
        return round(100 + (w - 100) * (regular - 100) / 300)
    return round(regular + (w - 400) * (700 - regular) / 300)


def ui_pt():
    """GNOME interface font size in points (fonttune.system; 12 when unreadable)."""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    from fonttune.system import font_pt
    pt = font_pt()
    print(f"statics: opsz auto: {pt:g} (interface font size in points)")
    return pt


_CLAMP_NOTED = set()


def make_static(path, outdir, family, suffix, weight, cut, pins):
    font = TTFont(path)
    axes = {ax.axisTag: ax for ax in font["fvar"].axes}
    for tag in pins:
        if tag not in axes:
            sys.exit(f"statics: {path} has no {tag} axis (has {', '.join(axes)})")
    clamped = {t: min(max(v, axes[t].minValue), axes[t].maxValue) for t, v in pins.items()}
    for t in pins:
        if clamped[t] != pins[t] and (path, t) not in _CLAMP_NOTED:
            _CLAMP_NOTED.add((path, t))
            print(f"statics: {t}={pins[t]:g} is outside {axes[t].minValue:g}-{axes[t].maxValue:g}, "
                  f"using {clamped[t]:g}")
    if pins.get("slnt") and not clamped["slnt"]:
        sys.exit(f"statics: slnt={pins['slnt']:g} clamps to 0, which would overwrite the upright")
    pins = clamped
    wax = axes.get("wght")
    if wax is None:
        sys.exit(f"statics: {path} has no wght axis")
    if not wax.minValue <= cut <= wax.maxValue:
        return None  # this master does not reach that weight
    italic_src = bool(font["OS/2"].fsSelection & FS_ITALIC) or font["post"].italicAngle != 0
    limits = {t: a.defaultValue for t, a in axes.items()}
    limits.update(pins)
    limits["wght"] = cut
    italic = italic_src or bool(pins.get("slnt", 0))
    # REMOVE merges overlapping contours. The default (KEEP_AND_SET_FLAGS) marks
    # every glyph OVERLAP_SIMPLE, and FreeType renders such glyphs with 4x4
    # oversampling: slower and slightly different coverage at the joins.
    font = instantiateVariableFont(font, limits, updateFontNames=False,
                                   overlap=OverlapMode.REMOVE)
    if "STAT" in font:
        # its axis values point at name IDs >= 256, deleted below (OTS then rejects
        # the table); a static font does not need STAT, and `trak = "stat"` adds one
        del font["STAT"]

    fam = family + (" " + suffix if suffix else "")
    wname = WEIGHTS[weight]
    sub = ("Italic" if italic else "Regular") if weight == 400 else wname + (" Italic" if italic else "")
    ribbi = weight in (400, 700)
    fam1 = fam if ribbi else f"{fam} {wname}"
    sub2 = (("Bold " if weight == 700 else "") + ("Italic" if italic else "")).strip() or "Regular"
    ps = fam.replace(" ", "") + "-" + sub.replace(" ", "")
    vendor = (font["OS/2"].achVendID or "").strip() or "FTUN"
    ver = (font["name"].getDebugName(5) or "Version 1.0").replace("Version ", "").split(";")[0]

    name = font["name"]
    # IDs >= 256 and 25 describe axes this font no longer has
    name.names = [n for n in name.names if n.nameID < 256 and n.nameID != 25]
    for nid, val in ((1, fam1), (2, sub2), (3, f"{ver};{vendor};{ps}"),
                     (4, f"{fam} {sub}"), (6, ps), (16, fam), (17, sub)):
        name.removeNames(nameID=nid)
        if nid in (16, 17) and ribbi and (fam1, sub2) == (fam, sub):
            continue
        name.setName(val, nid, 3, 1, 0x409)
        name.setName(val, nid, 1, 0, 0)

    os2 = font["OS/2"]
    os2.usWeightClass = weight
    if "wdth" in pins:
        os2.usWidthClass = WIDTH_CLASS[min(WIDTH_CLASS, key=lambda k: abs(k - pins["wdth"]))]
    sel = os2.fsSelection & ~(FS_ITALIC | FS_BOLD | FS_REGULAR)
    if italic:
        sel |= FS_ITALIC
    if weight == 700:
        sel |= FS_BOLD
    if not italic and weight != 700:
        sel |= FS_REGULAR
    os2.fsSelection = sel
    font["head"].macStyle = (1 if weight == 700 else 0) | (2 if italic else 0)
    if "slnt" in pins:
        font["post"].italicAngle = float(pins["slnt"])
    angle = -font["post"].italicAngle
    hhea = font["hhea"]
    if italic and angle:
        hhea.caretSlopeRise = font["head"].unitsPerEm
        hhea.caretSlopeRun = round(hhea.caretSlopeRise * math.tan(math.radians(angle)))
        hhea.caretOffset = 0
    else:
        hhea.caretSlopeRise, hhea.caretSlopeRun = 1, 0
    out = os.path.join(outdir, ps + ".ttf")
    font.save(out)
    print(f"  {fam1:28s} {sub2:12s} (wght {cut:g})")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--outdir", required=True)
    ap.add_argument("--family", required=True)
    ap.add_argument("--suffix", default="")
    ap.add_argument("--weights", default="100 200 300 400 500 600 700 800 900")
    ap.add_argument("--axis", action="append", default=[], metavar="TAG=VALUE")
    ap.add_argument("--regular-wght", default="")
    ap.add_argument("--no-scale", action="store_true")
    ap.add_argument("--fit-ppem", type=float, default=16.0)
    ap.add_argument("--fit-tolerance", type=float, default=0.25)
    ap.add_argument("fonts", nargs="+")
    a = ap.parse_args(argv)

    pins = {}
    for item in a.axis:
        tag, _, val = item.partition("=")
        if not tag or not val:
            sys.exit(f"statics: --axis wants TAG=VALUE, got {item!r}")
        pins[tag] = ui_pt() if (tag, val.lower()) == ("opsz", "auto") else num(val)
    weights = [num(w) for w in a.weights.split()]
    for w in weights:
        if w not in WEIGHTS:
            sys.exit(f"statics: weight {w} is not one of {sorted(WEIGHTS)}")
    regular = None
    if a.regular_wght:
        if a.regular_wght == "auto":
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import fit_weight
            best = fit_weight.best_regular(a.fonts[0], a.fit_ppem, a.fit_tolerance)
            if best and best != 400:
                print(f"statics: regular-wght auto: bars fit at wght {best} ({a.fit_ppem:g} ppem)")
                regular = best
            else:
                print("statics: regular-wght auto: 400 already fits (or nothing does); unchanged")
        else:
            regular = num(a.regular_wght)
            if not 100 <= regular <= 900:
                sys.exit("statics: --regular-wght must be 100-900")
        if regular and 400 not in weights:
            weights = [400] + weights
    os.makedirs(a.outdir, exist_ok=True)
    made = 0
    for path in a.fonts:
        for w in weights:
            if make_static(path, a.outdir, a.family, a.suffix, w,
                           cut_for(w, regular, not a.no_scale), pins):
                made += 1
    if not made:
        sys.exit("statics: no instance produced")
    return 0


if __name__ == "__main__":
    sys.exit(main())
