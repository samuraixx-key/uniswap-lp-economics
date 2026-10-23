"""The MkDocs hook serves figures from results/ (the site pages keep GitHub-correct paths)."""

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "mkdocs_hooks", Path(__file__).resolve().parents[1] / "scripts" / "mkdocs_hooks.py"
)
assert _spec and _spec.loader
hooks = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hooks)


def test_strips_one_level_for_figures() -> None:
    assert (
        hooks.site_figure_paths("![a](../../results/figures/04_markouts.svg)")
        == "![a](../results/figures/04_markouts.svg)"
    )
    assert (
        hooks.site_figure_paths("![a](../results/figures/00_hero.svg)")
        == "![a](results/figures/00_hero.svg)"
    )
    assert (
        hooks.site_figure_paths('<img src="../../results/figures/x.svg">')
        == '<img src="../results/figures/x.svg">'
    )


def test_leaves_other_links_alone() -> None:
    md = (
        "[t](../how/limitations.md) ![b](https://x/results/figures/a.svg) "
        "`../../results/figures/a.svg`"
    )
    assert hooks.site_figure_paths(md) == md
