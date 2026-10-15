from pathlib import Path

import pytest
from PIL import Image
from vizfix import fixture_frames, write_results

from uniswap_lp_economics.viz import data, hero, render, style


def test_hero_first_and_card_registered() -> None:
    assert render.FIGURES[0][0] == "00_hero"
    assert hero.social_card in render.EXTRAS


def test_negative_kept_becomes_a_source_and_flows_balance() -> None:
    d = fixture_frames()["summary"]["lp"]["destination"]
    src, dst = hero.flows(d, style.PALETTES["light"])
    assert [s[0] for s in src][1].startswith("Paid by searchers")
    assert sum(s[1] for s in src) == pytest.approx(sum(t[1] for t in dst))
    split = hero.pieces(src, dst)
    assert sum(a for _, _, a in split) == pytest.approx(106.0)
    assert split[-1][0] == 1  # the searchers' own money flows to the last destinations


def test_positive_kept_and_negative_flow_still_balance() -> None:
    d = dict(fixture_frames()["summary"]["lp"]["destination"])
    # sources 100 + 4 (negative multi-pool) = destinations 48 + 16 + 1 + 16 + 19 + 4 (kept)
    d.update(searcher_kept_usd=4.0, multi_pool_gross_usd=-4.0)
    src, dst = hero.flows(d, style.PALETTES["dark"])
    assert any(t[0] == "Searchers kept" for t in dst)
    assert any("negative" in s[0] for s in src)
    assert sum(s[1] for s in src) == pytest.approx(sum(t[1] for t in dst))


def test_unbalanced_destination_raises() -> None:
    d = dict(fixture_frames()["summary"]["lp"]["destination"])
    d["proposer_usd"] = 50.0
    with pytest.raises(ValueError, match="do not balance"):
        hero.flows(d, style.PALETTES["light"])


def test_social_card_is_1280_by_640(tmp_path: Path) -> None:
    r = data.load_results(write_results(tmp_path / "r", fixture_frames()))
    [path] = hero.social_card(r, tmp_path / "out")
    assert path.name == "00_hero.png" and Image.open(path).size == (1280, 640)


def test_ulpe_figures_writes_every_expected_file(tmp_path: Path) -> None:
    d = write_results(tmp_path / "results", fixture_frames())
    written = render.render_all(d, d / "figures")
    names = {p.name for p in written}
    stems = [
        "00_hero",
        "01_what_is_lvr",
        "02_stale_pool_episode",
        "03_pool_follows_binance",
        "04_markouts",
        "05_lvr_vs_volatility",
        "06_cumulative_fees_vs_lvr",
        "07_measured_vs_theory",
        "08_bots_keep",
        "09_every_position",
        "10_pnl_by_group",
        "11_jit_block",
        "12_lifetime",
    ]
    assert [s for s, _ in render.FIGURES] == stems
    expected = {f"{s}.svg" for s in stems} | {f"{s}-dark.svg" for s in stems}
    assert names == expected | {"02_stale_pool_episode.gif", "00_hero.png"}
    assert {p.name for p in (d / "figures").iterdir()} == names
