#!/usr/bin/env python3
"""Normalise OS/2 usWeightClass of Apple's static fonts to the standard scale.

Usage:  fix_weights.py FONT [FONT ...]      (edited in place; .otf or .ttf)

Why this exists
---------------
Apple ships every New York optical size (Small, Medium, Large, Extra Large)
with two pairs of colliding weight classes:

    Regular 400  Medium 500  Semibold 600  Bold 600  Heavy 800  Black 800

Bold and Semibold share 600, Heavy and Black share 800. fontconfig can then
only tell them apart by style name, and a plain "bold" request (weight 700)
lands on the wrong face. Verified with fc-match against the stock files:

    fc-match "New York Small:bold"  -> New York Small Black

Rewriting the weight classes to the conventional values (Bold 700, Black 900)
fixes this. The other families already use the standard scale, apart from
SF Mono Heavy at 900 (SF Mono has no Black), which becomes 800 like Heavy
everywhere else. Only OS/2.usWeightClass is touched; the name table and
outlines are left alone. Variable fonts are skipped: their weight comes from
the fvar axis, not from usWeightClass.

Apple fonts (vendor APPL) use Apple's scale, where Ultralight (100) sits below
Thin (200); every other family uses the OpenType scale, Thin 100 and ExtraLight
200, so Inter Thin is not pushed onto ExtraLight.

The weight is looked up by the font's own subfamily name (nameID 17, falling
back to nameID 2, with any "Italic" dropped), never by filename.
"""
import sys

from fontTools.ttLib import TTFont

# Apple's own scale: Ultralight below Thin (SF Pro Ultralight 100, Thin 200).
APPLE_WEIGHTS = {
    "ultralight": 100,
    "thin": 200,
    "light": 300,
    "regular": 400,
    "medium": 500,
    "semibold": 600,
    "bold": 700,
    "heavy": 800,
    "black": 900,
}

# Everyone else (OpenType spec, Google Fonts): Thin is the lightest, 100.
WEIGHTS = {
    "thin": 100, "hairline": 100,
    "extralight": 200, "ultralight": 200,
    "light": 300,
    "regular": 400,
    "medium": 500,
    "semibold": 600, "demibold": 600,
    "bold": 700,
    "extrabold": 800, "ultrabold": 800,
    "black": 900, "heavy": 900,  # the spec's "Black (Heavy)"; Iosevka, Source Han
}


# Families whose vendor scale differs from Apple's (matched on the start of
# the family name, nameID 16 then 1). MiSans Latin ships
#   Thin 150 ExtraLight 200 Light 250 Normal 305 Regular 330 Medium 380
#   Demibold 450 Semibold 520 Bold 630 Heavy 700
# which makes fontconfig pick Medium for "regular" and Heavy for "bold".
FAMILY_WEIGHTS = {
    "MiSans": {
        "thin": 100, "extralight": 200, "light": 300, "normal": 350,
        "regular": 400, "medium": 500, "demibold": 550, "semibold": 600,
        "bold": 700, "heavy": 900,
    },
}


def _table(font):
    name = font["name"]
    fam = name.getDebugName(16) or name.getDebugName(1) or ""
    for prefix, table in FAMILY_WEIGHTS.items():
        if fam.startswith(prefix):
            return table
    return APPLE_WEIGHTS if font["OS/2"].achVendID.strip() == "APPL" else WEIGHTS


def _subfamily(font):
    name = font["name"]
    for name_id in (17, 2):
        rec = name.getName(name_id, 3, 1, 0x409) or name.getName(name_id, 1, 0, 0)
        if rec is not None:
            return str(rec).strip()
    return None


def target(font, path="", warn=True):
    """(subfamily, old, new) for a static font, or None when it is not handled."""
    if "fvar" in font or "OS/2" not in font:
        return None
    sub = _subfamily(font)
    if sub is None:
        if warn:
            sys.stderr.write("fix_weights: %s: no subfamily name, skipped\n" % path)
        return None
    key = sub.lower().replace("italic", "").replace(" ", "").replace("-", "")
    key = key or "regular"
    table = _table(font)
    if key not in table:
        if warn:
            sys.stderr.write("fix_weights: %s: unknown subfamily %r, skipped\n" % (path, sub))
        return None
    return sub, font["OS/2"].usWeightClass, table[key]


def fix(path):
    font = TTFont(path)
    t = target(font, path)
    if t is None:
        return 0
    sub, old, new = t
    if old != new:
        font["OS/2"].usWeightClass = new
        font.save(path)
        print("  %-28s %-18s %4d -> %d" % (font["name"].getDebugName(1), sub, old, new))
    return 0


def main(argv):
    if len(argv) < 2:
        sys.stderr.write(__doc__)
        return 2
    rc = 0
    for path in argv[1:]:
        try:
            rc |= fix(path)
        except Exception as exc:  # noqa: BLE001 - report and continue
            sys.stderr.write("fix_weights: %s: %s\n" % (path, exc))
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv))
