"""Interactive questions. Every prompt is tagged with the config key it sets,
so the menu text can be tied back to flags, profiles and config.toml."""
import sys

from .system import auto_ppem


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


def ask_config(cfg, facts):
    """facts: what the input fonts allow ({'trak': bool, 'gridable': bool})."""
    cfg = dict(cfg)
    cfg["otf2ttf"] = yesno("otf2ttf", "Convert CFF/OTF outlines to TrueType "
                           "(FreeType autohints TrueType under hintslight)", cfg["otf2ttf"])
    if facts["trak"]:
        cfg["trak"] = choice("trak", "Apple tracking (trak) table", [
            ("", "keep it"), ("strip", "remove it"),
            ("custom", "bake tracking in at a point size")], cfg["trak"] or "")
        if cfg["trak"] == "custom":
            cfg["trak"] = number("trak", "point size")
    spacing = choice("even_spacing", "Even out letter-pair spacing (class kerning)", [
        ("", "no"), ("all", "latin, greek, cyrillic"), ("latin", "latin only"),
        ("greek", "greek only")], cfg["even_spacing"] or "")
    cfg["even_spacing"] = spacing
    if facts["gridable"] and not spacing:
        g = choice("pixel_grid", "Put advances and kerning on a pixel grid", [
            ("off", "no"),
            ("auto", f"from the GNOME interface font size ({auto_ppem():g} ppem now)"),
            ("16", "16 ppem"), ("14", "14 ppem"), ("13", "13 ppem"),
            ("custom", "type a size in ppem")], cfg["pixel_grid"] or "off")
        cfg["pixel_grid"] = {"off": ""}.get(g, g)
        if g == "custom":
            cfg["pixel_grid"] = number("pixel_grid", "ppem")
    cfg["gasp"] = choice("gasp", "gasp table", [
        ("keep", "leave as is"), ("smooth", "anti-alias at all sizes"),
        ("sized", "size-based"), ("gridfit", "grid-fit at all sizes")], cfg["gasp"])
    return cfg
