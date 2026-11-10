"""Summary of the chosen settings, plus what to set up around the fonts."""
from .steps.hint import PRESETS
from .system import _gsettings, auto_ppem, hintstyle

LABELS = [
    ("otf2ttf", "CFF -> TrueType"), ("weights", "usWeightClass fix"), ("trak", "trak table"),
    ("even_spacing", "even spacing"), ("pixel_grid", "pixel grid (ppem)"),
    ("hint", "ttfautohint preset"), ("alts", "aalt alternates -> cvXX"),
    ("features", "baked features"),
    ("feature_suffix", "family suffix"), ("gasp", "gasp table"),
]


import os
import re
from pathlib import Path

CHROMIUM_FLAG = "--disable-font-subpixel-positioning"
FF_ROOTS = (".mozilla/firefox", ".librewolf", ".floorp")


def probe(home=None):
    """What the user already has: Firefox prefs, Chromium flag files, GTK key."""
    home = Path(home or Path.home())
    ff = {}  # profile -> {pref: value}
    for root in FF_ROOTS:
        for d in sorted((home / root).glob("*.default*")):
            if re.search(r"back|crash", d.name):
                continue
            vals = {}
            for fn in ("prefs.js", "user.js"):
                f = d / fn
                if not f.is_file():
                    continue
                for m in re.finditer(r'user_pref\("(gfx\.text\.subpixel-position\.force-(?:enabled|disabled))",\s*(true|false)',
                                     f.read_text(errors="ignore")):
                    vals[m.group(1).rsplit("force-", 1)[1]] = m.group(2)
            ff[f"{root.split('/')[0]}/{d.name}".lstrip(".")] = vals
    flags = sorted(p.name for p in (home / ".config").glob("*flags*.conf")
                   if CHROMIUM_FLAG in p.read_text(errors="ignore").split())
    gtk, ini_rendering = {}, ""
    for v in ("3", "4"):
        f = home / ".config" / f"gtk-{v}.0" / "settings.ini"
        if f.is_file():
            txt = f.read_text(errors="ignore")
            m = re.search(r"^gtk-hint-font-metrics\s*=\s*(\w+)", txt, re.M)
            gtk[f"gtk-{v}.0"] = m.group(1) if m else None
            m = re.search(r"^gtk-font-rendering\s*=\s*(\w+)", txt, re.M)
            if v == "4" and m:
                ini_rendering = m.group(1).lower()
    # GTK4 reads gtk-hint-font-metrics and the hint style only under 'manual'
    # (gtkwidget.c, update_pango_context); 'automatic' forces slight, metrics off.
    # GNOME's key wins; without it settings.ini, then GTK's default (automatic).
    rendering = _gsettings("font-rendering").strip("'") or ini_rendering or "automatic"
    return {"firefox": ff, "chromium_flag_files": flags, "gtk": gtk, "rendering": rendering}


def _names(xs, n=4):
    xs = list(xs)
    return ", ".join(xs[:n]) + (f" and {len(xs) - n} more" if len(xs) > n else "")


def _on(v):
    return v not in (False, "", "keep", None)


def summary(cfg):
    lines = []
    for k, label in LABELS:
        v = cfg[k]
        if k == "hint" and _on(v):
            extra = [f"{x[5:]}={cfg[x]}" for x in ("hint_mode", "hint_min", "hint_max",
                                                    "hint_limit", "hint_xheight", "hint_xsnap")
                     if str(cfg[x]) != "auto"]
            v = f"{v}" + (f" ({', '.join(extra)})" if extra else "")
        lines.append(f"  {label:22} {('yes' if v is True else v) if _on(v) else '-'}")
    return lines


def advice(cfg, hs=None, has_trak=True, state=None):
    """-> list of (where, text). hs: desktop hint style, '' when unknown.
    state: probe() result (None = probe this machine)."""
    hs = hintstyle() if hs is None else hs
    st = probe() if state is None else state
    out = []
    add = lambda where, text: out.append((where, text))  # noqa: E731
    grid = _on(cfg["pixel_grid"])
    rendering = st.get("rendering") or "automatic"
    manual = rendering == "manual"
    if _on(cfg["hint"]):
        if hs in ("slight", "none"):
            add("system", f"hint is on but the desktop uses '{hs}': FreeType ignores the bytecode. "
                          "Enable it for these fonts: sudo ln -s "
                          "/usr/share/fontconfig/conf.avail/80-<package>.conf /etc/fonts/conf.d/ "
                          "(the package ships it when hint is on)")
        if manual and hs in ("medium", "full"):
            add("system", f"GTK4 font-rendering is manual and font-hinting {hs}: GTK4 runs the bytecode")
        elif manual:
            add("system", "GTK4 font-rendering is already manual: it follows font-hinting "
                          "(set medium for the bytecode)")
        else:
            add("system", "GTK4 hard-codes hintslight unless: gsettings set org.gnome.desktop."
                          "interface font-rendering manual; ... font-hinting medium")
        add("browser", "Chromium/Electron are excluded from the snippet on purpose (hintmedium "
                       "rounds every advance there); they keep using the light autohinter")
    elif hs in ("medium", "full"):
        add("system", f"hint style is '{hs}' but hint is off: FreeType will run its own "
                      "autohinter on TrueType; turn hint on to use ttfautohint instead")
    if cfg["otf2ttf"] and hs == "none":
        add("system", "hint style 'none': TrueType conversion has no visible effect; "
                      "use slight (gsettings set org.gnome.desktop.interface font-hinting slight)")
    if cfg["otf2ttf"] and hs == "slight" and not _on(cfg["hint"]):
        add("system", "hintslight autohints TrueType only, so the conversion is what makes "
                      "the fonts snap; keep font-hinting at slight")

    # ── subpixel positioning: on in Firefox always; Chromium's flag only for the grid ──
    if grid:
        p = cfg["pixel_grid"]
        p = f"{auto_ppem():g}" if p == "auto" else p
        add("system", f"pixel grid is tuned for {p} ppem: set the UI font to that size "
                      "(pt = ppem x 0.75), text-scaling-factor 1.0, and no fractional monitor scale")
    want_metrics = "true" if grid else "false"
    if st["gtk"].get("gtk-3.0") is not None:
        add("system", "gtk-3.0/settings.ini gtk-hint-font-metrics does nothing: GTK3 has "
                      "no such setting (Pango rounds GTK3 glyph positions to whole pixels anyway)")
    if not manual:
        if grid:
            how = ("" if _on(cfg["hint"]) else
                   " (gsettings set org.gnome.desktop.interface font-rendering manual)")
            add("system", f"GTK4 font-rendering is {rendering}: it ignores gtk-hint-font-metrics "
                          f"and keeps positions fractional. The grid needs manual{how} and "
                          "gtk-4.0/settings.ini gtk-hint-font-metrics=true")
        else:
            add("system", f"GTK4 font-rendering is {rendering}: hint metrics are off whatever "
                          "settings.ini says, which is what you want")
    for name, cur in st["gtk"].items():
        have = cur or "unset"
        if name == "gtk-3.0" or not manual:
            continue
        if cur != want_metrics:
            add("system", f"{name}/settings.ini gtk-hint-font-metrics: now {have}, set "
                          f"{want_metrics} (import-gsettings.sh does it)")
        else:
            add("system", f"{name}/settings.ini gtk-hint-font-metrics = {cur}: already right")
    ffs = st["firefox"]
    for prof, v in ffs.items():
        dis, en = v.get("disabled"), v.get("enabled")
        # Measured: spacing looks better with force-enabled, also with
        # gtk-hint-font-metrics=true (pixel grid), so Firefox is the same in both.
        if dis == "true":
            add("browser", f"Firefox [{prof}]: gfx.text.subpixel-position.force-disabled = true "
                           "works against the spacing: remove it (false) and set force-enabled = true")
        elif en == "true":
            add("browser", f"Firefox [{prof}]: force-enabled = true already set: keep it")
        else:
            add("browser", f"Firefox [{prof}]: set gfx.text.subpixel-position.force-enabled = true "
                           f"(now unset: Firefox decides from the hint style)")
    flagged = st["chromium_flag_files"]
    if grid and not flagged:
        add("browser", f"Chromium/Brave/Helium/Electron: add {CHROMIUM_FLAG} to their *-flags.conf")
    elif grid:
        add("browser", f"Chromium-family: {CHROMIUM_FLAG} is already in {len(flagged)} flag files")
    elif flagged:
        add("browser", f"Chromium-family: remove {CHROMIUM_FLAG} (default: off) from "
                       f"{len(flagged)} flag files: {_names(flagged)}")
    if _on(cfg["even_spacing"]):
        add("browser", "even spacing only shows with subpixel positioning on, hence the above")
    t = str(cfg["trak"])
    if t == "stat":
        add("browser", "trak kept with STAT: HarfBuzz apps apply it at the requested size; "
                       "Firefox's own trak path is bypassed")
    elif t == "" and has_trak:
        add("browser", "trak untouched: Firefox applies it about 5x too strongly, "
                       "other programs differ; strip or stat makes them agree")
    if _on(cfg["features"]):
        add("system", "the features are in the fonts now: fontfeatures entries for them in "
                      "~/.config/fontconfig/fonts.conf are redundant (harmless)")
        add("browser", "Chromium ignores fontconfig fontfeatures; baked features work there")
    if cfg.get("alts"):
        add("system", "the aalt alternates become cvXX features, off by default: the build "
                      "prints which cvXX is which character; turn them on in a fontfeatures "
                      "block of fonts.conf (or bake them with features=fonts.conf)")
    if cfg["feature_suffix"]:
        add("system", f"families are renamed with '{cfg['feature_suffix']}': choose "
                      "that name in GNOME Tweaks / settings and per-app font settings")
    # Measured on 2.15 (Noto Sans): with a strong/quantized stem mode for
    # DirectWrite (3rd letter q/s), sized/gridfit change 23-55% of pixels up to
    # ~20 px; with natural stems (n) nothing. The x-height setting plays no part.
    hinted = cfg["hint"] in PRESETS
    mode = (cfg.get("hint_mode") if str(cfg.get("hint_mode", "auto")) != "auto"
            else PRESETS[cfg["hint"]][0] if hinted else "")
    if cfg["gasp"] in ("sized", "gridfit") and hinted and hs in ("medium", "full"):
        if mode[-1:] != "n":
            add("system", f"gasp '{cfg['gasp']}' lacks symmetric smoothing: FreeType 2.15 runs the "
                          "static fonts' bytecode differently from ttfautohint's own gasp up to "
                          "about 20 px; 'smooth' or 'keep' leaves them as hinted")
        else:
            add("system", f"gasp '{cfg['gasp']}': with natural stems ({mode}) FreeType 2.15 "
                          "rendered Noto Sans the same as ttfautohint's own gasp")
    elif cfg["gasp"] not in ("keep", ""):
        add("system", "gasp only matters to FreeType when the bytecode runs (hintmedium/full); "
                      "otherwise it is for Windows/Wine and validators")
    add("system", "after installing: fc-cache -f, then restart the apps (and log out for GTK)")
    return out


def render(cfg, hs=None, has_trak=True, state=None):
    hs = hintstyle() if hs is None else hs
    lines = ["", "══ fonttune: your choices ══", *summary(cfg),
             f"  {'desktop hint style':22} {hs or 'unknown'}", "", "══ what to set around the fonts ══"]
    last = None
    items = sorted(advice(cfg, hs, has_trak, state), key=lambda i: i[0] != "system")
    for where, text in items:
        if where != last:
            lines.append(f" [{where}]")
            last = where
        lines.append(f"  - {text}")
    return "\n".join(lines) + "\n"
