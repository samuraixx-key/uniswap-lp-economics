from pathlib import Path

from vizfix import fixture_frames, write_results

from uniswap_lp_economics.viz import bots, data, render, style


def test_registered_after_figure_7() -> None:
    stems = [s for s, _ in render.FIGURES]
    assert stems.index("07_measured_vs_theory") + 1 == stems.index("08_bots_keep")


def test_bots_subtitle_and_bot_rows(tmp_path: Path) -> None:
    r = data.load_results(write_results(tmp_path, fixture_frames()))
    with style.theme("light"):
        fig = bots.bots_keep(r)
        texts = " ".join(t.get_text() for t in fig.texts)
        right = fig.axes[1]
        labels = [t.get_text() for t in right.get_yticklabels()]
    assert "$60" in texts and "−$6" in texts
    assert "TOTAL" not in " ".join(labels) and len(labels) == 2
