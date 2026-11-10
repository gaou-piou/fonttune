"""statics: axis pins."""
import subprocess
import sys
from pathlib import Path

BIN = Path(__file__).resolve().parent.parent / "bin" / "fonttune"


def test_statics_opsz_auto_and_clamp(tmp_path, monkeypatch):
    """opsz=auto pins the interface size in points, like Pango does for a VF."""
    import pytest
    vf = Path("/usr/share/fonts/Adwaita/AdwaitaSans-Regular.ttf")    # opsz 14-32
    if not vf.is_file():
        pytest.skip("needs Adwaita Sans (a variable font with an opsz axis)")
    from fontTools.ttLib import TTFont
    ax = {a.axisTag: a for a in TTFont(vf)["fvar"].axes}
    monkeypatch.setenv("PATH", str(tmp_path))          # no gsettings: auto_pt() falls back to 12
    step = BIN.parent.parent / "fonttune" / "steps" / "statics.py"
    for val, want in (("auto", 12), ("99", ax["opsz"].maxValue)):
        out = tmp_path / val
        r = subprocess.run([sys.executable, "-I", str(step), "-o", str(out), "--family", "T",
                            "--weights", "400", "--axis", f"opsz={val}", str(vf)],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        assert ("opsz auto: 12" in r.stdout) == (val == "auto")
        assert ("outside" in r.stdout) == (val == "99" or ax["opsz"].minValue > 12)
        sys.path.insert(0, str(BIN.parent.parent))
        from fonttune.ftrender import Renderer
        with Renderer() as rr:
            [static] = out.glob("*.ttf")
            a = rr.ink(str(static), 16, mode="none")
            b = rr.ink(str(vf), 16, mode="none", axes={"opsz": max(want, ax["opsz"].minValue)})
            other = rr.ink(str(vf), 16, mode="none", axes={"opsz": ax["opsz"].minValue
                           if val == "99" else ax["opsz"].maxValue})
            assert abs(a / b - 1) < 0.005 < abs(a / other - 1)   # overlap removal moves ~0.4%
