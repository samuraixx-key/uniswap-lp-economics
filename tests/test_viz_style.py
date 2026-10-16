from pathlib import Path

import matplotlib.pyplot as plt
import pytest

from uniswap_lp_economics.viz import style


def test_usd_formats_like_the_readme() -> None:
    assert style.usd(1_097_836.3) == "$1.1M"
    assert style.usd(-201_569.9) == "−$202k"
    assert style.usd(3_562.6) == "$3.6k"
    assert style.usd(40.4) == "$40"
    assert style.usd(-0.2) == "$0"  # no minus sign on a value that rounds to zero
    assert style.pct(0.4772) == "48%"
    assert style.per_10k_month(-1.35) == pytest.approx(-40.5)


def test_only_the_light_palette_defines_every_token() -> None:
    assert style.MODES == ("light",)
    fields = set(style.Palette.__dataclass_fields__)
    for mode in style.MODES:
        p = style.PALETTES[mode]
        assert {f for f in fields if getattr(p, f).startswith("#")} == fields


def test_theme_sets_inter_and_the_palette() -> None:
    with style.theme("light") as p:
        assert style.pal() is p is style.PALETTES["light"]
        assert plt.rcParams["font.family"] == ["Inter"]
        assert plt.rcParams["svg.fonttype"] == "path"
    with pytest.raises(RuntimeError, match="theme"):
        style.pal()
    with pytest.raises(ValueError, match="mode"), style.theme("sepia"):
        pass


def test_missing_font_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(style, "FONT_DIR", tmp_path)
    with pytest.raises(FileNotFoundError, match="Inter-Regular.ttf"):
        style.register_fonts()


def test_svg_is_deterministic_and_undated() -> None:
    def draw() -> bytes:
        with style.theme("light"):
            fig, ax = style.new_figure()
            ax.plot([0, 1], [0, 1])
            style.frame(fig, "Title", "Subtitle", "Source")
            return style.svg_bytes(fig)

    a, b = draw(), draw()
    assert a == b
    assert b"<dc:date>" not in a and a.startswith(b"<?xml")


def test_dollar_amounts_are_not_read_as_math() -> None:
    with style.theme("light"):
        fig, _ = style.new_figure()
        style.frame(
            fig,
            "A $1.1M gap",
            "LP fees − LVR: −$80 (95% interval −$110 to −$50), short by $35",
            "$1",
        )
        style.svg_bytes(fig)  # raises ValueError from mathtext if "$...$" is parsed


def test_frame_wraps_long_subtitle_and_source_lines() -> None:
    with style.theme("light"):
        fig, _ = style.new_figure()
        style.frame(fig, "Title", "word " * 60 + "\nsecond paragraph", "note " * 60)
        texts = [t.get_text() for t in fig.texts]
    subtitle, source = texts[1], texts[2]
    assert max(len(line) for line in subtitle.split("\n")) <= style.SUBTITLE_CHARS
    assert subtitle.endswith("\nsecond paragraph")  # explicit breaks are kept
    assert max(len(line) for line in source.split("\n")) <= style.SOURCE_CHARS


def test_frame_reserves_space_for_a_wrapped_header_and_footer() -> None:
    with style.theme("light"):
        fig, ax = style.new_figure(size=(8.0, 6.2))
        style.frame(
            fig,
            "A long chart title that should wrap instead of running beyond the canvas edge",
            "A detailed subtitle describing the comparison and its uncertainty. " * 3,
            "Source and a caveat that need their own space below the chart. " * 3,
        )
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        boxes = {t.get_gid(): t.get_window_extent(renderer) for t in fig.texts}
        assert boxes["title"].y0 > boxes["subtitle"].y1
        assert boxes["subtitle"].y0 > ax.get_window_extent(renderer).y1
        assert boxes["source"].y1 < ax.get_window_extent(renderer).y0
        assert all(box.x0 >= 0 and box.x1 <= fig.bbox.width for box in boxes.values())
        assert fig.texts[0].get_position()[0] == fig.texts[1].get_position()[0]
    plt.close(fig)
