# fonttune

One pipeline of font-tuning steps for the `*-hinted` packages (not on the AUR;
PKGBUILDs fetch it as a git source on `main`).

    fonttune steps
    fonttune run --profile clean --pixel-grid 16 -o out/ fonts/*.ttf
    fonttune run --dry-run ...        # print the plan only

Inputs are copied to `-o` first; steps edit the copies. A `fonttune.json` in
the output records the version and the steps applied.

Order: weights, trak, otf2ttf, even_spacing | pixel_grid, hint, alts, features, gasp.

`alts` (`--alts`, on in the `clean` profile) is for fonts that draw alternate letters
but reach them only through `aalt` (Google Sans: single-storey a, J with a bar,
slashed zero, ...), which no renderer applies to text. It adds one `cvXX` per
character, off by default, so fontconfig `fontfeatures`, CSS or `features=fonts.conf`
can turn on just the ones wanted. Accented letters go with their base letter,
ligatures with the component that has the alternate (f_t with t); the build prints
the table (`fonttune/steps/expose_alts.py --list FONT...` shows it without changing
anything). The lookups run last, so case/liga forms get their own alternate
(zero.cap -> zero.alt.cap) and tabular or fraction figures are left alone.

`hint` runs ttfautohint (presets balanced, sharp, natural, light; `--hint-mode/-min/-max/-limit/-xheight/-xsnap` override) and adds otf2ttf when it gets OTFs. FreeType runs the bytecode only at hintmedium/hintfull, so under hintslight it changes nothing; `configure` reads the desktop hint style and preselects `no` there. `fonttune hintconf -o 80-x.conf FONT...` writes the fontconfig snippet that enables bytecode hinting for those families (Chromium/Electron excluded).

`fonttune configure --save-to FILE FONT...` asks the questions, prints a summary of the choices with what to set up in the system and browsers, waits for Enter (n aborts), and writes the settings;
`fonttune run --config FILE --in-place [--only|--skip steps] FONT...` applies them.
`FONTTUNE_<KEY>` environment variables (e.g. `FONTTUNE_OTF2TTF=true`) answer a question
without asking. `trak` is empty, `strip`, `stat`, `auto` (bake at the GNOME interface font size, read when it runs) or a point size to bake.
`pixel_grid` and `even_spacing` are mutually exclusive.

Repository: `git@github.com:gaou-piou/fonttune.git`
(PKGBUILDs use `https://github.com/gaou-piou/fonttune.git#tag=vX.Y.Z`).

Local testing from a PKGBUILD: `FONTTUNE_DEV=true makepkg -f` (also 1/yes/on). The
`*-hinted` PKGBUILD then copies a local fonttune working tree, uncommitted edits included,
into `$srcdir/fonttune-local` and builds with it: the tree in `FONTTUNE_DEV_DIR`, else the
one set with `bin/fonttune dev set [path]` (default: this tree; saved in
`~/.config/fonttune/dev`, `fonttune dev unset` forgets it, `fonttune dev` shows it), else the
`fonttune` directory next to the package's directory. With none of them it says so and
builds with the git source: a missing tree never stops the build. The build log says
`==> fonttune: LOCAL tree` and the package's `FONTTUNE_REV` reads `local:<commit>[-dirty]`.
Without `FONTTUNE_DEV` (or false; AUR helpers) the PKGBUILDs always use the git source,
whatever is set. `FONTTUNE_REPO`/`FONTTUNE_REF` still pick the git source.

Tests: `python -m pytest tests`.

## Stem darkening: `darken`

`fonttune darken [--ppem 16] [--zero-at 32] [--ink 2.5] FONT [FONT...]`
prints a `FREETYPE_PROPERTIES` line with a darkening curve fitted to the
first font: the text gains `--ink` percent of ink at `--ppem` (default: the
GNOME interface size) and nothing from `--zero-at` (default twice that, the
HiDPI screen) up. FreeType's stock curve adds about 9% at 16 px. The gain
moves in steps of about 1% (FreeType rounds the amount to 1/64 px), so the
closest step wins. It shows the gain at a few sizes for every font given and
any dotted letter (`i`, `ä`, `ΐ`) whose dot merges into the body. It only
affects text drawn with hintslight (cairo/GTK3, GTK4 with hinting on), and
every autofitted or CFF font on the system gets the same curve. Nothing is
written: put the line in `~/.config/environment.d/` yourself. The
measurements use the system FreeType (`fonttune/ftrender.py`); freetype-py
wheels bundle an older one.

## UI size and x-height: `xheight`

`fonttune xheight [--pt 9,10,11] [--mode slight|full] FONT [FONT...]` lists,
for each size, the exact x-height in pixels, the x-height after hinting, and
how much the lowercase changes against the capitals. Under hintslight the
autofitter rounds the x-height to whole pixels and scales the lowercase with
it, so the change depends on the size: Adwaita Sans is +3.0% at 12 pt, -0.2%
at 11 pt and +7.5% at 11.5 pt. Sizes where the x-height and the
lowercase/capital ratio both stay within `--tolerance` (1.5%) are listed as
clean; pick the UI font size from them. Variable fonts with an `opsz` axis
are measured at opsz = the size in points, as Pango draws them. `--mode full`
reads the font's own bytecode (hintmedium/hintfull); fonts without one are
skipped there, FreeType autohints them anyway.

## Variable fonts: `statics` and `fit-weight`

`fonttune statics -o OUT --family NAME [--suffix S] [--weights "300 400 700"]
[--axis TAG=VALUE ...] [--regular-wght N|auto] [--no-scale] VF.ttf...`
cuts static instances (fontTools instancer) and writes RIBBI names, OS/2 and
italic metadata. Pin other axes with `--axis` (`opsz=14`, `slnt=-10`,
`FLAR=100`); `opsz=auto` is the GNOME interface size in points (without
text-scaling-factor, which GTK applies through the resolution), the value
Pango 1.56.2+ gives a variable font's opsz (measured on Pango 1.58: a 12 pt
layout renders pixel for pixel as opsz=12, at 96 and 120 dpi; Roboto Flex at opsz 14 instead has 2.3% less
ink and is 1.2% narrower). Pins outside an axis range are clamped. `--suffix`
adds a width/voice to the family. With
`--regular-wght auto` the Regular is cut at the weight whose horizontal bars
land on whole pixels at 16 ppem (`fonttune fit-weight FONT.ttf` shows the
table), and the lighter weights are re-spaced to match. Run `fonttune run` on
the output afterwards.
