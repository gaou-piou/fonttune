# fonttune

One pipeline of font-tuning steps for the `*-hinted` packages (not on the AUR;
PKGBUILDs fetch it as a git source pinned to a tag).

    fonttune steps
    fonttune run --profile clean --pixel-grid 14.6667 -o out/ fonts/*.ttf
    fonttune run --dry-run ...        # print the plan only

Inputs are copied to `-o` first; steps edit the copies. A `fonttune.json` in
the output records the version and the steps applied.

Order: weights, trak, otf2ttf, even_spacing | pixel_grid, hint, features, gasp.

`hint` runs ttfautohint (presets balanced, sharp, natural, light; `--hint-mode/-min/-max/-limit/-xheight/-xsnap` override) and adds otf2ttf when it gets OTFs. FreeType runs the bytecode only at hintmedium/hintfull, so under hintslight it changes nothing; `configure` reads the desktop hint style and preselects `no` there. `fonttune hintconf -o 80-x.conf FONT...` writes the fontconfig snippet that enables bytecode hinting for those families (Chromium/Electron excluded).

`fonttune configure --save-to FILE FONT...` asks the questions, prints a summary of the choices with what to set up in the system and browsers, waits for Enter (n aborts), and writes the settings;
`fonttune run --config FILE --in-place [--only|--skip steps] FONT...` applies them.
`FONTTUNE_<KEY>` environment variables (e.g. `FONTTUNE_OTF2TTF=true`) answer a question
without asking. `trak` is empty, `strip`, `stat` or a point size to bake.
`pixel_grid` and `even_spacing` are mutually exclusive.

Repository: `git@github.com:gaou-piou/fonttune.git`
(PKGBUILDs use `https://github.com/gaou-piou/fonttune.git#tag=vX.Y.Z`).

Local testing from a PKGBUILD: run `bin/fonttune dev on` once in this tree. Every
`*-hinted` PKGBUILD then copies this working tree, uncommitted edits included, into
`$srcdir/fonttune-local` and builds with it; the build log says `==> fonttune: LOCAL tree`
and the package's `FONTTUNE_REV` reads `local:<commit>[-dirty]`. `fonttune dev off`
goes back to the git source, `fonttune dev` shows which one is active.
For one build only: `FONTTUNE_DEV=/path/to/fonttune makepkg -f` (or `FONTTUNE_DEV=off`
to ignore the saved tree). `FONTTUNE_REPO`/`FONTTUNE_REF` still pick the git source.

Tests: `python -m pytest tests`.

## Variable fonts: `statics` and `fit-weight`

`fonttune statics -o OUT --family NAME [--suffix S] [--weights "300 400 700"]
[--axis TAG=VALUE ...] [--regular-wght N|auto] [--no-scale] VF.ttf...`
cuts static instances (fontTools instancer) and writes RIBBI names, OS/2 and
italic metadata. Pin other axes with `--axis` (`opsz=14`, `slnt=-10`,
`FLAR=100`); `--suffix` adds a width/voice to the family. With
`--regular-wght auto` the Regular is cut at the weight whose horizontal bars
land on whole pixels at 16 ppem (`fonttune fit-weight FONT.ttf` shows the
table), and the lighter weights are re-spaced to match. Run `fonttune run` on
the output afterwards.
