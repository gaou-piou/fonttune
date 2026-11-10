"""Interactive questions. Every prompt is tagged with the config key it sets,
so the menu text can be tied back to flags, profiles and config.toml."""
import sys
import textwrap

from .system import auto_ppem, auto_pt, hintstyle


def _read(prompt):
    try:
        return input(prompt).strip()
    except EOFError:
        sys.exit("\nfonttune: no input (stdin closed); pass flags or --profile instead")


WIDTH = 78


def _header(key, title, suffix=""):
    """Print '[key] first line', then each further paragraph of title (separated
    by a blank line) wrapped and indented: the explanation under the question."""
    head, *paras = title.split("\n\n")
    print(f"\n[{key}] {head}{suffix}")
    for p in paras:
        print(textwrap.fill(p, WIDTH, initial_indent="    ", subsequent_indent="    "))


def choice(key, title, options, default):
    """options: list of (value, description). Returns the chosen value."""
    _header(key, title)
    for i, (v, d) in enumerate(options, 1):
        mark = " (default)" if v == default else ""
        print(textwrap.fill(f"{i}) {v or '-'}: {d}{mark}", WIDTH,
                            initial_indent="  ", subsequent_indent="       "))
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
    _header(key, title, f" [{'Y/n' if default else 'y/N'}]")
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
        cfg["otf2ttf"] = yesno("otf2ttf", (
            "Convert the CFF (PostScript) outlines to TrueType?"
            "\n\nThe cubic curves are re-drawn as quadratic ones (at most 1 font unit off, "
            "invisible). What changes is how Linux renders them: under hintslight FreeType "
            "sends CFF fonts through Adobe's CFF hinter and TrueType fonts through its light "
            "autohinter, the one most of the desktop's fonts already use, so converted fonts "
            "match the rest of the UI in weight and sharpness."
            "\n\nThe hint and pixel_grid steps need TrueType: say no here and they are "
            "skipped. Cost: slightly bigger files."), cfg["otf2ttf"])
    if not facts.get("weights", True) and ask("weights"):
        skipped("weights", "variable fonts take their weight from the wght axis"
                if facts.get("variable") else "every usWeightClass already matches its style name")
        cfg["weights"] = False
    elif ask("weights"):
        cfg["weights"] = yesno("weights", (
            "Fix the weight numbers (OS/2 usWeightClass)?"
            "\n\nSome styles carry the wrong number: Apple's New York ships Bold and "
            "Semibold both as 600 and Heavy and Black both as 800, so fontconfig cannot tell "
            "them apart and a plain 'bold' request (700) gets Black. This rewrites only the "
            "number to the standard scale (Bold 700, Black 900); outlines and names are "
            "untouched. Safe: say yes unless you want the shipped numbers."), cfg["weights"])
    if not facts["trak"] and ask("trak"):
        skipped("trak", "no Apple trak table in these fonts")
    if facts["trak"] and ask("trak"):
        opts = [("", "leave the table. GTK and Chromium apply Apple's size-dependent "
                     "spacing (looser small text, as on macOS), but Firefox applies it about "
                     "5x too strongly: body text there gets ~20% wider and looks spaced out"),
                ("strip", "remove it. Every program shows the plain design widths and agrees "
                          "within 1%, but text is ~10% tighter than GTK showed it; small text "
                          "can look cramped"),
                ("stat", "keep it and add a STAT table, so HarfBuzz (GTK, Chromium) applies "
                         "it per size like macOS (+4% at 9 pt, -4% at 17 pt); Firefox still "
                         "over-applies it"),
                ("auto", f"remove it and add the spacing it asks for at the GNOME interface "
                         f"font size ({auto_pt():g} pt now) to every glyph. Same in every "
                         f"program and right at the size you read most; headings come out a "
                         f"little looser than Apple would set them. Follows the desktop "
                         f"setting at build time"),
                ("custom", "like auto, but you type the point size")]
        cur = cfg["trak"] or ""
        if cur not in [v for v, _ in opts]:
            opts.insert(3, (cur, f"like auto, but at {cur} pt (the current setting)"))
        cfg["trak"] = choice("trak", (
            "Apple tracking (trak) table: what to do with Apple's letter-spacing?"
            "\n\nApple fonts carry a table of extra letter-spacing per point size (looser "
            "when small, tighter when large). macOS applies it; on Linux every program "
            "treats it differently, so the same text has a different width in GTK, Chromium "
            "and Firefox."), opts, cur)
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
        g = choice("pixel_grid", (
            "Put letter widths and kerning on whole pixels at one size?"
            "\n\nNormally each letter starts at a fraction of a pixel, so the same stem "
            "renders as one dark column in one letter and two grey ones in the next, and a "
            "word looks unevenly weighted. This rounds every advance width and kerning value "
            "to whole pixels at the chosen size (ppem = pixels per em), so identical letters "
            "render identically. Exact at that size and its multiples (200% display scaling "
            "keeps it), unchanged-looking elsewhere."
            "\n\nCost: each gap moves up to half a pixel from the design, and kerns smaller "
            "than half a pixel disappear. Choosing a size skips even_spacing (the two "
            "exclude each other)."), [
            ("off", "no, keep the design's fractional spacing"),
            ("auto", f"the size GNOME renders interface text at, taken from the font setting "
                     f"and text scaling at build time ({auto_ppem():g} ppem now)"),
            ("16", "16 ppem (12 pt at 96 dpi)"), ("14", "14 ppem (10.5 pt)"),
            ("13", "13 ppem (10 pt)"),
            ("custom", "type a size in ppem")], cur)
        cfg["pixel_grid"] = {"off": ""}.get(g, g)
        if g == "custom":
            cfg["pixel_grid"] = number("pixel_grid", "ppem")
    if cfg["pixel_grid"] and ask("even_spacing"):
        print("\n[even_spacing] skipped: the pixel grid is on and would round its small kerns "
              "to zero (answer 'no' to pixel_grid to get even spacing)")
        cfg["even_spacing"] = ""
    elif ask("even_spacing"):
        cfg["even_spacing"] = choice("even_spacing", (
            "Even out the spacing between letter pairs?"
            "\n\nMeasures the white area between every pair of lowercase (and of capital) "
            "letters and adds kerning that moves each pair towards the typical gap, so words "
            "read with an even rhythm (e.g. 'rn', 'ry', Greek pairs that Latin-first fonts "
            "never kerned). The strength is calibrated on the pairs the designer kerned by "
            "hand; pairs the font already kerns are left alone, accented letters follow their "
            "base letter, and no correction exceeds about 1 pixel at body size."
            "\n\nMost useful on fonts with sparse kerning; on a well-kerned font the change "
            "is small."), [
            ("", "no, keep the font's own spacing"), ("all", "Latin, Greek and Cyrillic"),
            ("latin", "Latin only"), ("greek", "Greek only")], cfg["even_spacing"] or "")
    if facts.get("variable") and not facts.get("hintable", True) and ask("hint"):
        skipped("hint", "ttfautohint hints a variable font only at its default instance and "
                "distorts the other weights once bytecode is on (choose the static variant)")
        cfg["hint"] = ""
    elif facts.get("hintable", facts["gridable"]) and ask("hint"):
        hs = hintstyle()
        weak = hs in ("slight", "none")
        if weak:
            print(f"  note: the desktop uses hint style '{hs}': FreeType then ignores the "
                  "ttfautohint bytecode and the hints make no difference.")
        cur = cfg["hint"] or ("" if weak else "balanced")
        cfg["hint"] = choice("hint", (
            "Add ttfautohint hinting instructions?"
            "\n\nHints snap heights (baseline, x-height, cap height) and horizontal strokes "
            "to whole pixels: sharper, darker text at small sizes, at the price of slightly "
            "changed proportions. FreeType runs them only at hintmedium/hintfull; at "
            "hintslight (the GNOME default) it uses its own autohinter and the hints do "
            "nothing. `fonttune hintconf` writes a fontconfig file that switches just these "
            "families to hintmedium (Chromium and Electron excluded)."
            "\n\nOnly the y direction is hinted on Linux, so the presets differ in how hard "
            "horizontal strokes are snapped and from which size."), [
            ("", "no hints" + (" (recommended with this hint style)" if weak else "")),
            ("balanced", "strokes rounded to whole pixels where that keeps their ratio, "
                         "hinted from 8 to 50 px, x-height rounded up below 14 px for "
                         "legibility (ttfautohint's defaults)"),
            ("sharp", "every stroke forced to a whole pixel, from 6 px: most contrast, most "
                      "distortion; for low-DPI screens"),
            ("natural", "strokes keep their design thickness and the x-height is not bumped: "
                        "only the heights are aligned. Least distortion, softer"),
            ("light", "like natural but only from 12 px up; smaller text is left unhinted. "
                      "For HiDPI screens")], cur)
    if ask("alts"):
        alts = facts.get("alts", [])
        if alts:
            cfg["alts"] = yesno("alts", (
                f"Make {len(alts)} hidden alternate letters selectable?"
                f"\n\nThese alternates ({' '.join(alts[:12])}{' ...' if len(alts) > 12 else ''}) "
                "are reachable only through 'aalt', a glyph-picker bucket that no program turns "
                "on for text (and that would swap all of them at once). This gives each "
                "character its own cvXX feature. Nothing changes on screen until you turn one "
                "on: fontfeatures in fonts.conf (GTK), font-feature-settings in CSS, or the "
                "features step below (every program)."), True)
        else:
            skipped("alts", "no alternates hidden in aalt")
            cfg["alts"] = False
    if ask("features"):
        f = choice("features", (
            "Make OpenType features (stylistic sets, alternate letters) permanent?"
            "\n\nfontconfig's fontfeatures reach only GTK; Chromium, Electron, Qt, terminals "
            "and LibreOffice ignore them. This copies the chosen features into 'calt', which "
            "every program applies, so e.g. a single-storey a shows up everywhere. "
            "Afterwards a single feature can no longer be switched off on its own (only all "
            "of calt). Features that are wrong for running text (aalt, frac, ordn) are "
            "refused."), [
            ("", "none, leave the fonts as shipped"),
            ("fonts.conf", "the fontfeatures your ~/.config/fontconfig/fonts.conf turns on "
                           "for these families"),
            ("custom", "type the tags yourself")],
            cfg["features"] if cfg["features"] == "fonts.conf" else "")
        if f == "custom":
            f = _read("[features] tags, comma separated (e.g. ss06,cv07,case): ").replace(" ", ",")
        cfg["features"] = f
    if cfg["features"] and ask("feature_suffix"):
        cfg["feature_suffix"] = choice("feature_suffix", (
            "Give the fonts with baked features a new family name?"
            "\n\nWith a suffix the package installs e.g. 'Inter Alt': it can sit next to an "
            "untouched copy of the font, and you pick per program which look you get. Without "
            "it the fonts keep their name and the new forms appear everywhere the family is "
            "used."), [
            ("", "no, keep the family name"), (" Alt", "yes, add the suffix ' Alt'")],
            cfg["feature_suffix"])
    if ask("gasp"):
        cfg["gasp"] = choice("gasp", (
            "gasp table: per-size rendering hints for the rasteriser"
            "\n\nIt tells a renderer at which sizes to grid-fit and to anti-alias. Under "
            "hintslight (and with no hinting) FreeType ignores it. FreeType 2.15 passes its "
            "symmetric-smoothing bit to the bytecode, so with hintmedium/hintfull 'sized' and "
            "'gridfit' (which lack it) change ttfautohint's result below 17 px; 'smooth' "
            "matches what ttfautohint writes. Otherwise it is for Windows and font "
            "validators (fontbakery wants it present)."), [
            ("keep", "leave it as the font (or ttfautohint) wrote it"),
            ("smooth", "smooth and grid-fit at every size: the value Google Fonts uses"),
            ("sized", "Microsoft's old size-based scheme: no anti-aliasing from 9 to 16 px"),
            ("gridfit", "grid-fit and grayscale at every size")], cfg["gasp"])
    return cfg


def confirm(text):
    """Show the summary and wait for continue (default) or abort."""
    print(text)
    print("Press Enter to continue with the tuning, or type n to abort.")
    return _read("> ").lower() not in ("n", "no", "q", "abort")
