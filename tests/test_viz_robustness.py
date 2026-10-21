from pathlib import Path
from typing import Any

from matplotlib.text import Text
from vizfix import fixture_frames, write_results

from uniswap_lp_economics.viz import data, robustness, style


def test_title_claims_the_crossing_only_when_the_data_supports_it() -> None:
    claim = robustness.title({"a": -3.3, "b": -3.9}, 0.9, True)
    assert claim == "LPs lose at every reference unless prices are read 3.3 s before the slot"
    assert robustness.title({"a": None, "b": None}, 0.9, True).startswith(
        "LPs lose at every reference and every offset"
    )
    assert robustness.title({"a": -1.0}, 0.9, False).startswith("Whether LPs lose")
    assert robustness.title({"a": 1.2}, 0.9, True).startswith("Whether LPs lose")  # after 0 s
    assert robustness.title({"a": -3.0}, None, True).endswith("read 3.0 s before the slot")


def render(tmp_path: Path, frames: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
    r = data.load_results(write_results(tmp_path, frames))
    with style.theme("light"):
        fig = robustness.reference_and_timing(r)
        style.svg_bytes(fig)
    framed = {t.get_gid(): t.get_text() for t in fig.texts if t.get_gid()}
    return framed, [t.get_text() for t in fig.findobj(Text)]


def test_figure_draws_the_timing_band_and_names_its_relays(tmp_path: Path) -> None:
    framed, texts = render(tmp_path, fixture_frames())
    assert framed["title"].endswith("read 2.8 s before the slot")
    assert "Titan, Flashbots and Aestus" in framed["source"].replace("\n", " ")
    assert any("winning bids" in t for t in texts)
    assert any("protocol fee cut" in t for t in texts)
    assert any(t.startswith("Binance trade-side mid") for t in texts)


def test_figure_renders_without_timing(tmp_path: Path) -> None:
    frames = fixture_frames()
    frames["summary"]["lp"]["robustness"]["timing"] = {
        "n_timed": 0,
        "n_queried": 1000,
        "p10_ms": None,
        "p50_ms": None,
        "p90_ms": None,
        "by_relay": [],
    }
    frames["summary"]["lp"]["robustness"]["fees_minus_lvr_at_median_timing_usd"] = None
    framed, texts = render(tmp_path, frames)
    assert not any("winning bids" in t for t in texts)
    assert "No winning-bid times" in framed["source"].replace("\n", " ")
