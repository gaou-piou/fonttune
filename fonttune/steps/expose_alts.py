#!/usr/bin/env python3
"""Turn alternates that only 'aalt' reaches into one cvXX feature per character.

Why this exists
---------------
Some fonts draw alternate letters (Google Sans: a single-storey a, a J with
a top bar, a slashed zero, ...) but put them only in 'aalt', the "access all
alternates" bucket meant for a glyph picker. No renderer turns aalt on for
text, and turning it on swaps EVERY alternate at once: there is no way to ask
for just the single-storey a. So these glyphs are unreachable from
fontconfig, CSS or make_features.py (which refuses aalt).

This script reads aalt and, for every glyph whose alternate no other feature
reaches, adds a Character Variant feature per base character:

    cv01  G  -> G.alt   (plus Gbreve, Gcircumflex, ... -> their .alt)
    cv02  I  -> I.alt
    ...

Grouping: accented letters go with their base letter (aacute with a), a
letter whose base has no alternate goes with the mark that has one
(ccedilla with cedilla), and a ligature goes with the one component that has
an alternate (f_t with t). The numbering is fixed by the characters: capitals,
then small letters, then digits, then everything else, each in code point
order, counted from after the font's own highest cvXX. All fonts given in one
call share it, so cv05 is the same letter in Regular and in Bold.

The new lookups go at the END of the lookup list, so they act on what the
other features already did: f+t has become f_t (liga), zero has become
zero.cap (case). For such a form the matching alternate is used
(zero.cap -> zero.alt.cap); when the font has none, the aalt pick is used only
if it keeps the advance width, so tabular figures, numerators and the like
are left alone instead of turning into a wider or full-size glyph.

The features are off by default, like every cvXX; turn them on with
fontconfig ("cv03"), CSS (font-feature-settings: "cv03") or bake them into
calt with make_features.py. Each one carries its characters and a UI name
("Alternate a"), so font pickers can show them.

Usage
-----
    expose_alts.py --list FONT...     show what would be added, change nothing
    expose_alts.py FONT...            add the features (in place)
"""
import argparse
import os
import re
import sys
import unicodedata

from fontTools.ttLib import TTFont
from fontTools.ttLib.tables import otTables

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_features import add_target, sort_feature_list  # noqa: E402

# Combining marks -> the spacing character a font draws them as.
MARKS = {
    ("̧",): "¸",           # cedilla
    ("̌",): "ˇ",           # caron
    ("̈", "́"): "΅",  # Greek dialytika tonos
}
LATIN = re.compile(r"^LATIN (SMALL|CAPITAL) LETTER ([A-Z]+)(?: WITH .*)?$")


def subtables(lookup):
    for st in lookup.SubTable:
        yield (st.ExtSubTable if lookup.LookupType == 7 else st)


def scan(font):
    """-> ({src: [alternates]} reached only through aalt, set of cv tags in the font)."""
    if "GSUB" not in font:
        return {}, set()
    g = font["GSUB"].table
    if not g.FeatureList or not g.LookupList:
        return {}, set()
    aalt, used, reached = set(), set(), set()
    tags = {fr.FeatureTag for fr in g.FeatureList.FeatureRecord}
    for fr in g.FeatureList.FeatureRecord:
        (aalt if fr.FeatureTag == "aalt" else used).update(fr.Feature.LookupListIndex)
    # lookups called from contextual lookups of other features count as reached
    todo = list(used)
    while todo:
        for st in subtables(g.LookupList.Lookup[todo.pop()]):
            for attr in ("SubstLookupRecord", "SubstLookupRecords"):
                for rec in getattr(st, attr, None) or []:
                    if rec.LookupListIndex not in used:
                        used.add(rec.LookupListIndex)
                        todo.append(rec.LookupListIndex)
            for rs in getattr(st, "ChainSubRuleSet", None) or getattr(st, "SubRuleSet", None) or []:
                for r in (getattr(rs, "ChainSubRule", None) or getattr(rs, "SubRule", None) or []):
                    for rec in r.SubstLookupRecord:
                        if rec.LookupListIndex not in used:
                            used.add(rec.LookupListIndex)
                            todo.append(rec.LookupListIndex)
    for i in used - aalt:
        for st in subtables(g.LookupList.Lookup[i]):
            # single: glyph; multiple (type 2): list of glyphs
            for v in (getattr(st, "mapping", None) or {}).values():
                reached.update([v] if isinstance(v, str) else v)
            for v in (getattr(st, "alternates", None) or {}).values():
                reached.update(v)
            for ligs in (getattr(st, "ligatures", None) or {}).values():
                reached.update(l.LigGlyph for l in ligs)
    found = {}
    for i in aalt - used:
        for st in subtables(g.LookupList.Lookup[i]):
            pairs = [(k, [v]) for k, v in (getattr(st, "mapping", None) or {}).items()
                     if isinstance(v, str)]
            pairs += list((getattr(st, "alternates", None) or {}).items())
            for src, alts in pairs:
                alts = [a for a in alts if a != src and a not in reached
                        and ".alt" in a and ".alt" not in src]
                if alts:
                    found.setdefault(src, [])
                    found[src] += [a for a in alts if a not in found[src]]
    for src in found:  # .alt before .alt2 before .alt3
        found[src].sort(key=lambda a: (len(a), a))
    return found, {t for t in tags if re.fullmatch(r"cv\d\d", t)}


def pick(font, src, alts):
    """The alternates of src that fit where src stands, or [] to leave it."""
    if "." not in src:
        return alts
    base, sfx = src.split(".", 1)
    order = font.getGlyphOrder()
    own = [f"{a.split('.', 1)[0]}.{a.split('.', 1)[1]}.{sfx}" for a in alts]
    own = [a for a in own if a in set(order)]
    if own:
        return own
    hmtx = font["hmtx"].metrics
    return [a for a in alts if hmtx[a][0] == hmtx[src][0]]


def fold(c, primary):
    """The other character c belongs with (aacute -> a, tbar -> t,
    ccedilla -> cedilla), or None."""
    nfd = unicodedata.normalize("NFD", c)
    if nfd[0] != c and nfd[0] in primary:
        return nfd[0]
    m = LATIN.match(unicodedata.name(c, ""))
    if m:  # tbar -> t, ae -> a
        letter = m.group(2)[0]
        letter = letter.lower() if m.group(1) == "SMALL" else letter
        if letter != c and letter in primary:
            return letter
    mark = MARKS.get(tuple(nfd[1:]))
    return mark if mark in primary else None


def group_of(src, chars, primary):
    """The character whose cvXX src belongs to (str), or None."""
    base = src.split(".", 1)[0]
    if "_" in base:  # ligature: the one component that has an alternate
        parts = set()
        for p in base.split("_"):
            c = chars.get(p, p)
            parts.add(c if c in primary else fold(c, primary) if len(c) == 1 else None)
        parts -= {None}
        return parts.pop() if len(parts) == 1 else None
    c = chars.get(base)
    if c is None:
        return base
    return fold(c, primary) or c


def rank(key):
    if len(key) != 1:
        return (4, 0, key)
    cat = unicodedata.category(key)
    return ({"Lu": 0, "Ll": 1, "Nd": 2}.get(cat, 3), ord(key), key)


def plan(fonts):
    """-> ({font: {group: {src: [alts]}}}, [(tag, group)]) shared by all fonts."""
    per, have = {}, set()
    for font in fonts:
        found, cvs = scan(font)
        have |= cvs
        cmap = font.getBestCmap() or {}
        chars = {}
        for cp, gn in sorted(cmap.items()):
            chars.setdefault(gn, chr(cp))
        # a character is a group of its own when its plain glyph has an
        # alternate and it does not fold into another such character
        cand = {chars[s] for s in found if s in chars}
        primary = {c for c in cand if fold(c, cand) is None}
        groups = {}
        for src, alts in found.items():
            g = group_of(src, chars, primary)
            alts = pick(font, src, alts)
            if g is not None and alts:
                groups.setdefault(g, {})[src] = alts
        per[font] = groups
    keys = sorted({g for groups in per.values() for g in groups}, key=rank)
    start = max([int(t[2:]) for t in have] or [0]) + 1
    if start + len(keys) - 1 > 99:
        keys = keys[:max(0, 100 - start)]
        print(f"expose_alts: only {len(keys)} cvXX tags are free; the rest is left out")
    return per, [(f"cv{start + i:02d}", k) for i, k in enumerate(keys)]


def label(key):
    return f"Alternate {key}"


def add_name(font, text):
    name = font["name"]
    return name.addMultilingualName({"en": text}, ttFont=font, mac=False)


def apply(font, groups, tags):
    g = font["GSUB"].table
    for tag, key in tags:
        subst = groups.get(key)
        if not subst:
            continue
        lk = otTables.Lookup()
        lk.LookupFlag = 0
        multi = any(len(v) > 1 for v in subst.values())
        st = otTables.AlternateSubst() if multi else otTables.SingleSubst()
        if multi:
            st.alternates = {k: list(v) for k, v in subst.items()}
            lk.LookupType = 3
        else:
            st.mapping = {k: v[0] for k, v in subst.items()}
            lk.LookupType = 1
        lk.SubTable = [st]
        lk.SubTableCount = 1
        g.LookupList.Lookup.append(lk)
        g.LookupList.LookupCount = len(g.LookupList.Lookup)
        idx = add_target(g, tag)
        fr = g.FeatureList.FeatureRecord[idx]
        fr.Feature.LookupListIndex = [g.LookupList.LookupCount - 1]
        fr.Feature.LookupCount = 1
        p = otTables.FeatureParamsCharacterVariants()
        p.Format = 0
        p.FeatUILabelNameID = add_name(font, label(key))
        p.FeatUITooltipTextNameID = 0
        p.SampleTextNameID = 0
        p.NumNamedParameters = 0
        p.FirstParamUILabelNameID = 0
        p.Character = [ord(key)] if len(key) == 1 else []
        p.CharCount = len(p.Character)
        fr.Feature.FeatureParams = p
    sort_feature_list(g)


def describe(groups, tags):
    rows = []
    for tag, key in tags:
        subst = {}
        for gr in groups:
            subst.update(gr.get(key, {}))
        if not subst:
            continue
        forms = max(len(v) for v in subst.values())
        extra = sorted(s for s in subst if s.split(".")[0] != key)
        rows.append(f"  {tag}  {key!s:<3} {len(subst):3} glyph(s)"
                    + (f", {forms} forms (value 1..{forms})" if forms > 1 else "")
                    + (f"  [{' '.join(extra[:6])}{' ...' if len(extra) > 6 else ''}]"
                       if extra else ""))
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--list", action="store_true", help="show the plan, change nothing")
    ap.add_argument("fonts", nargs="+")
    a = ap.parse_args()
    fonts = [TTFont(p) for p in a.fonts]
    per, tags = plan(fonts)
    if not tags:
        print("expose_alts: no alternates hidden in aalt; fonts left as they are")
        return
    print("expose_alts: alternates only aalt reached, now one feature per character:")
    print("\n".join(describe(per.values(), tags)))
    if a.list:
        return
    for path, font in zip(a.fonts, fonts):
        if per[font]:
            apply(font, per[font], tags)
            font.save(path)


if __name__ == "__main__":
    main()
