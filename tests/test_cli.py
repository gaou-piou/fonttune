import subprocess
import sys
from pathlib import Path

BIN = Path(__file__).resolve().parent.parent / "bin" / "fonttune"


def run(*a):
    return subprocess.run([sys.executable, str(BIN), *a], capture_output=True, text=True)


def test_steps_listed():
    r = run("steps")
    assert r.returncode == 0 and "pixel_grid" in r.stdout


def test_grid_and_spacing_exclusive():
    r = run("run", "--pixel-grid", "14", "--even-spacing", "all", "--dry-run",
            "-o", "/tmp/ft_unused", str(BIN))
    assert r.returncode != 0 and "mutually exclusive" in r.stderr


def test_dry_run_plan():
    r = run("run", "--profile", "clean", "--dry-run", "-o", "/tmp/ft_unused", str(BIN))
    assert r.returncode == 0 and "otf2ttf" in r.stdout and "gasp" in r.stdout


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
    r = run("run", "--profile", "clean", "--dry-run", "--in-place", "--skip", "gasp", str(BIN))
    assert r.returncode == 0 and "gasp" not in r.stdout
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
          "chromium_flag_files": ["brave-flags.conf"], "gtk": {"gtk-4.0": "false"}}
    cfg = dict(cli.DEFAULTS, pixel_grid="14", hint="balanced")
    txt = advice.render(cfg, hs="slight", state=st)
    assert "force-enabled = true already set" in txt and "ignores the bytecode" in txt
    assert "now false, set true" in txt and "add --disable-font-subpixel-positioning" not in txt
    cfg = dict(cli.DEFAULTS, even_spacing="all")
    txt = advice.render(cfg, hs="slight", state=st)
    assert "remove --disable-font-subpixel-positioning" in txt and "already right" in txt
    assert "keep it" in txt
    assert "hint style is" in advice.render(dict(cli.DEFAULTS), hs="medium", state=st)


def test_statics_help_and_fit_weight_dispatch():
    assert "--regular-wght" in run("statics", "--help").stdout
    assert "--ppem" in run("fit-weight", "--help").stdout


def test_variable_fonts_ask_hint_not_grid(monkeypatch, capsys):
    sys.path.insert(0, str(BIN.parent.parent))
    from fonttune import prompts
    asked = []
    monkeypatch.setattr(prompts, "choice", lambda k, *a: asked.append(k) or a[-1])
    monkeypatch.setattr(prompts, "yesno", lambda k, *a: asked.append(k) or a[-1])
    monkeypatch.setattr(prompts, "hintstyle", lambda: "full")
    from fonttune.cli import DEFAULTS
    vf = {"trak": False, "gridable": False, "hintable": True, "variable": True}
    prompts.ask_config(DEFAULTS, vf)
    assert "hint" in asked and "pixel_grid" not in asked
    assert "[pixel_grid] skipped" in capsys.readouterr().out
    asked.clear()
    prompts.ask_config(DEFAULTS, {**vf, "gridable": True, "variable": False})
    assert "hint" in asked and "pixel_grid" in asked


def test_dev_toggle(tmp_path):
    import os
    env = {**os.environ, "XDG_CONFIG_HOME": str(tmp_path)}
    r = lambda *a: subprocess.run([sys.executable, str(BIN), "dev", *a], capture_output=True,  # noqa: E731
                                  text=True, env=env)
    assert r().stdout.startswith("git:")
    assert r("on").stdout.startswith("local:")
    assert (tmp_path / "fonttune" / "dev").read_text().strip() == str(BIN.parent.parent)
    assert r("off").stdout.startswith("git:") and not (tmp_path / "fonttune" / "dev").exists()


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
