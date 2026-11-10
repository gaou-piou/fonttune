"""Render text with the *system* FreeType, the one GTK and cairo use.

freetype-py wheels bundle their own libfreetype (2.13.2 in the pip wheel),
so measuring with `import freetype` alone says nothing about the FreeType
the desktop runs. This module only borrows freetype-py's ctypes structs and
calls the system library directly.

FREETYPE_PROPERTIES is read when a library handle is created, so a property
set later in the same process needs a fresh `Renderer`.
"""
import ctypes
import ctypes.util
import os
import functools
import re
import subprocess
import sys

from freetype.ft_structs import FT_Face, FT_Library

LOAD_RENDER = 0x4
LOAD_NO_HINTING = 0x2
TARGET_LIGHT = 1 << 16          # FT_LOAD_TARGET_(FT_RENDER_MODE_LIGHT)
# slight = cairo hintslight; full = hintmedium/hintfull (the bytecode runs)
MODES = {"slight": LOAD_RENDER | TARGET_LIGHT, "full": LOAD_RENDER,
         "none": LOAD_RENDER | LOAD_NO_HINTING}

TEXT = "Hamburgefonstiv quick jump ÄÖÜ äöü ίϊΐ αλφάβητο ελληνικά 0123"


@functools.cache
def system_path():
    """Absolute path of the system libfreetype.

    A bare soname is not enough: once freetype-py has loaded its bundled copy
    (soname libfreetype.so.6 too), dlopen("libfreetype.so.6") returns that copy.
    """
    env = os.environ.get("FONTTUNE_LIBFREETYPE")
    if env:
        return env
    want64 = sys.maxsize > 2 ** 32        # ldconfig tags 64-bit libs x86-64, AArch64, 64bit
    try:
        out = subprocess.run(["ldconfig", "-p"], capture_output=True, text=True,
                             timeout=5, stdin=subprocess.DEVNULL).stdout
    except (OSError, subprocess.SubprocessError):
        out = ""
    for m in re.finditer(r"^\s*libfreetype\.so\.6 \(([^)]*)\) => (\S+)$", out, re.M):
        if ("64" in m.group(1)) == want64:
            return m.group(2)
    name = ctypes.util.find_library("freetype")
    if not name:
        raise RuntimeError("no system libfreetype found")
    return name


def _lib():
    path = system_path()
    lib = ctypes.CDLL(path)
    lib.FT_New_Face.argtypes = [FT_Library, ctypes.c_char_p, ctypes.c_long, ctypes.POINTER(FT_Face)]
    lib.FT_Set_Char_Size.argtypes = [FT_Face, ctypes.c_long, ctypes.c_long, ctypes.c_uint, ctypes.c_uint]
    lib.FT_Get_Char_Index.argtypes = [FT_Face, ctypes.c_ulong]
    lib.FT_Get_Char_Index.restype = ctypes.c_uint
    lib.FT_Load_Glyph.argtypes = [FT_Face, ctypes.c_uint, ctypes.c_int32]
    lib.FT_Done_Face.argtypes = [FT_Face]
    lib.FT_Done_FreeType.argtypes = [FT_Library]
    return lib


class Renderer:
    def __init__(self):
        self.lib = _lib()
        self.handle = FT_Library()
        if self.lib.FT_Init_FreeType(ctypes.byref(self.handle)):
            raise RuntimeError("FT_Init_FreeType failed")

    def version(self):
        v = [ctypes.c_int() for _ in range(3)]
        self.lib.FT_Library_Version(self.handle, *map(ctypes.byref, v))
        return ".".join(str(x.value) for x in v)

    def glyphs(self, font, ppem, text=TEXT, mode="slight"):
        """Yield (char, rows, width, bytes) for each glyph of text at ppem.

        Characters the font lacks are skipped (no .notdef boxes)."""
        face = FT_Face()
        if self.lib.FT_New_Face(self.handle, os.fsencode(font), 0, ctypes.byref(face)):
            raise RuntimeError(f"cannot open {font}")
        try:
            self.lib.FT_Set_Char_Size(face, 0, round(ppem * 64), 72, 72)
            for ch in text:
                gid = self.lib.FT_Get_Char_Index(face, ord(ch))
                if ch == " " or not gid or self.lib.FT_Load_Glyph(face, gid, MODES[mode]):
                    continue
                b = face.contents.glyph.contents.bitmap
                rows, width, pitch = b.rows, b.width, abs(b.pitch)
                data = bytes(ctypes.string_at(b.buffer, rows * pitch)) if rows else b""
                if pitch != width and rows:
                    data = b"".join(data[r * pitch:r * pitch + width] for r in range(rows))
                if b.pitch < 0:    # bottom-up: buffer points at the last row
                    data = b"".join(data[r * width:(r + 1) * width] for r in reversed(range(rows)))
                yield ch, rows, width, data
        finally:
            self.lib.FT_Done_Face(face)

    def ink(self, font, ppem, text=TEXT, mode="slight"):
        """Total coverage of text at ppem, in fully-black pixels."""
        return sum(sum(d) for _, _, _, d in self.glyphs(font, ppem, text, mode)) / 255

    def close(self):
        if self.handle:
            self.lib.FT_Done_FreeType(self.handle)
            self.handle = FT_Library()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
