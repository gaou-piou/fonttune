"""fonttune command line: run a fixed pipeline of font steps over fonts.

    fonttune run [options] -o OUT FONT...
    fonttune steps
    fonttune --version

Fonts are copied to OUT first; every step then edits OUT in place, so the
inputs are never touched.  Step order and the PIXEL_GRID/EVEN_SPACING
exclusion live here, once, instead of in every PKGBUILD.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

from . import __version__
from .system import auto_ppem

STEPS_DIR = Path(__file__).resolve().parent / "steps"
PROFILES_DIR = Path(__file__).resolve().parent.parent / "profiles"

# (key, description) in execution order
STEPS = [
    ("otf2ttf", "convert CFF outlines to TrueType (cu2qu); FreeType then autohints them"),
    ("weights", "normalise OS/2 usWeightClass of Apple static fonts"),
    ("trak", "remove (or bake at a size) the Apple trak table"),
    ("even_spacing", "class-kerning GPOS lookup that evens out letter pairs"),
    ("pixel_grid", "round advances and kerning to whole pixels at one ppem"),
    ("features", "bake OpenType features into the font"),
    ("gasp", "rewrite the gasp table (sized|smooth|gridfit)"),
]

DEFAULTS = {
    "otf2ttf": False, "weights": False, "trak": "", "even_spacing": "",
    "pixel_grid": "", "features": "", "feature_target": "calt",
    "feature_family": "", "gasp": "keep", "ppem": 16.0,
}


CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "fonttune" / "config.toml"


def save_config(cfg, path=CONFIG):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for k in DEFAULTS:
        v = cfg[k]
        if isinstance(v, bool):
            lines.append(f"{k} = {str(v).lower()}")
        elif isinstance(v, (int, float)):
            lines.append(f"{k} = {v}")
        else:
            lines.append(f'{k} = "{v}"')
    path.write_text("\n".join(lines) + "\n")


def facts(fonts):
    """What the inputs allow, so prompts only ask relevant things."""
    from fontTools.ttLib import TTFont
    trak, gridable = False, True
    for f in fonts:
        try:
            t = TTFont(f, lazy=True)
        except Exception:  # noqa: BLE001
            continue
        trak |= "trak" in t
        if "fvar" in t or "glyf" not in t and "CFF " not in t:
            gridable = False
    return {"trak": trak, "gridable": gridable}


def die(msg):
    sys.exit(f"fonttune: {msg}")


def load_profile(name):
    p = Path(name)
    if not p.is_file():
        p = PROFILES_DIR / f"{name}.toml"
    if not p.is_file():
        die(f"profile not found: {name}")
    with open(p, "rb") as fh:
        return tomllib.load(fh)


def validate(cfg):
    if cfg["pixel_grid"] and cfg["even_spacing"]:
        die("pixel_grid and even_spacing are mutually exclusive: pixel_grid "
            "zeroes most of the small kerns even_spacing adds")
    if cfg["gasp"] not in ("keep", "sized", "smooth", "gridfit"):
        die(f"unknown gasp mode {cfg['gasp']!r}")


def py(step, *args):
    cmd = [sys.executable, "-I", str(STEPS_DIR / f"{step}.py"), *map(str, args)]
    subprocess.run(cmd, check=True)


def run(cfg, fonts, out, dry):
    out = Path(out)
    plan = [k for k, _ in STEPS if cfg.get(k) not in (False, "", "keep", None)]
    print("fonttune", __version__, "plan:", ", ".join(plan) or "(copy only)")
    if dry:
        return
    out.mkdir(parents=True, exist_ok=True)
    work = []
    for f in fonts:
        dst = out / Path(f).name
        shutil.copy2(f, dst)
        work.append(dst)
    ttfs = [w for w in work if w.suffix.lower() in (".ttf", ".otf")]

    if cfg["otf2ttf"]:
        for w in [w for w in ttfs if w.suffix.lower() == ".otf"]:
            py("otf2ttf", "--post-format", "2.0", "--max-error", "1.0",
               "--overwrite", "-o", w.with_suffix(".ttf"), w)
            w.unlink()
        ttfs = [w.with_suffix(".ttf") if w.suffix.lower() == ".otf" else w for w in ttfs]
    if cfg["weights"]:
        py("fix_weights", *ttfs)
    if cfg["trak"]:
        py("strip_trak", *(["--bake", cfg["trak"]] if cfg["trak"] != "strip" else []), *ttfs)
    for step in ("even_spacing", "pixel_grid"):
        v = cfg[step]
        if v:
            tmp = out / f".{step}"
            tmp.mkdir(exist_ok=True)
            args = ["--ppem", v if step == "pixel_grid" else cfg["ppem"]]
            if step == "even_spacing" and v != "all":
                args += ["--script", v]
            py(step, *args, "-o", tmp, *ttfs)
            for t in tmp.iterdir():
                shutil.move(t, out / t.name)
            tmp.rmdir()
    if cfg["features"]:
        args = ["--features", cfg["features"], "--target", cfg["feature_target"]]
        if cfg["feature_family"]:
            args += ["--family", cfg["feature_family"]]
        py("make_features", *args, *ttfs)
    if cfg["gasp"] != "keep":
        py("set_gasp", cfg["gasp"], *ttfs)

    (out / "fonttune.json").write_text(json.dumps(
        {"fonttune": __version__, "steps": plan,
         "config": {k: cfg[k] for k in plan}}, indent=2) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="fonttune")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("steps", help="list the pipeline steps in order")
    r = sub.add_parser("run", help="apply the pipeline")
    r.add_argument("fonts", nargs="+")
    r.add_argument("-o", "--out", required=True)
    r.add_argument("--profile")
    r.add_argument("--otf2ttf", action="store_true", default=None)
    r.add_argument("--weights", action="store_true", default=None)
    r.add_argument("--trak", help="'strip' or a size in pt to bake")
    r.add_argument("--even-spacing", dest="even_spacing", help="latin,greek,cyrillic or all")
    r.add_argument("--pixel-grid", dest="pixel_grid", help="target ppem")
    r.add_argument("--ppem", type=float)
    r.add_argument("--features")
    r.add_argument("--feature-target", dest="feature_target")
    r.add_argument("--feature-family", dest="feature_family")
    r.add_argument("--gasp")
    r.add_argument("--ask", action="store_true", help="prompt for the settings (default on a terminal with no flags)")
    r.add_argument("--no-ask", action="store_true")
    r.add_argument("--no-config", action="store_true", help="ignore ~/.config/fonttune/config.toml")
    r.add_argument("--save", action="store_true", help="write the final settings to config.toml")
    r.add_argument("--dry-run", action="store_true", help="print the plan only")
    a = ap.parse_args(argv)

    if a.cmd == "steps":
        for k, d in STEPS:
            print(f"{k:13} {d}")
        return 0

    cfg = dict(DEFAULTS)
    if not a.no_config and CONFIG.is_file() and not a.profile:
        with open(CONFIG, "rb") as fh:
            cfg.update(tomllib.load(fh))
    if a.profile:
        cfg.update(load_profile(a.profile))
    given = False
    for k in DEFAULTS:
        v = getattr(a, k, None)
        if v is not None:
            cfg[k] = v
            given = True
    for f in a.fonts:
        if not os.path.isfile(f):
            die(f"no such font: {f}")
    if a.ask or (not a.no_ask and not a.profile and not given and sys.stdin.isatty()):
        from .prompts import ask_config
        cfg = ask_config(cfg, facts(a.fonts))
    if a.save:
        save_config(cfg)
        print(f"fonttune: settings saved to {CONFIG}")
    if cfg["pixel_grid"] == "auto":
        cfg["pixel_grid"] = auto_ppem()
        print(f"fonttune: pixel_grid auto -> {cfg['pixel_grid']:g} ppem")
    cfg["pixel_grid"] = str(cfg["pixel_grid"]) if cfg["pixel_grid"] else ""
    validate(cfg)
    try:
        run(cfg, a.fonts, a.out, a.dry_run)
    except subprocess.CalledProcessError as e:
        die(f"step failed: {' '.join(map(str, e.cmd[2:4]))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
