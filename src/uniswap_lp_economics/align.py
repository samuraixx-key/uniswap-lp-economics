"""As-of reference prices: the Binance price in force at a time, and how old it is (spec 5.1)."""

from datetime import UTC, datetime, time

import polars as pl

from uniswap_lp_economics.config import HORIZONS_S, US, WINDOW_END


def window_end_us() -> int:
    """End of the study window (exclusive) in µs since the epoch; the Binance data ends there."""
    return int(datetime.combine(WINDOW_END, time(), UTC).timestamp()) * US


def reference_table(trades: pl.DataFrame) -> pl.DataFrame:
    """ETHUSDC trades as a (ts_us, price) reference. Among trades sharing a microsecond, the one
    with the highest Binance aggregated-trade ID (the latest) is the price in force."""
    return (
        trades.sort("ts_us", "agg_trade_id")
        .unique(subset="ts_us", keep="last", maintain_order=True)
        .select("ts_us", "price")
    )


def kline_reference_table(klines: pl.DataFrame, bar_s: int = 1) -> pl.DataFrame:
    """ETHUSDT klines as a reference. A bar's close is only known when the bar ends."""
    return klines.select(ts_us=pl.col("ts_us") + bar_s * US, price=pl.col("close")).sort("ts_us")


def trade_side_table(trades: pl.DataFrame) -> pl.DataFrame:
    """The latest buyer-initiated price (the ask) and seller-initiated price (the bid) in force
    after each microsecond's trades, from Binance's `is_buyer_maker` flag (sub-project 4 spec
    5.1). Times before both sides have traded are dropped. A quiet side goes stale, so the two
    can cross."""
    taker_buy = ~pl.col("is_buyer_maker")
    return (
        trades.sort("ts_us", "agg_trade_id")
        .with_columns(
            ask=pl.when(taker_buy).then(pl.col("price")).forward_fill(),
            bid=pl.when(~taker_buy).then(pl.col("price")).forward_fill(),
        )
        .unique(subset="ts_us", keep="last", maintain_order=True)
        .drop_nulls(["ask", "bid"])
        .select("ts_us", "ask", "bid")
    )


def trade_side_mid_table(trades: pl.DataFrame) -> pl.DataFrame:
    """The trade-side mid proxy as a (ts_us, price) reference: the average of ask and bid."""
    return trade_side_table(trades).select("ts_us", price=(pl.col("ask") + pl.col("bid")) / 2)


def proxy_quality(
    times_us: pl.Series, trades: pl.DataFrame, end_us: int
) -> dict[str, float | None]:
    """How rough the proxy is at the given times: share with ask below bid, spread quantiles
    (bp of the mid) and the mean distance of the last trade from the mid (bp). None when no
    time has both sides."""
    sides = trade_side_table(trades)
    q = pl.DataFrame(
        {
            "ask": reference_at(times_us, sides.select("ts_us", price="ask"), end_us)["price"],
            "bid": reference_at(times_us, sides.select("ts_us", price="bid"), end_us)["price"],
            "last": reference_at(times_us, reference_table(trades), end_us)["price"],
        }
    ).drop_nulls()
    if q.height == 0:
        return dict.fromkeys(QUALITY_KEYS)
    mid = (q["ask"] + q["bid"]) / 2
    spread = (q["ask"] - q["bid"]) / mid * 1e4
    return {
        "crossed_share": float((spread < 0).mean()),  # type: ignore[arg-type]
        "spread_bp_p10": float(spread.quantile(0.1)),  # type: ignore[arg-type]
        "spread_bp_p50": float(spread.quantile(0.5)),  # type: ignore[arg-type]
        "spread_bp_p90": float(spread.quantile(0.9)),  # type: ignore[arg-type]
        "mean_abs_last_minus_mid_bp": float(((q["last"] - mid).abs() / mid * 1e4).mean()),  # type: ignore[arg-type]
    }


QUALITY_KEYS = (
    "crossed_share",
    "spread_bp_p10",
    "spread_bp_p50",
    "spread_bp_p90",
    "mean_abs_last_minus_mid_bp",
)


def reference_at(times_us: pl.Series, ref: pl.DataFrame, end_us: int) -> pl.DataFrame:
    """Last reference price at or before each time, and its age in seconds, in input order.

    Both are null for times before the first reference point or at/after `end_us` (the data
    ends there, so the last price would be stale, not current).
    """
    query = pl.DataFrame({"t_us": times_us.cast(pl.Int64)}).with_row_index("_i").sort("t_us")
    joined = query.join_asof(
        ref.rename({"ts_us": "ref_ts_us"}).sort("ref_ts_us"),
        left_on="t_us",
        right_on="ref_ts_us",
        strategy="backward",
    ).sort("_i")
    valid = pl.col("ref_ts_us").is_not_null() & (pl.col("t_us") < end_us)
    return joined.select(
        price=pl.when(valid).then(pl.col("price")),
        age_s=pl.when(valid).then((pl.col("t_us") - pl.col("ref_ts_us")) / US),
    )


def add_reference_prices(
    df: pl.DataFrame,
    ref: pl.DataFrame,
    end_us: int,
    horizons: tuple[int, ...] = HORIZONS_S,
    shift_s: float = 0.0,
) -> pl.DataFrame:
    """Add t0_us (block time + shift) and p_cex_{h} / cex_age_s_{h} at t0 + h for each horizon."""
    t0 = df["block_timestamp"].dt.epoch("us") + int(round(shift_s * US))
    out = df.with_columns(t0_us=t0)
    for h in horizons:
        r = reference_at(t0 + h * US, ref, end_us)
        out = out.with_columns(r["price"].alias(f"p_cex_{h}"), r["age_s"].alias(f"cex_age_s_{h}"))
    return out
