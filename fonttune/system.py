"""Read the desktop settings that decide what `auto` means."""
import math
import re
import subprocess


def _gsettings(key):
    try:
        r = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", key],
                           capture_output=True, text=True, timeout=5, stdin=subprocess.DEVNULL)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def auto_ppem():
    """GNOME interface font size (pt) x 96/72 x text-scaling-factor, as ppem.

    Monitor scale is ignored on purpose: it is 1.0 on the setups this was
    measured on. Falls back to 16 ppem when the size cannot be read.
    """
    pt = _font_name_pt()
    return 16.0 if pt is None else round(pt * 96 / 72 * text_scale(), 4)


def _font_name_pt():
    """Size in GNOME's font-name ('Inter 11' -> 11.0), None when unreadable."""
    m = re.match(r"^'.* (\d+(?:\.\d+)?)'$", _gsettings("font-name"))
    return float(m.group(1)) if m else None


def text_scale():
    """GNOME text-scaling-factor, 1.0 when it cannot be read."""
    try:
        v = float(_gsettings("text-scaling-factor"))
    except ValueError:
        return 1.0
    return v if math.isfinite(v) and v > 0 else 1.0


def font_pt():
    """GNOME interface font size in points, without text-scaling-factor (12 if unreadable).

    GTK applies text-scaling-factor through the resolution, so Pango keeps this
    size (and sets opsz to it): measured on Pango 1.58 at 120 dpi, a 12 pt
    layout renders exactly as @opsz=12.
    """
    pt = _font_name_pt()
    return 12.0 if pt is None else pt


def auto_pt():
    """GNOME interface font size (pt) x text-scaling-factor: the size body text is set at.

    The size `trak = "auto"` bakes the Apple tracking at (the table is in points).
    Same source as auto_ppem(): 12 pt at scale 1.0 is 16 ppem.
    """
    return round(auto_ppem() * 72 / 96, 4)


# GNOME's font settings, in the order a family found in two of them takes its size from
USAGE_KEYS = (("font-name", "interface font"), ("document-font-name", "document font"),
              ("monospace-font-name", "monospace font"))
# Pango font-description words that are style, not family ('Adwaita Sans Bold 11')
_STYLE = {"normal", "roman", "regular", "book", "italic", "oblique", "thin", "hairline",
          "light", "extralight", "ultralight", "semilight", "demilight", "medium", "semibold",
          "semi-bold", "demibold", "demi-bold", "bold", "extrabold", "extra-bold",
          "ultrabold", "ultra-bold", "heavy", "black", "ultraheavy", "condensed",
          "semi-condensed", "expanded", "semi-expanded", "small-caps"}


def parse_font(value):
    """GNOME font setting -> (family, size in pt) or None.

    "'SF Pro 14 @opsz=17'" -> ("SF Pro", 14.0); style words and a family list
    after the first are dropped ("'Adwaita Sans Bold 11'" -> ("Adwaita Sans", 11.0))."""
    m = re.match(r"^'?(.+?),? (\d+(?:\.\d+)?)(?: @\S*)*'?$", value.strip())
    if not m:
        return None
    words = m.group(1).split(",")[0].split()
    while len(words) > 1 and words[-1].lower() in _STYLE:
        words.pop()
    return (" ".join(words), float(m.group(2))) if words else None


def usage_sizes():
    """[(family, pt x text-scaling-factor, label)] for GNOME's interface, document
    and monospace fonts (unreadable or unset ones are left out)."""
    scale, out = text_scale(), []
    for key, label in USAGE_KEYS:
        f = parse_font(_gsettings(key))
        if f:
            out.append((f[0], round(f[1] * scale, 4), label))
    return out


def usage_pt(family, sizes=None):
    """(pt, label) a family is used at, from usage_sizes(): an exact (case-blind)
    family match first, then a family that extends a set one ('SF Pro Text' under
    'SF Pro'). Not set anywhere: the interface size, auto_pt()."""
    sizes = usage_sizes() if sizes is None else sizes
    fam = family.casefold()
    for match in (lambda u: fam == u, lambda u: fam.startswith(u + " ")):
        for f, pt, label in sizes:
            if match(f.casefold()):
                return pt, f"{label} '{f}'"
    return auto_pt(), "interface size: the family is not one of GNOME's fonts"


def hintstyle():
    """'none' | 'slight' | 'medium' | 'full' as the desktop sets it ('' if unknown).

    GNOME's font-hinting first; fontconfig's answer for the default sans-serif
    otherwise. Note GTK4 with font-rendering=automatic hard-codes slight.
    """
    v = _gsettings("font-hinting").strip("'")
    if v in ("none", "slight", "medium", "full"):
        return v
    try:
        r = subprocess.run(["fc-match", "-v", "sans-serif"], capture_output=True,
                           text=True, timeout=5, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return ""
    m = re.search(r"hintstyle: (\d)", r.stdout)
    return {"0": "none", "1": "slight", "2": "medium", "3": "full"}.get(m.group(1), "") if m else ""
