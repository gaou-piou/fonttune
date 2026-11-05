"""Summary of the chosen settings, plus what to set up around the fonts."""
from .system import auto_ppem, hintstyle

LABELS = [
    ("otf2ttf", "CFF -> TrueType"), ("weights", "usWeightClass fix"), ("trak", "trak table"),
    ("even_spacing", "even spacing"), ("pixel_grid", "pixel grid (ppem)"),
    ("hint", "ttfautohint preset"), ("features", "baked features"),
    ("feature_suffix", "family suffix"), ("gasp", "gasp table"),
]


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


def advice(cfg, hs=None, has_trak=True):
    """-> list of (where, text). hs: desktop hint style, '' when unknown."""
    hs = hintstyle() if hs is None else hs
    out = []
    add = lambda where, text: out.append((where, text))  # noqa: E731
    if _on(cfg["hint"]):
        if hs in ("slight", "none"):
            add("system", f"hint is on but the desktop uses '{hs}': FreeType ignores the bytecode. "
                          "Enable it for these fonts: sudo ln -s "
                          "/usr/share/fontconfig/conf.avail/80-<package>.conf /etc/fonts/conf.d/ "
                          "(the package ships it when hint is on)")
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
    if _on(cfg["pixel_grid"]):
        p = cfg["pixel_grid"]
        p = f"{auto_ppem():g}" if p == "auto" else p
        add("system", f"pixel grid is tuned for {p} ppem: set the UI font to that size "
                      "(pt = ppem x 0.75), text-scaling-factor 1.0, and no fractional monitor scale")
        add("system", "~/.config/gtk-4.0/settings.ini and gtk-3.0: gtk-hint-font-metrics=true "
                      "so GTK keeps the rounded advances")
        add("browser", "Firefox: user.js gfx.text.subpixel-position.force-disabled = true "
                       "(otherwise it positions glyphs at fractions and undoes the grid)")
        add("browser", "Chromium/Brave/Helium: --disable-font-subpixel-positioning")
    if _on(cfg["even_spacing"]):
        add("browser", "even spacing needs subpixel positioning: leave Firefox/Chromium "
                       "at their defaults (do not apply the pixel-grid tweaks)")
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
    if cfg["feature_suffix"]:
        add("system", f"families are renamed with '{cfg['feature_suffix']}': choose "
                      "that name in GNOME Tweaks / settings and per-app font settings")
    if cfg["gasp"] not in ("keep", ""):
        add("system", "gasp is read by Windows/Wine only; FreeType ignores it")
    add("system", "after installing: fc-cache -f, then restart the apps (and log out for GTK)")
    return out


def render(cfg, hs=None, has_trak=True):
    hs = hintstyle() if hs is None else hs
    lines = ["", "══ fonttune: your choices ══", *summary(cfg),
             f"  {'desktop hint style':22} {hs or 'unknown'}", "", "══ what to set around the fonts ══"]
    last = None
    items = sorted(advice(cfg, hs, has_trak), key=lambda i: i[0] != "system")
    for where, text in items:
        if where != last:
            lines.append(f" [{where}]")
            last = where
        lines.append(f"  - {text}")
    return "\n".join(lines) + "\n"
