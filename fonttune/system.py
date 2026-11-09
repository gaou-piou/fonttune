"""Read the desktop settings that decide what `auto` means."""
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
    m = re.match(r"^'.* (\d+(?:\.\d+)?)'$", _gsettings("font-name"))
    if not m:
        return 16.0
    t = _gsettings("text-scaling-factor")
    try:
        t = float(t)
    except ValueError:
        t = 1.0
    return round(float(m.group(1)) * 96 / 72 * t, 4)


def auto_pt():
    """GNOME interface font size (pt) x text-scaling-factor: the size body text is set at.

    The size `trak = "auto"` bakes the Apple tracking at (the table is in points).
    Same source as auto_ppem(): 12 pt at scale 1.0 is 16 ppem.
    """
    return round(auto_ppem() * 72 / 96, 4)


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
