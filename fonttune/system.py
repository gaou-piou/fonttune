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
