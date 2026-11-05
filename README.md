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

`fonttune configure --save-to FILE FONT...` asks the questions and writes the settings;
`fonttune run --config FILE --in-place [--only|--skip steps] FONT...` applies them.
`FONTTUNE_<KEY>` environment variables (e.g. `FONTTUNE_OTF2TTF=true`) answer a question
without asking. `trak` is empty, `strip`, `stat` or a point size to bake.
`pixel_grid` and `even_spacing` are mutually exclusive.

Repository: `git@github.com:gaou-piou/fonttune.git`
(PKGBUILDs use `https://github.com/gaou-piou/fonttune.git#tag=vX.Y.Z`).

Local testing from a PKGBUILD: `FONTTUNE_REPO=file:///path/to/fonttune makepkg -f`.

Tests: `python -m pytest tests`.
