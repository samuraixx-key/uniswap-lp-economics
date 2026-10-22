from datetime import date

import numpy as np
import polars as pl
import pytest

from uniswap_lp_economics.lp import theory
from uniswap_lp_economics.strategy import stats
from uniswap_lp_economics.strategy.stats import Paired


def _paired(lo: float, hi: float, delta: float = 0.07) -> Paired:
    mid = np.linspace(lo, hi, 1000)
    return stats.paired(mid, np.zeros(1000), 0.0, delta)


def test_index_matches_theory():
    idx = stats.day_index(61)
    assert idx.shape == (theory.N_BOOT, 61)
    rng = np.random.default_rng(theory.SEED)
    first = rng.integers(0, 61, size=(theory.N_BOOT, 61))[0]
    assert (idx[0] == first).all()


def test_on_grid_zero_fills():
    days = [date(2026, 8, 1), date(2026, 8, 2), date(2026, 8, 3)]
    daily = pl.DataFrame({"day": [date(2026, 8, 3), date(2026, 8, 1)], "fees": [3.0, 1.0]})
    out = stats.on_grid(daily, days, ["fees"])
    assert out["day"].to_list() == days
    assert out["fees"].to_list() == [1.0, 0.0, 3.0]


def test_ratio_draws_nan_where_den_not_positive():
    idx = np.array([[0, 0], [1, 1]])
    out = stats.ratio_draws(np.array([2.0, 3.0]), np.array([4.0, 0.0]), idx)
    assert out[0] == 0.5
    assert np.isnan(out[1])


def test_undefined_draws():
    delta = 0.07
    a = np.zeros(1000)
    b = np.zeros(1000)
    a[:30] = np.nan  # 3% undefined
    assert stats.paired(a, b, 0.0, delta).inside is False
    a = np.zeros(1000)
    a[:20] = np.nan  # 2% undefined
    p = stats.paired(a, b, 0.0, delta)
    assert p.inside is True
    assert p.n_undefined == 20
    # nan draws never make "above" true, even when defined draws sit above
    a = np.full(1000, 0.5)
    a[:30] = np.nan
    assert stats.paired(a, b, 0.5, delta).above is True
    a = np.full(1000, np.nan)
    p = stats.paired(a, b, 0.0, delta)
    assert (p.above, p.below, p.inside) == (False, False, False)


def test_verdicts():
    inside = _paired(-0.02, 0.02)
    above = _paired(0.1, 0.2)
    straddle = _paired(0.0, 0.2)
    assert stats.range_verdict({"a": inside, "b": inside, "c": inside}) == "holds"
    assert stats.range_verdict({"a": inside, "b": above}) == "fails"
    assert stats.range_verdict({"a": inside, "b": straddle}) == "inconclusive"
    below = _paired(-0.3, -0.1)
    levels = {1.0: below, 5.0: inside, 10.0: straddle, 20.0: above, 30.0: above}
    per, summary = stats.fee_verdicts(levels, True)
    assert 5.0 not in per
    assert per[1.0] == "not tested (below baseline)"
    assert per[10.0] == "inconclusive"
    assert per[20.0] == "holds"
    assert summary == "holds from 20 bp"
    assert stats.fee_verdicts({10.0: below}, True) == ({10.0: "fails"}, "fails")
    assert stats.fee_verdicts(levels, False)[1] == "not tested (calibration failed)"


def test_delta():
    assert stats.delta_from(0.72) == pytest.approx(0.07)
    with pytest.raises(ValueError, match="broke even"):
        stats.delta_from(1.0)


def test_break_even():
    assert stats.break_even_fee([5, 10, 20], [0.8, 0.9, 1.1]) == pytest.approx(15.0)
    assert stats.break_even_fee([5, 10], [0.8, 0.9]) is None
    assert stats.break_even_fee([5, 10], [1.2, 0.9]) == 5
    assert stats.interp([0.0, 10.0], [0.0, 1.0], 5.0) == pytest.approx(0.5)
    assert stats.break_even_share(1.0, 0.0, 4.0, 2.0) == 0.5
    assert stats.break_even_share(1.0, 0.0, 2.0, 2.0) is None
    assert stats.protocol_cut(75.0, 0.0) == 100.0
    assert stats.PROTOCOL_CUTS == (0.0, 0.1, 0.25)
