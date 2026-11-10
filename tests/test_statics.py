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
            assert abs(a / b - 1) < 0.005 < abs(a / other - 1)   # overlap removal moves ~0.4%


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
    r = subprocess.run([sys.executable, "-I", str(step), "-o", str(tmp_path), "--family", "T",
                        "--axis", "opsz=big", "x.ttf"], capture_output=True, text=True)
    assert r.returncode != 0 and "not a number" in r.stderr and "Traceback" not in r.stderr
