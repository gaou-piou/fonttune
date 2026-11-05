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
