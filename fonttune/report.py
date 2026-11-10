"""After the steps: the reports chosen with `check`, `darken` and `xheight`.

They read the built fonts and print what they measured; they never change a
font and never stop the run (a failing report is printed and skipped).
darken and xheight measure one font, the upright closest to Regular: that is
the one interface text is drawn with.
"""
import sys

from fontTools.ttLib import TTFont


def regular(fonts):
    """The upright font whose usWeightClass is closest to 400."""
    def key(f):
        try:
            with TTFont(f, lazy=True, fontNumber=0) as t:
                os2 = t["OS/2"]
                italic = bool(os2.fsSelection & 1) or t["post"].italicAngle != 0
                return (italic, abs(os2.usWeightClass - 400), str(f))
        except Exception:  # noqa: BLE001 - unreadable fonts go last
            return (True, 10 ** 6, str(f))
    return min(fonts, key=key)


def _call(title, module, argv):
    print(f"\n══ fonttune {title} ══", flush=True)
    try:
        from importlib import import_module
        import_module(f"{__package__}.{module}").main(argv)
    except SystemExit:  # argparse already printed why
        pass
    except Exception as e:  # noqa: BLE001 - a report must not fail the build
        print(f"  {module} skipped: {type(e).__name__}: {e}")
    sys.stdout.flush()


def wanted(cfg):
    return [k for k in ("check", "xheight", "darken") if cfg.get(k) not in (False, "", None)]


def run(cfg, fonts, hs):
    """fonts: the built fonts; hs: the desktop hint style (system.hintstyle())."""
    fonts = [str(f) for f in fonts]
    if not fonts or not wanted(cfg):
        return
    if cfg.get("check"):
        _call("check", "check", [*fonts, *(["--fontbakery"] if cfg["check"] == "fontbakery" else [])])
    if not (cfg.get("xheight") or cfg.get("darken")):
        return
    reg = regular(fonts)
    if cfg.get("xheight"):
        # the bytecode runs only when there is one and the desktop hints at medium/full
        mode = "full" if cfg.get("hint") and hs in ("medium", "full") else "slight"
        _call(f"xheight ({mode})", "xheight", [reg, "--mode", mode])
    if cfg.get("darken"):
        _call("darken", "darken", [reg, "--ink", str(cfg["darken"])])
