from pathlib import Path
from typing import Any

from matplotlib.text import Text
from vizfix import fixture_frames, write_results

from uniswap_lp_economics.viz import data, robustness, style


def test_title_claims_the_crossing_only_when_the_data_supports_it() -> None:
    claim = robustness.title({"a": -3.3, "b": -3.9}, 0.9, True)
    assert (
        claim
        == "LPs lose at every reference unless prices are read more than 3.3 s before the slot"
    )
    assert robustness.title({"a": None, "b": None}, 0.9, True).startswith(
        "LPs lose at every reference and every offset"
    )
    assert robustness.title({"a": -1.0}, 0.9, False).startswith("Whether LPs lose")
    assert robustness.title({"a": 1.2}, 0.9, True).startswith("Whether LPs lose")  # after 0 s
    assert robustness.title({"a": -3.0}, None, True).endswith(
        "read more than 3.0 s before the slot"
    )


def render(tmp_path: Path, frames: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
    r = data.load_results(write_results(tmp_path, frames))
    with style.theme("light"):
        fig = robustness.reference_and_timing(r)
        style.svg_bytes(fig)
    framed = {t.get_gid(): t.get_text() for t in fig.texts if t.get_gid()}
    return framed, [t.get_text() for t in fig.findobj(Text)]


def test_figure_draws_the_timing_band_and_names_its_relays(tmp_path: Path) -> None:
    framed, texts = render(tmp_path, fixture_frames())
    assert framed["title"].endswith("read more than 2.8 s before the slot")
    source = framed["source"].replace("\n", " ")
    assert "Titan, Flashbots or Aestus delivered" in source and "120 of 1,000" in source
    assert "also through ultrasound" in source  # a block can go through several relays
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


def test_title_says_more_than() -> None:
    assert "more than 3.0 s before the slot" in robustness.title({"a": -3.0}, 0.9, True)


def test_reference_lines_look_different_and_labels_point_at_them(tmp_path: Path) -> None:
    from uniswap_lp_economics.lp import robustness as lp_robustness

    r = data.load_results(write_results(tmp_path, fixture_frames()))
    with style.theme("light"):
        fig = robustness.reference_and_timing(r)
        ax = fig.axes[0]
        lines = {ln.get_gid(): ln for ln in ax.get_lines() if ln.get_gid()}
        mid = lines["binance_trade_side_mid"]
        usdt = lines["binance_ethusdt_1s_close"]
        assert (mid.get_color(), mid.get_linestyle()) != (usdt.get_color(), usdt.get_linestyle())
        labels = {
            t.get_text(): t
            for t in ax.texts
            if t.get_text() in lp_robustness.REFERENCE_LABELS.values()
        }
        assert len(labels) == 3
        for name, label in lp_robustness.REFERENCE_LABELS.items():
            ann = labels[label]
            assert ann.arrow_patch is not None  # a leader from the label to its line's end
            assert ann.arrowprops is not None and ann.arrowprops.get("relpos") == (
                0,
                0.5,
            )  # from the text's left edge, not through it
            end = lines[name].get_ydata()[-1]
            assert ann.xy[1] == end


def test_subtitle_names_the_protocol_line_by_its_colour(tmp_path: Path) -> None:
    # two lines are dashed (the protocol cut and the trade-side mid): "Dashed:" was ambiguous
    framed, _ = render(tmp_path, fixture_frames())
    subtitle = " ".join(framed["subtitle"].split())
    assert "Dashed:" not in subtitle and "Purple line: the protocol's fee cut" in subtitle
