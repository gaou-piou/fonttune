# fonttune

One pipeline of font-tuning steps for the `*-hinted` packages (not on the AUR;
PKGBUILDs fetch it as a git source pinned to a tag).

    fonttune steps
    fonttune run --profile clean --pixel-grid 14.6667 -o out/ fonts/*.ttf
    fonttune run --dry-run ...        # print the plan only

Inputs are copied to `-o` first; steps edit the copies. A `fonttune.json` in
the output records the version and the steps applied.

Order: otf2ttf, weights, trak, even_spacing | pixel_grid, features, gasp.
`pixel_grid` and `even_spacing` are mutually exclusive.

Local testing from a PKGBUILD: `FONTTUNE_REPO=file:///path/to/fonttune makepkg -f`.

Tests: `python -m pytest tests`.
