from pathlib import Path
from typing import Any

import pytest
from matplotlib.patches import PathPatch, Rectangle
from matplotlib.text import Text
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
    src, dst = hero.flows(d, style.PALETTES["light"])
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
    expected = {f"{s}.svg" for s in stems}
    assert names == expected | {"02_stale_pool_episode.gif", "00_hero.png"}
    assert {p.name for p in (d / "figures").iterdir()} == names


def _hero_texts(fig: Any) -> dict[str, str]:
    return {t.get_gid() or t.get_text(): t.get_text() for t in fig.findobj(Text)}


def test_uncertain_slice_sits_between_builders_and_proposers() -> None:
    d = fixture_frames()["summary"]["lp"]["destination"]
    p = style.PALETTES["light"]
    _, dst = hero.flows(d, p)
    # self-built sensitivity moves $4 from proposers (19 -> 15) to builders (16 -> 20)
    drawn = hero.split_uncertain(dst, moved=-4.0)
    names = [n[0] for n in drawn]
    k = names.index(hero.UNCERTAIN)
    assert names[k - 1] == "Block builders" and names[k + 1] == "Proposers"
    assert [n[1] for n in drawn[k - 1 : k + 2]] == pytest.approx([16.0, 4.0, 15.0])
    assert sum(n[1] for n in drawn) == pytest.approx(sum(n[1] for n in dst))
    # the other direction: the sensitivity gives proposers more
    drawn = hero.split_uncertain(dst, moved=3.0)
    assert [n[1] for n in drawn[k - 1 : k + 2]] == pytest.approx([13.0, 3.0, 19.0])


def test_hero_draws_the_uncertain_slice_hatched_and_touching_both_flows(tmp_path: Path) -> None:
    r = data.load_results(write_results(tmp_path, fixture_frames()))
    with style.theme("light"):
        fig = hero.hero(r)
        nodes = {a.get_gid(): a for a in fig.findobj(Rectangle) if a.get_gid()}
        bands = [a for a in fig.findobj(PathPatch) if a.get_hatch()]
    b, u, q = (nodes[f"node:{n}"] for n in ("Block builders", hero.UNCERTAIN, "Proposers"))
    assert u.get_hatch()
    assert u.get_y() + u.get_height() == pytest.approx(b.get_y())
    assert q.get_y() + q.get_height() == pytest.approx(u.get_y())
    assert len(bands) == 1


def test_tiny_shares_read_under_one_percent(tmp_path: Path) -> None:
    frames = fixture_frames()
    frames["summary"]["lp"]["destination"].update(gas_burned_usd=0.3, multi_pool_gross_usd=6.7)
    r = data.load_results(write_results(tmp_path, frames))
    with style.theme("light"):
        texts = " ".join(t.get_text() for t in hero.hero(r).findobj(Text))
    assert "Gas burned" in texts and "$0 · <1%" in texts
    assert "· 0%" not in texts


def test_footnote_explains_the_second_source_and_the_hatching(tmp_path: Path) -> None:
    r = data.load_results(write_results(tmp_path, fixture_frames()))
    with style.theme("light"):
        source = _hero_texts(hero.hero(r))["source"]
    assert "second source" in source and "hatched" in source.lower()


def _title_share_of_height(fig: Any) -> float:
    fig.canvas.draw()
    [title] = [t for t in fig.texts if t.get_gid() == "title"]
    return float(title.get_window_extent().height / fig.bbox.height)


def test_social_card_text_is_larger_than_the_plain_hero(tmp_path: Path) -> None:
    r = data.load_results(write_results(tmp_path, fixture_frames()))
    with style.theme("light"):
        plain = _title_share_of_height(hero.hero(r, size=(12.8, 6.4)))
        card = _title_share_of_height(hero.card_figure(r))
    assert card >= 1.2 * plain
