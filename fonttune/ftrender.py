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
import platform
import re
import subprocess

from freetype.ft_structs import FT_Face, FT_Library

LOAD_RENDER = 0x4
LOAD_NO_HINTING = 0x2
TARGET_LIGHT = 1 << 16          # FT_LOAD_TARGET_(FT_RENDER_MODE_LIGHT)
MODES = {"slight": LOAD_RENDER | TARGET_LIGHT, "none": LOAD_RENDER | LOAD_NO_HINTING}

TEXT = "Hamburgefonstiv quick jump ÄÖÜ äöü ίϊΐ αλφάβητο ελληνικά 0123"


def system_path():
    """Absolute path of the system libfreetype.

    A bare soname is not enough: once freetype-py has loaded its bundled copy
    (soname libfreetype.so.6 too), dlopen("libfreetype.so.6") returns that copy.
    """
    env = os.environ.get("FONTTUNE_LIBFREETYPE")
    if env:
        return env
    arch = "x86-64" if platform.machine() == "x86_64" else platform.machine()
    try:
        out = subprocess.run(["ldconfig", "-p"], capture_output=True, text=True,
                             timeout=5, stdin=subprocess.DEVNULL).stdout
    except (OSError, subprocess.SubprocessError):
        out = ""
    for m in re.finditer(r"^\s*libfreetype\.so\.6 \(([^)]*)\) => (\S+)$", out, re.M):
        if arch in m.group(1) or "," not in m.group(1):
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
    lib.FT_Load_Char.argtypes = [FT_Face, ctypes.c_ulong, ctypes.c_int32]
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
        """Yield (char, rows, width, bytes) for each glyph of text at ppem."""
        face = FT_Face()
        if self.lib.FT_New_Face(self.handle, os.fsencode(font), 0, ctypes.byref(face)):
            raise RuntimeError(f"cannot open {font}")
        try:
            self.lib.FT_Set_Char_Size(face, 0, round(ppem * 64), 72, 72)
            for ch in text:
                if ch == " " or self.lib.FT_Load_Char(face, ord(ch), MODES[mode]):
                    continue
                b = face.contents.glyph.contents.bitmap
                rows, width, pitch = b.rows, b.width, b.pitch
                data = bytes(ctypes.string_at(b.buffer, rows * abs(pitch))) if rows else b""
                if pitch != width and rows:
                    data = b"".join(data[r * pitch:r * pitch + width] for r in range(rows))
                yield ch, rows, width, data
        finally:
            self.lib.FT_Done_Face(face)

    def ink(self, font, ppem, text=TEXT, mode="slight"):
        """Total coverage of text at ppem, in fully-black pixels."""
        return sum(sum(d) for _, _, _, d in self.glyphs(font, ppem, text, mode)) / 255

    def close(self):
        self.lib.FT_Done_FreeType(self.handle)
