"""ftrender: what the measurements read."""
import math
import sys
from pathlib import Path

import pytest

pytest.importorskip("freetype")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fonttune.ftrender import Renderer  # noqa: E402

EBDT = Path("/usr/share/fonts/TTF/odosung-ExtB.ttf")   # glyf outlines + 1-bit EBDT strikes


def test_embedded_bitmaps_are_skipped(tmp_path):
    """A 1-bit strike would be read as gray bytes; the outlines must be what is measured."""
    if not EBDT.is_file():
        pytest.skip("needs a font with embedded bitmaps (odosung-ExtB)")
    from fontTools.ttLib import TTFont
    f = TTFont(EBDT)
    text = "".join(chr(c) for c in sorted(f.getBestCmap()) if c > 0x20000)[:6]
    del f["EBDT"], f["EBLC"]
    outlines = tmp_path / "outlines.ttf"
    f.save(outlines)
    with Renderer() as r:
        for mode in ("slight", "full", "none"):
            assert r.glyphs(str(EBDT), 11, text, mode) == r.glyphs(str(outlines), 11, text, mode)


@pytest.mark.parametrize("ppem", [0, -3, math.nan, math.inf])
def test_bad_ppem_raises(ppem):
    font = "/usr/share/fonts/Adwaita/AdwaitaSans-Regular.ttf"
    if not Path(font).is_file():
        pytest.skip("needs Adwaita Sans")
    with Renderer() as r, pytest.raises(ValueError, match="ppem"):
        r.ink(font, ppem)


def test_system_freetype_without_path(monkeypatch, tmp_path):
    """Tests that empty PATH (for a fake gsettings) still get the system FreeType,
    not the copy bundled with freetype-py."""
    from fonttune import ftrender
    ftrender.system_path.cache_clear()
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.delenv("FONTTUNE_LIBFREETYPE", raising=False)
    try:
        got = ftrender.system_path()
        assert Path(got).is_absolute() and "site-packages" not in got
    finally:
        ftrender.system_path.cache_clear()
