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


def test_both_palettes_define_every_token() -> None:
    fields = set(style.Palette.__dataclass_fields__)
    for mode in style.MODES:
        p = style.PALETTES[mode]
        assert {f for f in fields if getattr(p, f).startswith("#")} == fields


def test_theme_sets_inter_and_the_palette() -> None:
    with style.theme("dark") as p:
        assert style.pal() is p is style.PALETTES["dark"]
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
