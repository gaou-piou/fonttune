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
import re
import os
import shutil
import subprocess
import sys
import tomllib
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import __version__
from .system import auto_ppem

STEPS_DIR = Path(__file__).resolve().parent / "steps"
PROFILES_DIR = Path(__file__).resolve().parent.parent / "profiles"

# (key, description) in execution order
STEPS = [
    ("weights", "normalise OS/2 usWeightClass of Apple static fonts"),
    ("trak", "remove / bake the Apple trak table, or add STAT so HarfBuzz applies it"),
    ("otf2ttf", "convert CFF outlines to TrueType (cu2qu); FreeType then autohints them"),
    ("even_spacing", "class-kerning GPOS lookup that evens out letter pairs"),
    ("pixel_grid", "round advances and kerning to whole pixels at one ppem"),
    ("hint", "ttfautohint bytecode (FreeType runs it at hintmedium/hintfull only; see `hintconf`)"),
    ("features", "bake OpenType features into the font (and rename with a suffix)"),
    ("gasp", "rewrite the gasp table (sized|smooth|gridfit)"),
]
STEP_KEYS = [k for k, _ in STEPS]

DEFAULTS = {
    "otf2ttf": False, "weights": False, "trak": "", "even_spacing": "",
    "pixel_grid": "", "hint": "", "hint_mode": "auto", "hint_min": "auto",
    "hint_max": "auto", "hint_limit": "auto", "hint_xheight": "auto", "hint_xsnap": "auto",
    "features": "", "feature_target": "calt",
    "feature_family": "", "feature_suffix": "", "gasp": "keep", "ppem": 16.0,
    "even_strength": "auto", "even_depth": "auto", "even_max": "auto", "even_min": "auto",
}
BOOLS = {"otf2ttf", "weights"}
PROMPTED = ("otf2ttf", "weights", "trak", "even_spacing", "pixel_grid", "hint", "features",
            "feature_suffix", "gasp")

CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "fonttune" / "config.toml"
FONTS_CONF = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "fontconfig" / "fonts.conf"


def save_config(cfg, path=CONFIG):
    path = Path(path)
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
    if cfg["hint"] not in ("", "balanced", "sharp", "natural", "light"):
        die(f"unknown hint preset {cfg['hint']!r} (balanced, sharp, natural, light)")
    if str(cfg["hint_mode"]) != "auto" and not re.fullmatch(r"[nqs]{3}", str(cfg["hint_mode"])):
        die("hint_mode must be auto or 3 letters from n q s")
    for k in ("hint_min", "hint_max", "hint_limit", "hint_xheight"):
        if str(cfg[k]) != "auto" and not re.fullmatch(r"\d+", str(cfg[k])):
            die(f"{k} must be auto or a whole number")
    if cfg["gasp"] not in ("keep", "sized", "smooth", "gridfit"):
        die(f"unknown gasp mode {cfg['gasp']!r}")
    t = str(cfg["trak"])
    if t not in ("", "strip", "stat"):
        try:
            if float(t) <= 0:
                raise ValueError
        except ValueError:
            die(f"trak must be empty, strip, stat or a point size, not {t!r}")
    if cfg["even_spacing"] and not re.fullmatch(
            r"all|(latin|greek|cyrillic)(,(latin|greek|cyrillic))*", cfg["even_spacing"]):
        die("even_spacing must be all or a comma list of latin,greek,cyrillic")
    if cfg["pixel_grid"] and not re.fullmatch(r"auto|\d+(\.\d+)?", str(cfg["pixel_grid"])):
        die("pixel_grid must be empty, auto or a size in ppem")
    for k in ("even_strength", "even_depth", "even_max", "even_min"):
        if str(cfg[k]) != "auto" and not re.fullmatch(r"\d+(\.\d+)?", str(cfg[k])):
            die(f"{k} must be auto or a number")
    sfx = cfg["feature_suffix"]
    if sfx and not re.fullmatch(r"\s*[A-Za-z0-9][A-Za-z0-9 ._-]*", sfx):
        die(f"feature_suffix {sfx!r} is not usable as a family suffix")
    if cfg["features"] != "fonts.conf":
        for t in str(cfg["features"]).replace(" ", ",").split(","):
            if t and not re.fullmatch(r"[A-Za-z0-9]{4}", t):
                die(f"features: {t!r} is not a feature tag (e.g. ss06)")


def py(step, *args):
    cmd = [sys.executable, "-I", str(STEPS_DIR / f"{step}.py"), *map(str, args)]
    subprocess.run(cmd, check=True)


def pmap(step, jobs, items):
    """Run one step per item (a list of args each) on `jobs` workers."""
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
        for fut in [ex.submit(py, step, *a) for a in items]:
            fut.result()


# ── features from fontconfig ────────────────────────────────────────────────
ALWAYS = {"kern", "liga", "ccmp", "locl", "mark", "mkmk", "calt", "clig", "rlig", "rvrn"}
REFUSED = {"aalt", "ordn", "dlig", "salt", "hlig", "hist"}


def note(msg):
    print(f"  note: {msg}", file=sys.stderr)


def features_from_conf(conf, fam_re):
    """Active, bakeable fontfeatures tags of the <match target="font"> blocks
    whose family matches fam_re."""
    if not Path(conf).is_file():
        die(f"{conf} not found (use --fonts-conf)")
    rx = re.compile(fam_re or "")
    tags = []
    for m in ET.parse(conf).getroot().iter("match"):
        if m.get("target") != "font":
            continue
        if not any(t.get("name") == "family" and rx.search((t.findtext("string") or "").strip())
                   for t in m.findall("test")):
            continue
        for e in m.findall("edit"):
            if e.get("name") != "fontfeatures":
                continue
            for st in e.findall("string"):
                tag = (st.text or "").strip()
                why = ("negated" if tag.startswith("-") else
                       "already applied by every shaper" if tag in ALWAYS else
                       "refused by make_features.py" if tag in REFUSED else None)
                if why:
                    note(f"fonts.conf: '{tag}' skipped ({why})")
                elif tag not in tags:
                    tags.append(tag)
    return tags


def gsub_tags(files):
    from fontTools.ttLib import TTFont
    have = set()
    for p in files:
        f = TTFont(p, lazy=True)
        if "GSUB" in f:
            have |= {r.FeatureTag for r in f["GSUB"].table.FeatureList.FeatureRecord}
    return have


def resolve_features(cfg, files, ns):
    """-> comma list of tags to bake ('' = nothing)."""
    spec = cfg["features"]
    if spec != "fonts.conf":
        return ",".join(t for t in str(spec).replace(" ", ",").split(",") if t)
    tags = features_from_conf(ns.fonts_conf or FONTS_CONF, ns.features_match)
    have = gsub_tags(files)
    keep = []
    for t in tags:
        if t in have:
            keep.append(t)
        else:
            note(f"fonts.conf: '{t}' skipped (no font has it in GSUB)")
    print(f"fonttune: features from fonts.conf: {','.join(keep) or '<none>'}")
    return ",".join(keep)


def active(cfg, key):
    if key == "features":
        return bool(cfg["features"] or cfg["feature_suffix"])
    return cfg.get(key) not in (False, "", "keep", None)


def run(cfg, ns, fonts, out, dry):
    plan = [k for k in STEP_KEYS if active(cfg, k)
            and (not ns.only or k in ns.only) and k not in ns.skip]
    if "hint" in plan and "otf2ttf" not in plan and "otf2ttf" not in ns.skip \
            and any(str(f).lower().endswith(".otf") for f in fonts):
        plan.insert(plan.index("hint"), "otf2ttf")
        note("hint needs TrueType outlines: otf2ttf added")
    print("fonttune", __version__, "plan:", ", ".join(plan) or "(copy only)")
    if dry:
        return
    if ns.in_place:
        work = [Path(f) for f in fonts]
    else:
        out = Path(out)
        out.mkdir(parents=True, exist_ok=True)
        work = []
        for f in fonts:
            dst = out / Path(f).name
            shutil.copy2(f, dst)
            work.append(dst)
    ttfs = [w for w in work if w.suffix.lower() in (".ttf", ".otf")]
    jobs = ns.jobs or os.cpu_count() or 1
    workdir = ttfs[0].parent if ttfs else Path(".")

    def step_dir(name):
        d = workdir / f".fonttune-{name}"
        d.mkdir(exist_ok=True)
        return d

    def merge_back(d):
        for t in d.iterdir():
            shutil.move(t, workdir / t.name)
        d.rmdir()

    for step in plan:
        if step == "weights":
            py("fix_weights", *ttfs)
        elif step == "trak":
            t = str(cfg["trak"])
            if t == "stat":
                py("add_stat", *ttfs)
            else:
                py("strip_trak", *(["--bake", t] if t != "strip" else []), *ttfs)
        elif step == "otf2ttf":
            todo = [w for w in ttfs if w.suffix.lower() == ".otf"]
            pmap("otf2ttf", jobs, [["--post-format", "2.0", "--max-error", "1.0",
                                    "--overwrite", "-o", w.with_suffix(".ttf"), w] for w in todo])
            for w in todo:
                w.unlink()
            ttfs = [w.with_suffix(".ttf") if w.suffix.lower() == ".otf" else w for w in ttfs]
        elif step == "even_spacing":
            d = step_dir("even")
            args = ["--ppem", cfg["ppem"]]
            if cfg["even_spacing"] != "all":
                args += ["--script", cfg["even_spacing"]]
            for k in ("strength", "depth", "max", "min"):
                if str(cfg[f"even_{k}"]) != "auto":
                    args += [f"--{k}", cfg[f"even_{k}"]]
            pmap("even_spacing", jobs, [[*args, "-o", d, w] for w in ttfs])
            merge_back(d)
        elif step == "pixel_grid":
            grid = [w for w in ttfs if w.suffix.lower() == ".ttf"]
            if not grid:
                note("pixel_grid needs TrueType fonts (enable otf2ttf); skipped")
                continue
            d = step_dir("grid")
            pmap("pixel_grid", jobs, [["--ppem", cfg["pixel_grid"], "-o", d, w] for w in grid])
            merge_back(d)
        elif step == "hint":
            hinted = [w for w in ttfs if w.suffix.lower() == ".ttf"]
            args = []
            for k, flag in (("mode", "--mode"), ("min", "--min"), ("max", "--max"),
                            ("limit", "--limit"), ("xheight", "--xheight")):
                if str(cfg[f"hint_{k}"]) != "auto":
                    args += [flag, cfg[f"hint_{k}"]]
            if str(cfg["hint_xsnap"]) != "auto":
                args += ["--xsnap", "" if cfg["hint_xsnap"] == "none" else cfg["hint_xsnap"]]
            pmap("hint", jobs, [[cfg["hint"], w, *args] for w in hinted])
        elif step == "features":
            tags = resolve_features(cfg, ttfs, ns) if cfg["features"] else ""
            if tags:
                args = ["--features", tags, "--target", cfg["feature_target"]]
                if cfg["feature_family"]:
                    args += ["--family", cfg["feature_family"]]
                for s in ns.feature_skip:
                    args += ["--skip", s]
                py("make_features", *args, *ttfs)
            elif cfg["features"]:
                print("fonttune: no feature left to bake; fonts kept as they are")
            if cfg["feature_suffix"]:
                py("fix_names", "--suffix", cfg["feature_suffix"], *ttfs)
        elif step == "gasp":
            py("set_gasp", cfg["gasp"], *ttfs)

    if not ns.in_place:
        (Path(out) / "fonttune.json").write_text(json.dumps(
            {"fonttune": __version__, "steps": plan,
             "config": {k: cfg[k] for k in plan}}, indent=2) + "\n")


def parse_steps(v):
    ks = [x for x in (v or "").split(",") if x]
    for k in ks:
        if k not in STEP_KEYS:
            die(f"unknown step {k!r} (see: fonttune steps)")
    return ks


def env_layer():
    given = {}
    for k, d in DEFAULTS.items():
        v = os.environ.get(f"FONTTUNE_{k.upper()}")
        if v is None:
            continue
        if k in BOOLS:
            if v.lower() not in ("true", "false", "1", "0", "yes", "no"):
                die(f"FONTTUNE_{k.upper()} must be true or false")
            given[k] = v.lower() in ("true", "1", "yes")
        elif isinstance(d, float):
            given[k] = float(v)
        else:
            given[k] = v
    return given


def main(argv=None):
    ap = argparse.ArgumentParser(prog="fonttune")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("steps", help="list the pipeline steps in order")
    h = sub.add_parser("hintconf", help="write the fontconfig snippet that enables bytecode hinting")
    h.add_argument("fonts", nargs="+")
    h.add_argument("-o", "--out", default="-", help="file to write (default: stdout)")
    h.add_argument("--name", default="fonttune")
    r = sub.add_parser("run", help="apply the pipeline")
    c = sub.add_parser("configure", help="ask the settings and save them (no fonts are changed)")
    for p in (r, c):
        p.add_argument("fonts", nargs="+")
        p.add_argument("--profile", help="settings file/name; no questions are asked")
        p.add_argument("--defaults", help="settings file/name used as the defaults the questions offer")
        p.add_argument("--config", help="read the settings from this file (no questions)")
        p.add_argument("--otf2ttf", action="store_true", default=None)
        p.add_argument("--weights", action="store_true", default=None)
        p.add_argument("--trak", help="'strip', 'stat' or a size in pt to bake")
        p.add_argument("--even-spacing", dest="even_spacing", help="latin,greek,cyrillic or all")
        p.add_argument("--pixel-grid", dest="pixel_grid", help="auto or target ppem")
        p.add_argument("--ppem", type=float)
        p.add_argument("--even-strength", dest="even_strength")
        p.add_argument("--even-depth", dest="even_depth")
        p.add_argument("--even-max", dest="even_max")
        p.add_argument("--even-min", dest="even_min")
        p.add_argument("--features", help="tag list or 'fonts.conf'")
        p.add_argument("--feature-target", dest="feature_target")
        p.add_argument("--feature-family", dest="feature_family")
        p.add_argument("--feature-suffix", dest="feature_suffix",
                       help="append to every family name (' Alt'), also where no feature applies")
        p.add_argument("--hint", help="ttfautohint preset: balanced, sharp, natural or light")
        for k in ("mode", "min", "max", "limit", "xheight", "xsnap"):
            p.add_argument(f"--hint-{k}", dest=f"hint_{k}")
        p.add_argument("--gasp")
        p.add_argument("--ask", action="store_true", help="prompt even when flags are given")
        p.add_argument("--no-ask", action="store_true")
        p.add_argument("--no-config", action="store_true", help="ignore ~/.config/fonttune/config.toml")
        p.add_argument("--save", action="store_true", help="write the final settings to config.toml")
    c.add_argument("--save-to", required=True, help="where to write the settings")
    r.add_argument("-o", "--out")
    r.add_argument("--in-place", action="store_true", help="edit the given fonts, no copy")
    r.add_argument("--only", default="", help="comma list of steps to run")
    r.add_argument("--skip", default="", help="comma list of steps to leave out")
    r.add_argument("-j", "--jobs", type=int, help="parallel fonts (default: all cores)")
    r.add_argument("--fonts-conf", help="fontconfig file for features=fonts.conf")
    r.add_argument("--features-match", default="", help="regex: only fonts.conf blocks whose family matches")
    r.add_argument("--feature-skip", action="append", default=[], metavar="TAG=REGEX[|WHY]",
                   help="do not bake TAG into fonts matching REGEX")
    r.add_argument("--dry-run", action="store_true", help="print the plan only")
    a = ap.parse_args(argv)

    if a.cmd == "steps":
        for k, d in STEPS:
            print(f"{k:13} {d}")
        return 0
    if a.cmd == "hintconf":
        from . import hintconf
        hintconf.main(a.fonts, a.out, a.name)
        return 0
    if a.cmd == "run":
        if not a.in_place and not a.out:
            die("run needs -o OUT or --in-place")
        a.only, a.skip = parse_steps(a.only), parse_steps(a.skip)

    cfg = dict(DEFAULTS)
    if a.defaults:
        cfg.update(load_profile(a.defaults))
    fixed = bool(a.profile or a.config)
    if a.config:
        cfg.update(load_profile(a.config))
    elif not a.no_config and not a.profile and CONFIG.is_file():
        with open(CONFIG, "rb") as fh:
            cfg.update(tomllib.load(fh))
    if a.profile:
        cfg.update(load_profile(a.profile))
    given = env_layer()
    for k in DEFAULTS:
        v = getattr(a, k, None)
        if v is not None:
            given[k] = v
    cfg.update(given)
    for f in a.fonts:
        if not os.path.isfile(f):
            die(f"no such font: {f}")
    asked = bool(a.ask or (not a.no_ask and not fixed and sys.stdin.isatty()))
    if asked:
        from .prompts import ask_config
        cfg = ask_config(cfg, facts(a.fonts), set(given) if not a.ask else set())
    if a.save:
        save_config(cfg)
        print(f"fonttune: settings saved to {CONFIG}")
    if cfg["pixel_grid"] == "auto" and a.cmd == "run":
        cfg["pixel_grid"] = auto_ppem()
        print(f"fonttune: pixel_grid auto -> {cfg['pixel_grid']:g} ppem")
    if cfg["pixel_grid"] != "auto":
        cfg["pixel_grid"] = str(cfg["pixel_grid"]) if cfg["pixel_grid"] else ""
    cfg["trak"] = str(cfg["trak"]) if cfg["trak"] else ""
    validate(cfg)
    if asked:
        from . import advice
        from .prompts import confirm
        if not confirm(advice.render(cfg, has_trak=facts(a.fonts)["trak"])):
            die("aborted")
    if a.cmd == "configure":
        save_config(cfg, a.save_to)
        print(f"fonttune: settings written to {a.save_to}")
        return 0
    try:
        run(cfg, a, a.fonts, a.out, a.dry_run)
    except subprocess.CalledProcessError as e:
        die(f"step failed: {' '.join(map(str, e.cmd[2:4]))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
