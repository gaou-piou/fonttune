#!/usr/bin/env python3
"""ttfautohint one TrueType font in place, with a named preset.

Usage:  hint.py PRESET FONT.ttf [--mode nqs] [--min N] [--max N] [--limit N]
                [--xheight N] [--xsnap STR]

Only the THIRD letter of the stem-width mode matters on Linux: FreeType's v40
interpreter reports itself to the bytecode as DirectWrite ClearType.
FreeType runs the bytecode only at hintmedium/hintfull; under hintslight it
uses its own autohinter and ignores these hints (see `fonttune hintconf`).
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile

#            mode  min max xheight
PRESETS = {
    "balanced": ("qsq", 8, 50, 14),   # upstream defaults
    "sharp":    ("sss", 6, 50, 14),   # max contrast, low DPI
    "natural":  ("nnn", 8, 50, 0),    # least distortion
    "light":    ("nnn", 12, 50, 0),   # HiDPI: < 12 px left alone
}
# i/j dots and diaereses touch the letter at Bold/Heavy 10-13 px otherwise
XSNAP_DEFAULT = "10-13"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("preset", choices=sorted(PRESETS))
    ap.add_argument("font")
    ap.add_argument("--mode")
    ap.add_argument("--min", type=int)
    ap.add_argument("--max", type=int)
    ap.add_argument("--limit", type=int, help="default: same as --max")
    ap.add_argument("--xheight", type=int)
    ap.add_argument("--xsnap", help="x-height snapping exceptions, '' for none")
    a = ap.parse_args()

    exe = shutil.which("ttfautohint")
    if not exe:
        sys.exit("hint: ttfautohint not found (pacman -S ttfautohint)")
    mode, lo, hi, xh = PRESETS[a.preset]
    mode = a.mode or mode
    lo = lo if a.min is None else a.min
    hi = hi if a.max is None else a.max
    xh = xh if a.xheight is None else a.xheight
    lim = hi if a.limit is None else a.limit
    xsnap = XSNAP_DEFAULT if a.xsnap is None else a.xsnap
    if not re.fullmatch(r"[nqs]{3}", mode):
        sys.exit(f"hint: mode {mode!r} must be 3 letters from n q s")
    if lo > hi:
        sys.exit(f"hint: range min {lo} > max {hi}")

    # PUA glyphs (SF Symbols / Nerd icons): scale them, do not hint as Latin.
    cmd = [exe, f"--hinting-range-min={lo}", f"--hinting-range-max={hi}",
           f"--hinting-limit={lim}", f"--increase-x-height={xh}",
           f"--x-height-snapping-exceptions={xsnap}", f"--stem-width-mode={mode}",
           "--fallback-script=none", "--fallback-scaling", "--ignore-restrictions",
           "--no-info"]
    # cvar deltas point into the cvt that ttfautohint rewrites: drop them
    from fontTools.ttLib import TTFont
    f = TTFont(a.font)
    if "cvar" in f:
        del f["cvar"]
        f.save(a.font)
    f.close()
    fd, tmp = tempfile.mkstemp(suffix=".ttf", dir=os.path.dirname(os.path.abspath(a.font)))
    os.close(fd)
    try:
        subprocess.run([*cmd, a.font, tmp], check=True)
        os.replace(tmp, a.font)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


if __name__ == "__main__":
    main()
