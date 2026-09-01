"""Chronoscope invariants — the registries, the SVG, and the a11y contract.

The scope dropdown is driven by TIMELINES while the clickable branches are
driven by _BRANCHES/_BRANCHES_SM: a typo'd key in any of them produces a
branch that clicks but never matches the dropdown, and nothing else would
catch it.
"""
import re

from src.ui.chronoscope import (
    _BRANCHES,
    _BRANCHES_SM,
    TIMELINES,
    chronoscope_svg,
)


def _ids(svg: str) -> set[str]:
    return set(re.findall(r'id="([^"]+)"', svg))


def _data_keys(svg: str) -> set[str]:
    return set(re.findall(r'data-key="([^"]+)"', svg))


def test_branch_registries_match_timelines() -> None:
    tl_keys = {t["key"] for t in TIMELINES}
    for branches in (_BRANCHES, _BRANCHES_SM):
        keys = {b["key"] for b in branches}
        assert keys <= tl_keys, f"branch keys not in TIMELINES: {keys - tl_keys}"
    # every timeline except the spine itself renders as a branch in both scenes
    spine = {"mcu"}
    for branches in (_BRANCHES, _BRANCHES_SM):
        keys = {b["key"] for b in branches}
        assert tl_keys - spine <= keys, f"timelines without a branch: {tl_keys - spine - keys}"


def test_both_scenes_render_every_branch_and_unique_defs() -> None:
    desktop, mobile = chronoscope_svg(False), chronoscope_svg(True)
    tl_keys = {t["key"] for t in TIMELINES}
    assert _data_keys(desktop) == tl_keys
    assert _data_keys(mobile) == tl_keys

    # desktop + compact mount into ONE document: ids must not collide and
    # every url(#…) must resolve within its own scene
    ids = _ids(desktop) | _ids(mobile)
    assert len(re.findall(r'id="[^"]+"', desktop + mobile)) == len(ids), "duplicate def ids"
    for svg in (desktop, mobile):
        refs = set(re.findall(r"url\(#([^)]+)\)", svg))
        assert refs <= ids, f"dangling refs: {refs - ids}"


def test_pruned_vs_live_branch_a11y() -> None:
    desktop = chronoscope_svg(False)
    for m in re.finditer(r'<g class="branch-g[^"]*"([^>]*)>', desktop):
        attrs = m.group(1)
        pruned = 'data-pruned="1"' in attrs
        assert ('role="button"' in attrs) != pruned, f"wrong role: {attrs}"
        if pruned:
            assert 'aria-disabled="true"' in attrs and "tabindex" not in attrs
        else:
            assert 'tabindex="0"' in attrs
