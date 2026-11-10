import subprocess
import sys
from pathlib import Path

import pytest

BIN = Path(__file__).resolve().parent.parent / "bin" / "fonttune"


def run(*a, env=None):
    """bin/fonttune without the caller's FONTTUNE_* answers or config directory."""
    import os
    if env is None:
        env = {k: v for k, v in os.environ.items() if not
               (k.startswith("FONTTUNE_") and k not in ("FONTTUNE_DEV", "FONTTUNE_LIBFREETYPE"))}
        env["XDG_CONFIG_HOME"] = _empty_config().name
    return subprocess.run([sys.executable, str(BIN), *a], capture_output=True, text=True, env=env)


_CONFIG = None


def _empty_config():
    """One empty config directory for the session (no saved fonttune settings)."""
    global _CONFIG
    if _CONFIG is None:
        import tempfile
        _CONFIG = tempfile.TemporaryDirectory(prefix="fonttune-test-config-")
    return _CONFIG


def desktop(tmp_path, font="Adwaita Sans 11", scale=1.0):
    """Environment whose gsettings reports this interface font and text scale."""
    import os
    d = tmp_path / "gsettings-bin"
    d.mkdir(exist_ok=True)
    gs = d / "gsettings"
    gs.write_text(f"#!/bin/sh\ncase \"$3\" in font-name) echo \"'{font}'\";; "
                  f"text-scaling-factor) echo {scale};; esac\n")
    gs.chmod(0o755)
    return {**os.environ, "PATH": str(d)}


def test_steps_listed():
    r = run("steps")
    assert r.returncode == 0 and "pixel_grid" in r.stdout


def test_grid_and_spacing_exclusive():
    r = run("run", "--pixel-grid", "14", "--even-spacing", "all", "--dry-run",
            "-o", "/tmp/ft_unused", str(BIN))
    assert r.returncode != 0 and "mutually exclusive" in r.stderr


def test_dry_run_plan():
    r = run("run", "--profile", "clean", "--dry-run", "-o", "/tmp/ft_unused", str(BIN))
    assert r.returncode == 0 and "otf2ttf" in r.stdout and "alts" in r.stdout


def test_config_saved_and_reused(tmp_path):
    import os
    env = {**os.environ, "XDG_CONFIG_HOME": str(tmp_path)}
    r = subprocess.run([sys.executable, str(BIN), "run", "--gasp", "sized", "--save",
                        "--dry-run", "-o", str(tmp_path / "o"), str(BIN)],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0
    assert 'gasp = "sized"' in (tmp_path / "fonttune" / "config.toml").read_text()
    r = subprocess.run([sys.executable, str(BIN), "run", "--dry-run", "-o", str(tmp_path / "o"),
                        str(BIN)], capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)
    assert "gasp" in r.stdout


def test_only_skip_and_unknown_step():
    r = run("run", "--profile", "clean", "--dry-run", "--in-place", "--skip", "alts", str(BIN))
    assert r.returncode == 0 and "alts" not in r.stdout
    r = run("run", "--dry-run", "--in-place", "--only", "nope", str(BIN))
    assert r.returncode != 0 and "unknown step" in r.stderr


def test_configure_writes_file_and_env_layer(tmp_path):
    import os
    out = tmp_path / "c.toml"
    env = {**os.environ, "FONTTUNE_OTF2TTF": "true", "FONTTUNE_TRAK": "13"}
    r = subprocess.run([sys.executable, str(BIN), "configure", "--no-config", "--save-to", str(out),
                        str(BIN)], capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)
    assert r.returncode == 0
    t = out.read_text()
    assert "otf2ttf = true" in t and 'trak = "13"' in t


def test_trak_auto_resolves_to_ui_font_size(tmp_path):
    from fontTools.ttLib import TTFont
    src = next(iter(sorted(Path("/usr/share/fonts").rglob("SF-Pro-Rounded-*.ttf"))), None)
    if not src or "trak" not in TTFont(src, lazy=True):
        import pytest
        pytest.skip("needs a font with a trak table")
    sys.path.insert(0, str(BIN.parent.parent))
    from fonttune import system
    r = run("run", "--trak", "auto", "-o", str(tmp_path / "o"), str(src))
    assert r.returncode == 0, r.stderr
    assert f"trak auto -> bake at {system.auto_pt():g} pt" in r.stdout
    assert "trak" not in TTFont(tmp_path / "o" / src.name)


def test_hint_plan_and_validation():
    r = run("run", "--hint", "balanced", "--dry-run", "-o", "/tmp/ft_unused", str(BIN))
    assert r.returncode == 0 and "hint" in r.stdout
    r = run("run", "--hint", "bogus", "--dry-run", "-o", "/tmp/ft_unused", str(BIN))
    assert r.returncode != 0 and "unknown hint preset" in r.stderr
    r = run("run", "--hint", "light", "--hint-mode", "xyz", "--dry-run", "-o", "/tmp/ft_unused", str(BIN))
    assert r.returncode != 0 and "hint_mode" in r.stderr


def test_hint_runs_and_hintconf(tmp_path):
    import shutil
    from fontTools.ttLib import TTFont
    src = next(iter(sorted(Path("/usr/share/fonts").rglob("*.ttf"))), None)
    if not src or not shutil.which("ttfautohint"):
        import pytest
        pytest.skip("needs a system TTF and ttfautohint")
    out = tmp_path / "o"
    r = run("run", "--hint", "light", "-o", str(out), str(src))
    assert r.returncode == 0, r.stderr
    assert "fpgm" in TTFont(out / src.name)
    c = tmp_path / "80.conf"
    r = run("hintconf", "-o", str(c), str(out / src.name))
    assert r.returncode == 0 and 'name="hintstyle"' in c.read_text()


def test_advice_text():
    sys.path.insert(0, str(BIN.parent.parent))
    from fonttune import advice, cli
    st = {"firefox": {"mozilla/x.default": {"enabled": "true"}},
          "chromium_flag_files": ["brave-flags.conf"], "gtk": {"gtk-4.0": "false"},
          "rendering": "manual"}
    cfg = dict(cli.DEFAULTS, pixel_grid="14", hint="balanced")
    txt = advice.render(cfg, hs="slight", state=st)
    assert "force-enabled = true already set" in txt and "ignores the bytecode" in txt
    assert "now false, set true" in txt and "add --disable-font-subpixel-positioning" not in txt
    cfg = dict(cli.DEFAULTS, even_spacing="all")
    txt = advice.render(cfg, hs="slight", state=st)
    assert "remove --disable-font-subpixel-positioning" in txt and "already right" in txt
    assert "keep it" in txt
    assert "hint style is" in advice.render(dict(cli.DEFAULTS), hs="medium", state=st)
    # GTK4 under font-rendering=automatic ignores the key; GTK3 has no such key
    auto = dict(st, rendering="automatic", gtk={"gtk-4.0": "true", "gtk-3.0": "true"})
    txt = advice.render(dict(cli.DEFAULTS, pixel_grid="16"), hs="slight", state=auto)
    assert "ignores gtk-hint-font-metrics" in txt and "GTK3 has no such setting" in txt
    assert "now true" not in txt and "already right" not in txt
    txt = advice.render(dict(cli.DEFAULTS), hs="slight", state=auto)
    assert "which is what you want" in txt
    # switching to manual for the bytecode: say what GTK4's metrics default does then
    txt = advice.render(dict(cli.DEFAULTS, hint="balanced"), hs="full", state=dict(auto, gtk={}))
    assert "font-hinting full; GTK4 then hints the metrics" in txt
    assert "[Settings] gtk-hint-font-metrics=false" in txt
    txt = advice.render(dict(cli.DEFAULTS, hint="balanced", pixel_grid="16"), hs="slight",
                        state=dict(auto, gtk={}))
    assert "font-hinting medium" in txt and "then hints the metrics" not in txt
    txt = advice.render(dict(cli.DEFAULTS, hint="balanced"), hs="medium",
                        state=dict(st, rendering="manual"))
    assert "GTK4 runs the bytecode" in txt and "hard-codes" not in txt
    txt = advice.render(dict(cli.DEFAULTS, hint="balanced", gasp="sized"), hs="full", state=st)
    assert "lacks symmetric smoothing" in txt
    txt = advice.render(dict(cli.DEFAULTS, hint="natural", gasp="sized"), hs="full", state=st)
    assert "lacks symmetric smoothing" not in txt and "stem mode nnn" in txt
    txt = advice.render(dict(cli.DEFAULTS, hint="sharp", gasp="sized"), hs="full", state=st)
    assert "lacks symmetric smoothing" not in txt and "stem mode sss" in txt
    txt = advice.render(dict(cli.DEFAULTS, hint="natural", hint_mode="qsq", gasp="sized"), hs="full", state=st)
    assert "lacks symmetric smoothing" in txt
    txt = advice.render(dict(cli.DEFAULTS, hint="balanced", hint_mode="qsn", gasp="sized"), hs="full", state=st)
    assert "lacks symmetric smoothing" in txt                    # measured: 23-46% of pixels
    txt = advice.render(dict(cli.DEFAULTS, hint="", gasp="sized"), hs="full", state=st)
    assert "lacks symmetric smoothing" not in txt and "gasp only matters" in txt
    txt = advice.render(dict(cli.DEFAULTS, gasp="smooth"), hs="slight", state=st)
    assert "only matters to FreeType when the bytecode runs" in txt
    # unknown rendering = GTK's default, automatic; the warning needs no settings.ini
    txt = advice.render(dict(cli.DEFAULTS, pixel_grid="16"), hs="slight",
                        state=dict(st, rendering="", gtk={}))
    assert "font-rendering is automatic" in txt and "already right" not in txt
    txt = advice.render(dict(cli.DEFAULTS, pixel_grid="16", hint="balanced"), hs="slight",
                        state=dict(auto, gtk={}))
    assert txt.count("font-rendering manual") == 1
    # manual rendering without gtk-4.0/settings.ini: GTK4's default is true
    txt = advice.render(dict(cli.DEFAULTS), hs="slight", state=dict(st, gtk={}))
    assert "does not exist" in txt and "gtk-hint-font-metrics=false" in txt
    txt = advice.render(dict(cli.DEFAULTS, pixel_grid="16"), hs="slight", state=dict(st, gtk={}))
    assert "does not exist" not in txt and "default (true) is already right" in txt
    txt = advice.render(dict(cli.DEFAULTS), hs="slight", state=dict(st, gtk={"gtk-4.0": None}))
    assert "now unset (true), set false" in txt
    txt = advice.render(dict(cli.DEFAULTS, pixel_grid="16"), hs="slight",
                        state=dict(st, gtk={"gtk-4.0": None}))
    assert "unset (true): already right" in txt


def test_probe_reads_gtk4_rendering(tmp_path, monkeypatch):
    sys.path.insert(0, str(BIN.parent.parent))
    from fonttune import advice
    d = tmp_path / ".config" / "gtk-4.0"
    d.mkdir(parents=True)
    (d / "settings.ini").write_text("[Settings]\ngtk-font-rendering=manual\n")
    monkeypatch.setattr(advice, "_gsettings", lambda k: "")
    assert advice.probe(tmp_path)["rendering"] == "manual"
    (d / "settings.ini").write_text("[Settings]\n")
    assert advice.probe(tmp_path)["rendering"] == "automatic"


def test_statics_help_and_fit_weight_dispatch():
    assert "--regular-wght" in run("statics", "--help").stdout
    assert "--ppem" in run("fit-weight", "--help").stdout


def test_statics_remove_overlaps(tmp_path):
    """Statics must not carry OVERLAP_SIMPLE flags: FreeType oversamples those glyphs."""
    import pytest
    from fontTools.ttLib import TTFont
    vf = Path("/usr/share/fonts/Adwaita/AdwaitaSans-Regular.ttf")
    if not vf.exists():
        pytest.skip("needs a variable TTF")
    r = run("statics", "-o", str(tmp_path), "--family", "T", "--weights", "400", str(vf))
    assert r.returncode == 0, r.stderr
    out = TTFont(next(tmp_path.glob("*.ttf")))
    glyf = out["glyf"]
    assert not any(glyf[n].numberOfContours > 0 and glyf[n].flags[0] & 0x40
                   for n in out.getGlyphOrder())


def test_variable_fonts_skip_hint_and_grid(monkeypatch, capsys):
    sys.path.insert(0, str(BIN.parent.parent))
    from fonttune import prompts
    asked = []
    monkeypatch.setattr(prompts, "choice", lambda k, *a: asked.append(k) or a[-1])
    monkeypatch.setattr(prompts, "yesno", lambda k, *a: asked.append(k) or a[-1])
    monkeypatch.setattr(prompts, "hintstyle", lambda: "full")
    from fonttune.cli import DEFAULTS
    vf = {"trak": False, "gridable": False, "hintable": False, "variable": True}
    cfg = prompts.ask_config({**DEFAULTS, "hint": "natural"}, vf)
    assert "hint" not in asked and "pixel_grid" not in asked and cfg["hint"] == ""
    out = capsys.readouterr().out
    assert "[pixel_grid] skipped" in out and "[hint] skipped" in out
    asked.clear()
    prompts.ask_config(DEFAULTS, {**vf, "gridable": True, "hintable": True, "variable": False})
    assert "hint" in asked and "pixel_grid" in asked


def test_dev_toggle(tmp_path):
    import os
    env = {**os.environ, "XDG_CONFIG_HOME": str(tmp_path)}
    r = lambda *a: subprocess.run([sys.executable, str(BIN), "dev", *a], capture_output=True,  # noqa: E731
                                  text=True, env=env)
    assert r().stdout.startswith("no local tree")
    assert r("set").stdout.startswith("local tree:")
    assert (tmp_path / "fonttune" / "dev").read_text().strip() == str(BIN.parent.parent)
    assert r("unset").stdout.startswith("no local tree") and not (tmp_path / "fonttune" / "dev").exists()
    assert r("on").stdout.startswith("local tree:")  # the old names still work
    assert r("off").stdout.startswith("no local tree")
    assert r("set", str(tmp_path)).returncode != 0  # not a fonttune tree
    assert r("set", str(BIN.parent.parent)).stdout.startswith("local tree:")


def test_pixel_grid_asked_before_even_spacing(monkeypatch, capsys):
    sys.path.insert(0, str(BIN.parent.parent))
    from fonttune import prompts
    from fonttune.cli import DEFAULTS
    answers = {"pixel_grid": "14", "even_spacing": "all"}
    asked = []
    monkeypatch.setattr(prompts, "choice", lambda k, *a: asked.append(k) or answers.get(k, a[-1]))
    monkeypatch.setattr(prompts, "yesno", lambda k, *a: a[-1])
    monkeypatch.setattr(prompts, "hintstyle", lambda: "slight")
    static = {"trak": False, "gridable": True, "hintable": True, "variable": False}
    cfg = prompts.ask_config(DEFAULTS, static)
    assert asked.index("pixel_grid") < asked.index("hint") and "even_spacing" not in asked
    assert cfg["pixel_grid"] == "14" and cfg["even_spacing"] == ""
    assert "[even_spacing] skipped" in capsys.readouterr().out
    answers["pixel_grid"], asked[:] = "off", []
    cfg = prompts.ask_config(DEFAULTS, static)
    assert asked.index("pixel_grid") < asked.index("even_spacing") and cfg["even_spacing"] == "all"
    # a profile default must not hide even_spacing on a variable font
    asked[:] = []
    cfg = prompts.ask_config({**DEFAULTS, "pixel_grid": "auto"}, {**static, "gridable": False,
                                                                  "variable": True})
    assert "even_spacing" in asked and cfg["pixel_grid"] == ""


def test_facts_skip_irrelevant_questions(tmp_path, monkeypatch, capsys):
    sys.path.insert(0, str(BIN.parent.parent))
    from fontTools.fontBuilder import FontBuilder
    from fonttune import prompts
    from fonttune.cli import DEFAULTS, facts

    def font(path, style, weight):
        fb = FontBuilder(1000, isTTF=True)
        fb.setupGlyphOrder([".notdef"])
        fb.setupCharacterMap({})
        fb.setupGlyf({".notdef": __import__("fontTools.pens.ttGlyphPen", fromlist=["x"])
                      .TTGlyphPen(None).glyph()})
        fb.setupHorizontalMetrics({".notdef": (500, 0)})
        fb.setupHorizontalHeader()
        fb.setupNameTable({"familyName": "T", "styleName": style})
        fb.setupOS2(usWeightClass=weight)
        fb.setupPost()
        fb.save(path)
        return str(path)

    ok = font(tmp_path / "ok.ttf", "Bold", 700)
    bad = font(tmp_path / "bad.ttf", "Bold", 600)
    assert facts([ok])["cff"] is False and facts([ok])["weights"] is False
    assert facts([ok, bad])["weights"] is True
    asked = []
    monkeypatch.setattr(prompts, "choice", lambda k, *a: asked.append(k) or a[-1])
    monkeypatch.setattr(prompts, "yesno", lambda k, *a: asked.append(k) or a[-1])
    monkeypatch.setattr(prompts, "hintstyle", lambda: "slight")
    prompts.ask_config(DEFAULTS, facts([ok]))
    out = capsys.readouterr().out
    assert "otf2ttf" not in asked and "weights" not in asked and "trak" not in asked
    assert "[otf2ttf] skipped" in out and "[weights] skipped" in out and "[trak] skipped" in out
    asked.clear()
    prompts.ask_config(DEFAULTS, facts([ok, bad]))
    assert "weights" in asked


def test_expose_alts(tmp_path, monkeypatch, capsys):
    sys.path.insert(0, str(BIN.parent.parent))
    from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    from fontTools.ttLib import TTFont
    from fonttune import prompts
    from fonttune.cli import DEFAULTS, facts

    names = [".notdef", "a", "aacute", "a.alt", "aacute.alt", "f", "t", "t.alt", "f_t",
             "f_t.alt", "zero", "zero.alt", "zero.cap", "zero.alt.cap", "zero.tf", "b", "b.ss01"]
    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder(names)
    fb.setupCharacterMap({0x61: "a", 0xE1: "aacute", 0x66: "f", 0x74: "t", 0x30: "zero",
                          0x62: "b"})
    fb.setupGlyf({n: TTGlyphPen(None).glyph() for n in names})
    fb.setupHorizontalMetrics({n: (600 if n == "zero.tf" else 500, 0) for n in names})
    fb.setupHorizontalHeader()
    fb.setupNameTable({"familyName": "T", "styleName": "Regular"})
    fb.setupOS2()
    fb.setupPost()
    path = tmp_path / "t.ttf"
    fb.save(str(path))
    font = TTFont(str(path))
    addOpenTypeFeaturesFromString(font, """
        feature aalt { feature ss01; sub a by a.alt; sub aacute by aacute.alt; sub t by t.alt;
            sub f_t by f_t.alt; sub zero by zero.alt; sub zero.cap by zero.alt;
            sub zero.tf by zero.alt; } aalt;
        feature liga { sub f t by f_t; } liga;
        feature case { sub zero by zero.cap; sub zero.alt by zero.alt.cap; } case;
        feature tnum { sub zero by zero.tf; } tnum;
        feature ss01 { sub b by b.ss01; } ss01;
        feature ccmp { sub b.ss01 by f t; } ccmp;
    """)
    font.save(str(path))

    assert facts([str(path)])["alts"] == ["a", "t", "0"]
    r = run("run", "--no-config", "--no-ask", "--alts", "--in-place", "--only", "alts", str(path))
    assert r.returncode == 0, r.stderr
    assert "cv01  a     2 glyph(s)  [aacute]" in r.stdout
    gsub = TTFont(str(path))["GSUB"].table
    subst = {}
    for fr in gsub.FeatureList.FeatureRecord:
        for i in fr.Feature.LookupListIndex:
            for st in gsub.LookupList.Lookup[i].SubTable:
                subst.setdefault(fr.FeatureTag, {}).update(getattr(st, "mapping", {}))
    assert subst["cv01"] == {"a": "a.alt", "aacute": "aacute.alt"}
    assert subst["cv02"] == {"t": "t.alt", "f_t": "f_t.alt"}
    # zero.cap gets the cap alternate; zero.tf is wider than zero.alt, so it is left alone
    assert subst["cv03"] == {"zero": "zero.alt", "zero.cap": "zero.alt.cap"}
    tags = [fr.FeatureTag for fr in gsub.FeatureList.FeatureRecord]
    assert tags == sorted(tags) and "ss01" in tags
    # cv lookups come last, after liga/case made their forms
    assert min(gsub.FeatureList.FeatureRecord[tags.index("cv01")].Feature.LookupListIndex) \
        > max(i for fr in gsub.FeatureList.FeatureRecord if fr.FeatureTag in ("liga", "case")
              for i in fr.Feature.LookupListIndex)

    asked = []
    monkeypatch.setattr(prompts, "choice", lambda k, *a: asked.append(k) or a[-1])
    monkeypatch.setattr(prompts, "yesno", lambda k, *a: asked.append(k) or a[-1])
    monkeypatch.setattr(prompts, "hintstyle", lambda: "slight")
    cfg = prompts.ask_config(DEFAULTS, {"trak": False, "gridable": True, "alts": ["a"]})
    assert "alts" in asked and cfg["alts"] is True
    asked.clear()
    prompts.ask_config(DEFAULTS, {"trak": False, "gridable": True, "alts": []})
    assert "alts" not in asked and "[alts] skipped" in capsys.readouterr().out


def test_darken_curve_hits_target_and_fades_out():
    import pytest
    font = "/usr/share/fonts/Adwaita/AdwaitaSans-Regular.ttf"
    if not Path(font).is_file():
        pytest.skip("needs Adwaita Sans")
    sys.path.insert(0, str(BIN.parent.parent))
    from fonttune import darken
    from fonttune.ftrender import Renderer, system_path
    assert Path(system_path()).is_absolute()
    _, curve, gain = darken.fit(font, 16, 32, 0.025)
    assert darken.check(curve) == ""
    assert 0.01 < gain < 0.04
    [(_, gains, lost)] = darken.report([font], curve, [16, 32])
    assert abs(gains[1]) < 0.005 and lost == []
    assert darken.check([500, 400, 400, 300, 1667, 275, 2333, 0]) == "x must increase"
    assert darken.check([500, 400, 600, 100, 1667, 275, 2333, 0]) == "y must not increase"
    assert darken.check([500, 400, 600, 200, 1667, 100, 2333, 0]) == "a segment is steeper than -1"
    r = Renderer()
    assert r.version() != "" and r.ink(font, 16) > 0


def test_darken_cli(tmp_path):
    import pytest
    font = "/usr/share/fonts/Adwaita/AdwaitaSans-Regular.ttf"
    if not Path(font).is_file():
        pytest.skip("needs Adwaita Sans")
    r = run("darken", "--ppem", "16", "--quiet", font)
    assert r.returncode == 0 and "autofitter:darkening-parameters=" in r.stdout
    junk = tmp_path / "junk.ttf"
    junk.write_bytes(b"not a font")
    bitmap = next(Path("/usr/share/fonts/misc").glob("*.pcf.gz"), None)
    for args in (["--ppem", "nan", font], ["--zero-at", "inf", font], [str(tmp_path / "no.ttf")],
                 ["--quiet", "--ppem", "16", font, str(junk)], ["--ppem", "6000", font],
                 ["--ppem", "0.5", font], *([[str(bitmap)]] if bitmap else [])):
        r = run("darken", *args)
        assert r.returncode == 2 and "error:" in r.stderr and "Traceback" not in r.stderr, args


def test_hintslight_ignores_bytecode_and_gasp(tmp_path, monkeypatch):
    """System FreeType: ttfautohint and gasp change no pixel under hintslight; at full
    the bytecode runs, and on 2.15 gasp 'sized' changes a balanced (qsq) font but
    not a sharp (sss) one."""
    import shutil
    import pytest
    src = Path("/usr/share/fonts/noto/NotoSans-Regular.ttf")
    if not src.is_file() or not shutil.which("ttfautohint"):
        pytest.skip("needs Noto Sans and ttfautohint")
    sys.path.insert(0, str(BIN.parent.parent))
    from fonttune.ftrender import Renderer
    plain, hinted, sized = (tmp_path / n for n in ("plain.ttf", "hinted.ttf", "sized.ttf"))
    subprocess.run(["ttfautohint", "--dehint", str(src), str(plain)], check=True)
    shutil.copy(plain, hinted)
    steps = BIN.parent.parent / "fonttune" / "steps"
    subprocess.run([sys.executable, "-I", str(steps / "hint.py"), "balanced", str(hinted)], check=True)
    shutil.copy(hinted, sized)
    subprocess.run([sys.executable, "-I", str(steps / "set_gasp.py"), "sized", str(sized)], check=True)
    monkeypatch.setenv("FREETYPE_PROPERTIES", "truetype:interpreter-version=40")
    r = Renderer()
    try:
        def bitmaps(f, mode):
            return [d for _, _, _, d in r.glyphs(str(f), 16, mode=mode)]
        assert bitmaps(plain, "slight") == bitmaps(hinted, "slight") == bitmaps(sized, "slight")
        assert bitmaps(plain, "full") != bitmaps(hinted, "full")      # the bytecode does run at full
        if tuple(map(int, r.version().split("."))) < (2, 15):
            pytest.skip(f"FreeType {r.version()}: gasp reaches the bytecode from 2.15 on")
        assert bitmaps(hinted, "full") != bitmaps(sized, "full")
        # ...only when the 2nd and 3rd stem-mode letters differ: sharp (sss) is unchanged
        sharp, sharp_sized = tmp_path / "sharp.ttf", tmp_path / "sharp-sized.ttf"
        shutil.copy(plain, sharp)
        subprocess.run([sys.executable, "-I", str(steps / "hint.py"), "sharp", str(sharp)], check=True)
        shutil.copy(sharp, sharp_sized)
        subprocess.run([sys.executable, "-I", str(steps / "set_gasp.py"), "sized", str(sharp_sized)],
                       check=True)
        assert bitmaps(sharp, "full") == bitmaps(sharp_sized, "full")
    finally:
        r.close()


def test_xheight_snaps_under_hintslight(tmp_path):
    import pytest
    font = "/usr/share/fonts/Adwaita/AdwaitaSans-Regular.ttf"
    if not Path(font).is_file():
        pytest.skip("needs Adwaita Sans")
    sys.path.insert(0, str(BIN.parent.parent))
    from fonttune import xheight
    rows = xheight.table(font, [12, 13.33, 16, 17.33])
    for ppem, exact, hinted, dx, _ in rows:
        assert hinted == round(hinted) and abs(hinted - exact) < 1   # the autofitter rounds it
        assert abs(dx - (hinted / exact - 1)) < 1e-9
    # x-height 1118/2048 em: 8.73 px at 16 ppem -> 9, 7.28 px at 13.33 -> 7
    assert [round(r[1], 2) for r in rows][1:3] == [7.28, 8.73]
    assert [r[2] for r in rows][1:3] == [7.0, 9.0]
    # opsz = pt without text scaling: 30 ppem at scale 1.25 is 18 pt (opsz 14-32 here)
    from fonttune.ftrender import Renderer
    [(_, exact, *_)] = xheight.table(font, [30], scale=1.25)
    with Renderer() as rr:
        at = {o: rr.extent(font, 30, "x", "none", {"opsz": o})[0] for o in (18, 22.5, 30)}
    assert exact == at[18] and len(set(at.values())) == 3
    env = desktop(tmp_path)                                  # scale 1: 12 pt = 16 ppem
    r = run("xheight", "--pt", "11,12", font, env=env)
    assert r.returncode == 0 and "clean sizes:" in r.stdout and "+3.0%" in r.stdout
    for args in (["--pt", "x"], ["--pt", "nan"], ["--pt", "inf"], ["--pt", ""], ["--tolerance", "nan"]):
        r = run("xheight", *args, font, env=env)
        assert r.returncode == 2 and "Traceback" not in r.stderr, args
    junk = tmp_path / "junk.ttf"
    junk.write_bytes(b"not a font")
    r = run("xheight", font, str(junk), env=env)
    assert r.returncode == 2 and "cannot read" in r.stderr and "Traceback" not in r.stderr
    r = run("xheight", "--mode", "full", "--pt", "12", font, env=env)   # Adwaita Sans: no fpgm
    assert r.returncode == 1 and "no bytecode" in r.stdout and "hintmedium" in r.stdout



def test_check_flags_measured_problems(tmp_path):
    """check: overlap flags, hinted VF, gasp without symmetric smoothing; a clean
    static passes. The overlap flag alone must also change the rendering."""
    import shutil
    import pytest
    from fontTools.ttLib import TTFont, newTable
    from fontTools.varLib.instancer import OverlapMode, instantiateVariableFont
    vf = Path("/usr/share/fonts/Adwaita/AdwaitaSans-Regular.ttf")
    if not vf.exists():
        pytest.skip("needs Adwaita Sans")
    sys.path.insert(0, str(BIN.parent.parent))
    from fonttune.check import check
    from fonttune.ftrender import Renderer
    clean, flagged = tmp_path / "clean.ttf", tmp_path / "flagged.ttf"
    instantiateVariableFont(TTFont(vf), {"wght": 400, "opsz": 14},
                            overlap=OverlapMode.REMOVE).save(clean)
    instantiateVariableFont(TTFont(vf), {"wght": 400, "opsz": 14},
                            overlap=OverlapMode.KEEP_AND_SET_FLAGS).save(flagged)
    assert check(str(clean)) == []
    assert [c for c, _ in check(str(flagged))] == ["overlap"]
    # same outlines, only the flag: FreeType's oversampling changes pixels
    only_flag = tmp_path / "onlyflag.ttf"
    f = TTFont(clean)
    for n in f.getGlyphOrder():
        g = f["glyf"][n]
        if not g.isComposite() and g.numberOfContours > 0:
            g.flags[0] |= 0x40
    f.save(only_flag)
    with Renderer() as r:
        a = b"".join(d for *_, d in r.glyphs(str(clean), 16))
        b = b"".join(d for *_, d in r.glyphs(str(only_flag), 16))
    assert len(a) == len(b) and sum(x != y for x, y in zip(a, b)) > 0.2 * len(a)   # measured 35%
    from fonttune.check import overlap_glyphs
    assert [c for c, _ in check(str(only_flag))] == ["overlap"]
    of = TTFont(only_flag)
    composites = [n for n in overlap_glyphs(of) if of["glyf"][n].isComposite()]
    assert composites          # unflagged composites of flagged parts are oversampled too
    # the component flag alone, on one composite: it and composites built on it
    f = TTFont(clean)
    comp = next(n for n in f.getGlyphOrder() if f["glyf"][n].isComposite())
    f["glyf"][comp].components[0].flags |= 0x0400
    assert comp in overlap_glyphs(f) and len(overlap_glyphs(f)) < len(composites)
    # bytecode in a static font is fine; no family name is not
    f = TTFont(clean)
    from fontTools.ttLib.tables import ttProgram
    f["fpgm"] = newTable("fpgm")
    f["fpgm"].program = ttProgram.Program()
    f["fpgm"].program.fromBytecode(b"")
    hinted_static = tmp_path / "hinted-static.ttf"
    f.save(hinted_static)
    assert check(str(hinted_static)) == []
    f["name"].removeNames(nameID=1)
    f["name"].removeNames(nameID=16)
    f.save(hinted_static)
    assert [c for c, _ in check(str(hinted_static))] == ["names"]
    # hinted VF and gasp without symmetric smoothing
    hvf = tmp_path / "hvf.ttf"
    t = TTFont(vf)
    t["prep"] = newTable("prep")
    t["prep"].program = ttProgram.Program()
    t["prep"].program.fromBytecode(b"")
    t["fpgm"] = newTable("fpgm")
    t["fpgm"].program = ttProgram.Program()
    t["fpgm"].program.fromBytecode(b"")
    t["gasp"] = newTable("gasp")
    t["gasp"].version, t["gasp"].gaspRange = 0, {8: 2, 16: 1, 0xFFFF: 3}
    t.save(hvf)
    assert [c for c, _ in check(str(hvf))] == ["vf-hints"]     # gasp: not a ttfautohint font
    t["name"].setName("Version 1.0; ttfautohint (v1.8.4)", 5, 3, 1, 0x409)
    t.save(hvf)
    msg = dict(check(str(hvf)))["gasp"]
    assert "0-8 ppem, 9-16 ppem, 17+ ppem" in msg
    t["gasp"].version, t["gasp"].gaspRange = 1, {20: 0xF, 0xFFFF: 0x3}   # only above 20 px:
    t.save(hvf)                                     # still moves Noto Sans pixels at 21-48 px
    assert "21+ ppem" in dict(check(str(hvf)))["gasp"]
    t["gasp"].gaspRange = {0xFFFF: 0xF}
    t.save(hvf)
    assert "gasp" not in dict(check(str(hvf)))
    # blank typographic family falls back to nameID 1
    t["name"].setName(" ", 16, 3, 1, 0x409)
    t.save(hvf)
    assert "names" not in dict(check(str(hvf)))

    # CLI: exit status and usage errors
    assert run("check", str(clean)).returncode == 0
    r = run("check", str(clean), str(flagged))
    assert r.returncode == 1 and "[overlap]" in r.stdout and "clean.ttf: ok" in r.stdout
    assert run("check", str(tmp_path / "missing.ttf")).returncode == 2
    broken = tmp_path / "broken.ttf"
    broken.write_bytes(b"\0\1\0\0garbage")
    r = run("check", str(broken), str(clean))
    assert r.returncode == 2 and "broken.ttf: cannot read (" in r.stdout and "clean.ttf: ok" in r.stdout
    if not shutil.which("fontbakery"):
        r = run("check", "--fontbakery", str(clean))
        assert r.returncode == 2 and "not installed" in r.stderr
    # collections are checked face by face
    from fontTools.ttLib import TTCollection
    ttc = TTCollection()
    ttc.fonts = [TTFont(clean), TTFont(flagged)]
    ttc.save(tmp_path / "pair.ttc")
    r = run("check", str(tmp_path / "pair.ttc"))
    assert r.returncode == 1 and "pair.ttc#0: ok" in r.stdout and "pair.ttc#1: 1 warning" in r.stdout
    # a failing fontbakery makes the status 1
    import os
    fb = tmp_path / "fb" / "fontbakery"
    fb.parent.mkdir()
    fb.write_text("#!/bin/sh\nexit 3\n")
    fb.chmod(0o755)
    r = run("check", "--fontbakery", str(clean), env={**os.environ, "PATH": str(fb.parent)})
    assert r.returncode == 1 and "clean.ttf: ok" in r.stdout
