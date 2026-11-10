"""statics: axis pins."""
import subprocess
import sys
from pathlib import Path

import pytest

BIN = Path(__file__).resolve().parent.parent / "bin" / "fonttune"


def test_statics_opsz_auto_and_clamp(tmp_path, monkeypatch):
    """opsz=auto pins the interface size in points, like Pango does for a VF."""
    vf = Path("/usr/share/fonts/Adwaita/AdwaitaSans-Regular.ttf")    # opsz 14-32
    if not vf.is_file():
        pytest.skip("needs Adwaita Sans (a variable font with an opsz axis)")
    from fontTools.ttLib import TTFont
    ax = {a.axisTag: a for a in TTFont(vf)["fvar"].axes}
    monkeypatch.setenv("PATH", str(tmp_path))          # no gsettings: font_pt() falls back to 12
    step = BIN.parent.parent / "fonttune" / "steps" / "statics.py"
    sys.path.insert(0, str(BIN.parent.parent))
    from fonttune.ftrender import Renderer
    for val, want in (("auto", 12), ("99", ax["opsz"].maxValue)):
        out = tmp_path / val
        r = subprocess.run([sys.executable, "-I", str(step), "-o", str(out), "--family", "T",
                            "--weights", "400", "--axis", f"opsz={val}", str(vf)],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        assert ("opsz auto: 12" in r.stdout) == (val == "auto")
        assert ("outside" in r.stdout) == (val == "99" or ax["opsz"].minValue > 12)
        with Renderer() as rr:
            [static] = out.glob("*.ttf")
            a = rr.ink(str(static), 16, mode="none")
            b = rr.ink(str(vf), 16, mode="none", axes={"opsz": max(want, ax["opsz"].minValue)})
            other = rr.ink(str(vf), 16, mode="none", axes={"opsz": ax["opsz"].minValue
                           if val == "99" else ax["opsz"].maxValue})
            assert abs(a / b - 1) < 0.02 < abs(a / other - 1)   # overlap removal ~0.4%, other ~8%


def test_font_pt_ignores_text_scaling(tmp_path, monkeypatch):
    """GTK scales text through the dpi, so Pango's opsz stays at the unscaled size."""
    gs = tmp_path / "gsettings"
    gs.write_text("#!/bin/sh\ncase \"$3\" in font-name) echo \"'Inter 11'\";; "
                  "text-scaling-factor) echo 1.25;; esac\n")
    gs.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    sys.path.insert(0, str(BIN.parent.parent))
    from fonttune.system import auto_ppem, font_pt
    assert font_pt() == 11.0
    assert auto_ppem() == round(11 * 96 / 72 * 1.25, 4)


def test_statics_bad_axis_value(tmp_path):
    step = BIN.parent.parent / "fonttune" / "steps" / "statics.py"
    for v in ("big", "nan", "inf"):
        r = subprocess.run([sys.executable, "-I", str(step), "-o", str(tmp_path), "--family", "T",
                            "--axis", f"opsz={v}", "x.ttf"], capture_output=True, text=True)
        assert r.returncode != 0 and "not a number" in r.stderr and "Traceback" not in r.stderr


def test_statics_validates_pins_before_writing(tmp_path):
    """A pin that fails on the second font stops before the first is written."""
    vf = Path("/usr/share/fonts/Adwaita/AdwaitaSans-Regular.ttf")     # no slnt axis
    if not vf.is_file():
        pytest.skip("needs Adwaita Sans")
    step = BIN.parent.parent / "fonttune" / "steps" / "statics.py"
    out = tmp_path / "out"
    r = subprocess.run([sys.executable, "-I", str(step), "-o", str(out), "--family", "T",
                        "--weights", "400", "--axis", "slnt=-10", str(vf)],
                       capture_output=True, text=True)
    assert r.returncode != 0 and "has no slnt axis" in r.stderr
    assert not out.exists()


def test_statics_opsz_auto_reads_unscaled_size(tmp_path, monkeypatch):
    """With a desktop at 18 pt and text-scaling 1.25, opsz=auto must cut opsz 18
    (inside Adwaita's 14-32), not the scaled 22.5."""
    vf = Path("/usr/share/fonts/Adwaita/AdwaitaSans-Regular.ttf")
    if not vf.is_file():
        pytest.skip("needs Adwaita Sans")
    gs = tmp_path / "bin" / "gsettings"
    gs.parent.mkdir()
    gs.write_text("#!/bin/sh\ncase \"$3\" in font-name) echo \"'Adwaita Sans 18'\";; "
                  "text-scaling-factor) echo 1.25;; esac\n")
    gs.chmod(0o755)
    monkeypatch.setenv("PATH", str(gs.parent))
    step = BIN.parent.parent / "fonttune" / "steps" / "statics.py"
    out = tmp_path / "out"
    r = subprocess.run([sys.executable, "-I", str(step), "-o", str(out), "--family", "T",
                        "--weights", "400", "--axis", "opsz=auto", str(vf)],
                       capture_output=True, text=True)
    assert r.returncode == 0 and "opsz auto: 18" in r.stdout, r.stdout + r.stderr
    sys.path.insert(0, str(BIN.parent.parent))
    from fonttune.ftrender import Renderer
    [static] = out.glob("*.ttf")
    with Renderer() as rr:
        x = rr.extent(str(static), 30, "x", "none")[0]
        at = {o: rr.extent(str(vf), 30, "x", "none", {"opsz": o})[0] for o in (18, 22.5)}
    assert x == at[18] != at[22.5]


def test_statics_slnt_pin_that_clamps_to_upright(tmp_path):
    """A slnt pin outside the axis is clamped; one that ends up at 0 would cut an
    upright labelled italic, so it stops. Adwaita's opsz axis stands in for slnt
    (renamed, range -10..0)."""
    vf = Path("/usr/share/fonts/Adwaita/AdwaitaSans-Regular.ttf")
    if not vf.is_file():
        pytest.skip("needs Adwaita Sans")
    from fontTools.ttLib import TTFont
    f = TTFont(vf)
    for a in f["fvar"].axes:
        if a.axisTag == "opsz":
            a.axisTag, a.minValue, a.defaultValue, a.maxValue = "slnt", -10, 0, 0
    for inst in f["fvar"].instances:
        inst.coordinates["slnt"] = 0
        del inst.coordinates["opsz"]
    if "STAT" in f:
        del f["STAT"]
    slanted = tmp_path / "slnt.ttf"
    f.save(slanted)
    step = BIN.parent.parent / "fonttune" / "steps" / "statics.py"
    for pin, ok in (("5", False), ("-20", True)):
        out = tmp_path / pin
        r = subprocess.run([sys.executable, "-I", str(step), "-o", str(out), "--family", "T",
                            "--weights", "400", "--axis", f"slnt={pin}", str(slanted)],
                           capture_output=True, text=True)
        assert (r.returncode == 0) == ok, r.stdout + r.stderr
        assert "Traceback" not in r.stderr
        if ok:
            [static] = out.glob("*.ttf")
            t = TTFont(static)
            assert t["post"].italicAngle == -10 and t["OS/2"].fsSelection & 1
        else:
            assert not out.exists()
