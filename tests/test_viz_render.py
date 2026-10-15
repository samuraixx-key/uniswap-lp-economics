from pathlib import Path

import polars as pl
import pytest
from vizfix import fixture_frames, write_results

from uniswap_lp_economics import cli
from uniswap_lp_economics.viz import data, render, style


def test_load_results_reads_every_input(tmp_path: Path) -> None:
    r = data.load_results(write_results(tmp_path, fixture_frames()))
    assert r.daily["day"].dtype.is_temporal() and r.summary["lp"]["daily"]["days"] == 6
    assert r.jit_block.height == 5 and r.basis_hist.height == 200


def test_missing_inputs_name_the_command(tmp_path: Path) -> None:
    d = write_results(tmp_path, fixture_frames())
    (d / "figure_data" / "jit_block.csv").unlink()
    (d / "markouts.csv").unlink()
    with pytest.raises(FileNotFoundError) as e:
        data.load_results(d)
    msg = str(e.value)
    assert "jit_block.csv missing; run `ulpe lp`" in msg
    assert "markouts.csv missing; run `ulpe analyze`" in msg


def test_old_summary_without_lp_daily_names_the_command(tmp_path: Path) -> None:
    frames = fixture_frames()
    del frames["summary"]["lp"]["daily"]
    with pytest.raises(FileNotFoundError, match=r"lp\.daily.*ulpe lp"):
        data.load_results(write_results(tmp_path, frames))


def test_render_all_writes_both_modes_and_removes_stale_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    d = write_results(tmp_path / "results", fixture_frames())
    out = d / "figures"
    out.mkdir()
    (out / "7_lp_fees_vs_lvr_daily.png").write_bytes(b"old")
    (out / "notes.txt").write_text("keep")

    def tiny(r: data.Results):  # type: ignore[no-untyped-def]
        fig, ax = style.new_figure()
        ax.plot([0, 1], [0, 1])
        return fig

    monkeypatch.setattr(render, "FIGURES", [("99_tiny", tiny)])
    monkeypatch.setattr(render, "EXTRAS", [])
    written = render.render_all(d, out, preview_dir=tmp_path / "preview")
    assert sorted(p.name for p in written) == ["99_tiny-dark.svg", "99_tiny.svg"]
    assert not (out / "7_lp_fees_vs_lvr_daily.png").exists()  # stale figure file removed
    assert (out / "notes.txt").exists()  # only figure files are cleaned
    assert sorted(p.name for p in (tmp_path / "preview").iterdir()) == [
        "99_tiny-dark.png",
        "99_tiny.png",
    ]


@pytest.mark.parametrize("stem", [stem for stem, _ in render.FIGURES])
def test_every_figure_renders_deterministically_in_both_modes(tmp_path: Path, stem: str) -> None:
    r = data.load_results(write_results(tmp_path, fixture_frames()))
    fn = dict(render.FIGURES)[stem]
    for mode in style.MODES:
        with style.theme(mode):
            a = style.svg_bytes(fn(r))
        with style.theme(mode):
            b = style.svg_bytes(fn(r))
        assert a == b and b"<dc:date>" not in a, (stem, mode)


def test_cli_figures_turns_a_missing_input_into_a_clean_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli.config, "RESULTS_DIR", tmp_path)
    with pytest.raises(SystemExit, match="ulpe analyze"):
        cli.run_step("figures", False)


@pytest.mark.parametrize("stem", [stem for stem, _ in render.FIGURES])
def test_subtitles_leave_no_stranded_words(tmp_path: Path, stem: str) -> None:
    r = data.load_results(write_results(tmp_path, fixture_frames()))
    with style.theme("light"):
        fig = dict(render.FIGURES)[stem](r)
        [subtitle] = [t for t in fig.texts if t.get_gid() == "subtitle"]
        lines = subtitle.get_text().split("\n")
        style.svg_bytes(fig)
    assert all(len(line) >= 30 for line in lines[:-1]), (stem, lines)


def test_header_only_tables_keep_their_types(tmp_path: Path) -> None:
    frames = fixture_frames()
    for key in ("episodes", "episode_blocks", "episode_cex", "jit_block", "bot_profit"):
        frames[key] = frames[key].head(0)
    r = data.load_results(write_results(tmp_path, frames))
    assert r.episodes["threshold_bp"].dtype == pl.Float64
    for stem, fn in render.FIGURES:
        with style.theme("light"):
            style.svg_bytes(fn(r)), stem
