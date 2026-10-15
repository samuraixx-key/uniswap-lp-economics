from pathlib import Path

from PIL import Image
from vizfix import fixture_frames, write_results

from uniswap_lp_economics.viz import data, render, style, what_is_lvr


def test_registered_in_order() -> None:
    stems = [s for s, _ in render.FIGURES]
    assert stems.index("01_what_is_lvr") < stems.index("02_stale_pool_episode")
    assert what_is_lvr.episode_gif in render.EXTRAS


def test_episode_subtitle_reports_the_window_lvr(tmp_path: Path) -> None:
    r = data.load_results(write_results(tmp_path, fixture_frames()))
    with style.theme("light"):
        fig = what_is_lvr.episode(r)
        texts = " ".join(t.get_text() for t in fig.texts)
    assert "5 blocks" in texts and "$590" in texts  # 300 + 250 + 40


def test_gif_has_one_frame_per_block(tmp_path: Path) -> None:
    r = data.load_results(write_results(tmp_path / "r", fixture_frames()))
    [path] = what_is_lvr.episode_gif(r, tmp_path / "out")
    assert path.name == "02_stale_pool_episode.gif"
    assert Image.open(path).n_frames == 5


def test_empty_episode_renders_and_skips_the_gif(tmp_path: Path) -> None:
    frames = fixture_frames()
    frames["episode_blocks"] = frames["episode_blocks"].head(0)
    r = data.load_results(write_results(tmp_path, frames))
    with style.theme("dark"):
        style.svg_bytes(what_is_lvr.episode(r))
    assert what_is_lvr.episode_gif(r, tmp_path / "out") == []
