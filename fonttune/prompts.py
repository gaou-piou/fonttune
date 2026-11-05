"""Interactive questions. Every prompt is tagged with the config key it sets,
so the menu text can be tied back to flags, profiles and config.toml."""
import sys

from .system import auto_ppem, hintstyle


def _read(prompt):
    try:
        return input(prompt).strip()
    except EOFError:
        sys.exit("\nfonttune: no input (stdin closed); pass flags or --profile instead")


def choice(key, title, options, default):
    """options: list of (value, description). Returns the chosen value."""
    print(f"\n[{key}] {title}")
    for i, (v, d) in enumerate(options, 1):
        mark = " (default)" if v == default else ""
        print(f"  {i}) {v or '-'}: {d}{mark}")
    while True:
        a = _read("> ")
        if not a:
            return default
        if a.isdigit() and 1 <= int(a) <= len(options):
            return options[int(a) - 1][0]
        if a in [v for v, _ in options]:
            return a
        print("  pick a number or a name from the list")


def yesno(key, title, default):
    print(f"\n[{key}] {title} [{'Y/n' if default else 'y/N'}]")
    while True:
        a = _read("> ").lower()
        if not a:
            return default
        if a in ("y", "yes"):
            return True
        if a in ("n", "no"):
            return False


def number(key, title):
    while True:
        a = _read(f"[{key}] {title}: ")
        try:
            if float(a) > 0:
                return a
        except ValueError:
            pass
        print("  type a positive number")


def ask_config(cfg, facts, skip=()):
    """facts: what the input fonts allow ({'trak', 'gridable', 'hintable', 'variable'}: bool).
    skip: keys already decided by flags or environment; they are not asked."""
    cfg = dict(cfg)
    ask = lambda k: k not in skip  # noqa: E731
    skipped = lambda k, why: print(f"\n[{k}] skipped: {why}")  # noqa: E731
    if not facts.get("cff", True) and ask("otf2ttf"):
        skipped("otf2ttf", "the fonts are already TrueType")
    elif ask("otf2ttf"):
        cfg["otf2ttf"] = yesno("otf2ttf", "Convert CFF/OTF outlines to TrueType "
                               "(FreeType autohints TrueType under hintslight)", cfg["otf2ttf"])
    if not facts.get("weights", True) and ask("weights"):
        skipped("weights", "variable fonts take their weight from the wght axis"
                if facts.get("variable") else "every usWeightClass already matches its style name")
        cfg["weights"] = False
    elif ask("weights"):
        cfg["weights"] = yesno("weights", "Normalise usWeightClass: some styles carry the wrong "
                               "weight number, so fontconfig picks the wrong face", cfg["weights"])
    if not facts["trak"] and ask("trak"):
        skipped("trak", "no Apple trak table in these fonts")
    if facts["trak"] and ask("trak"):
        opts = [("", "leave the table (Firefox applies it ~5x too strongly)"),
                ("strip", "remove it: all programs agree, text ~10% tighter"),
                ("stat", "keep it and add STAT so HarfBuzz applies it"),
                ("custom", "remove it and bake the tracking in at a point size")]
        cur = cfg["trak"] or ""
        if cur not in [v for v, _ in opts]:
            opts.insert(2, (cur, f"remove it and bake the tracking in at {cur} pt"))
        cfg["trak"] = choice("trak", "Apple tracking (trak) table", opts, cur)
        if cfg["trak"] == "custom":
            cfg["trak"] = number("trak", "point size")
    if facts.get("variable") and ask("pixel_grid"):
        print("\n[pixel_grid] skipped: needs static fonts and the input is variable "
              "(choose the static variant to get the pixel grid)")
        cfg["pixel_grid"] = ""  # a profile default would only hide even_spacing
    if cfg["even_spacing"] and "even_spacing" in skip and ask("pixel_grid"):
        print("\n[pixel_grid] skipped: even_spacing is set and the two exclude each other")
    elif facts["gridable"] and ask("pixel_grid"):
        cur = str(cfg["pixel_grid"] or "off")
        g = choice("pixel_grid", "Put advances and kerning on a pixel grid at one size (ppem). "
                   "Excludes even_spacing: choosing a size here skips that question", [
            ("off", "no"),
            ("auto", f"from the GNOME interface font size ({auto_ppem():g} ppem now)"),
            ("16", "16 ppem"), ("14", "14 ppem"), ("13", "13 ppem"),
            ("custom", "type a size in ppem")], cur)
        cfg["pixel_grid"] = {"off": ""}.get(g, g)
        if g == "custom":
            cfg["pixel_grid"] = number("pixel_grid", "ppem")
    if cfg["pixel_grid"] and ask("even_spacing"):
        print("\n[even_spacing] skipped: the pixel grid is on and would round its small kerns "
              "to zero (answer 'no' to pixel_grid to get even spacing)")
        cfg["even_spacing"] = ""
    elif ask("even_spacing"):
        cfg["even_spacing"] = choice("even_spacing", "Even out letter-pair spacing (class kerning)", [
            ("", "no"), ("all", "latin, greek, cyrillic"), ("latin", "latin only"),
            ("greek", "greek only")], cfg["even_spacing"] or "")
    if facts.get("hintable", facts["gridable"]) and ask("hint"):
        hs = hintstyle()
        weak = hs in ("slight", "none")
        if weak:
            print(f"  note: the desktop uses hint style '{hs}': FreeType then ignores the "
                  "ttfautohint bytecode and the hints make no difference.")
        cur = cfg["hint"] or ("" if weak else "balanced")
        cfg["hint"] = choice("hint", "ttfautohint bytecode hints (`fonttune hintconf` "
                             "enables them per family)", [
            ("", "no" + (" (recommended with this hint style)" if weak else "")),
            ("balanced", "balanced: stem q, 8-50 px, x-height 14 (upstream defaults)"),
            ("sharp", "sharp: stem s, 6-50 px (max contrast, low DPI)"),
            ("natural", "natural: stem n, no x-height bump (least distortion)"),
            ("light", "light: stem n, from 12 px (HiDPI)")], cur)
    if ask("features"):
        f = choice("features", "Bake OpenType features into calt (every program applies them)", [
            ("", "none: leave the fonts as shipped"),
            ("fonts.conf", "the features active in ~/.config/fontconfig/fonts.conf"),
            ("custom", "type the tags yourself")], cfg["features"] if cfg["features"] == "fonts.conf" else "")
        if f == "custom":
            f = _read("[features] tags, comma separated (e.g. ss06,cv07,case): ").replace(" ", ",")
        cfg["features"] = f
    if cfg["features"] and ask("feature_suffix"):
        cfg["feature_suffix"] = choice("feature_suffix", "Also rename the families so the stock "
                                       "look stays available", [
            ("", "no, change the fonts in place"), (" Alt", "yes, suffix ' Alt'")],
            cfg["feature_suffix"])
    if ask("gasp"):
        cfg["gasp"] = choice("gasp", "gasp table", [
            ("keep", "leave as is"), ("smooth", "anti-alias at all sizes"),
            ("sized", "size-based"), ("gridfit", "grid-fit at all sizes")], cfg["gasp"])
    return cfg


def confirm(text):
    """Show the summary and wait for continue (default) or abort."""
    print(text)
    print("Press Enter to continue with the tuning, or type n to abort.")
    return _read("> ").lower() not in ("n", "no", "q", "abort")
