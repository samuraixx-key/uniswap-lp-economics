"""Lifetime P&L against holding (spec section 6), for every window-active position.

Everything the LP got out (collected tokens, tokens still owed and accrued at the window end,
tokens still in the position) minus everything put in, valued at the exit price. Collected
amounts include withdrawn principal, so withdrawals are not added again. Deposits are also
valued at their own time for the lifetime return (Binance 1-minute closes before the window).
"""

from typing import Any

import polars as pl

from uniswap_lp_economics.align import reference_at
from uniswap_lp_economics.lp.pnl import (
    WIDTH_BUCKETS,
    Edge,
    position_amounts,
    usd,
    width_bp,
    width_bucket,
)

LIFE_BUCKETS = ("<1d", "1-7d", "7-30d", "30-180d", ">=180d")
US = 1_000_000
DAY_S = 86_400
LIFE_SCHEMA: dict[str, Any] = {
    "position_id": pl.String,
    "kind": pl.String,
    "width_bucket": pl.String,
    "life_s": pl.Float64,
    "life_bucket": pl.String,
    "deposits_usd": pl.Float64,
    "pnl_hold_life_usd": pl.Float64,
    "return_life": pl.Float64,
    "beat_hold": pl.Boolean,
}


def life_bucket(seconds: float) -> str:
    for limit, name in zip((1, 7, 30, 180), LIFE_BUCKETS, strict=False):
        if seconds < limit * DAY_S:
            return name
    return LIFE_BUCKETS[-1]


def lifetime_table(
    positions: pl.DataFrame,
    flows: pl.DataFrame,
    accounts: pl.DataFrame,
    active_ids: list[str],
    prices: dict[int, tuple[int, float]],
    minute_ref: pl.DataFrame,
    window_start_us: int,
    end: Edge,
) -> pl.DataFrame:
    pos = {r["position_id"]: r for r in positions.iter_rows(named=True)}
    acc = {r["position_id"]: r for r in accounts.iter_rows(named=True)}
    fl = flows.filter(pl.col("position_id").is_in(active_ids)).sort("block_number", "log_index")
    deposits = fl.filter(pl.col("event").is_in(["mint", "increase"]))
    pre = reference_at(deposits["ts_us"], minute_ref, window_start_us)["price"].to_list()
    dep_price = [
        p if t < window_start_us else prices.get(b, (0, None))[1]
        for t, b, p in zip(
            deposits["ts_us"].to_list(), deposits["block_number"].to_list(), pre, strict=True
        )
    ]
    deposits = deposits.with_columns(price=pl.Series(dep_price, dtype=pl.Float64))
    by_pos: dict[str, list[dict[str, Any]]] = {}
    for row in fl.iter_rows(named=True):
        by_pos.setdefault(row["position_id"], []).append(row)
    dep_by: dict[str, list[dict[str, Any]]] = {}
    for row in deposits.iter_rows(named=True):
        dep_by.setdefault(row["position_id"], []).append(row)
    rows = []
    for pid in active_ids:
        p, a, fs = pos[pid], acc[pid], by_pos.get(pid, [])
        lo, hi = p["tick_lower"], p["tick_upper"]
        d0 = sum(x["amount0"] for x in dep_by.get(pid, []))
        d1 = sum(x["amount1"] for x in dep_by.get(pid, []))
        dep_usd = sum(
            usd(x["amount0"], x["amount1"], x["price"])
            for x in dep_by.get(pid, [])
            if x["price"] is not None
        )
        c0 = sum(x["amount0"] for x in fs if x["event"] == "collect")
        c1 = sum(x["amount1"] for x in fs if x["event"] == "collect")
        o0 = a["owed_end0"] + a["pending_end0"]
        o1 = a["owed_end1"] + a["pending_end1"]
        if a["liquidity_end"] > 0:
            e0, e1 = position_amounts(a["liquidity_end"], lo, hi, end.sqrt_price_x96)
            exit_ts, p_exit = end.ts_us, end.p_cex
        else:
            last = [x for x in fs if x["liquidity_delta"] < 0][-1]
            e0 = e1 = 0
            exit_ts, p_exit = last["ts_us"], prices[last["block_number"]][1]
        pnl = usd(c0 + o0 + e0 - d0, c1 + o1 + e1 - d1, p_exit)
        life_s = (exit_ts - p["first_ts_us"]) / US
        w = width_bp(lo, hi)
        rows.append(
            {
                "position_id": pid,
                "kind": p["kind"],
                "width_bucket": width_bucket(w),
                "life_s": life_s,
                "life_bucket": life_bucket(life_s),
                "deposits_usd": dep_usd,
                "pnl_hold_life_usd": pnl,
                "return_life": pnl / dep_usd if dep_usd > 0 else None,
                "beat_hold": pnl > 0,
            }
        )
    return pl.DataFrame(rows, schema=LIFE_SCHEMA)


def lifetime_summary(life: pl.DataFrame) -> tuple[dict[str, Any], pl.DataFrame, pl.DataFrame]:
    def table(by: str, order: tuple[str, ...]) -> pl.DataFrame:
        t = life.group_by(by).agg(
            positions=pl.len(),
            share_beat_hold=pl.col("beat_hold").mean(),
            median_return=pl.col("return_life").median(),
        )
        o = pl.DataFrame({by: list(order), "_o": list(range(len(order)))})
        return t.join(o, on=by).sort("_o").drop("_o")

    overall = {
        "positions": life.height,
        "share_beat_hold": float(life["beat_hold"].mean()) if life.height else None,  # type: ignore[arg-type]
        "median_return": life["return_life"].median() if life.height else None,
    }
    return overall, table("width_bucket", WIDTH_BUCKETS), table("life_bucket", LIFE_BUCKETS)
