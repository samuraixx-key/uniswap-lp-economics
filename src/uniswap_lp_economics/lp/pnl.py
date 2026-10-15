"""Window P&L per position and by group (spec section 6).

Per active position: fees and LVR from the ledger's attribution, LP gas and direct builder
payments in the window, P&L against a rebalancing portfolio (fees - LVR - gas - direct payments)
and against holding (everything the LP got out minus everything put in, all at the exit price,
less the same costs). Rates are bp of time-weighted position value
per day; the value is sampled hourly (plan Ruling 5).
"""

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
from numpy.typing import NDArray

from uniswap_lp_economics.config import BLOCK_TIME_S, DAY_S, DECIMALS0, DECIMALS1, HOUR_US, US
from uniswap_lp_economics.v3math import get_sqrt_ratio_at_tick
from uniswap_lp_economics.v3swap import get_amount0_delta, get_amount1_delta

WIDTH_BUCKETS = ("<50", "50-200", "200-1000", "1000-5000", ">=5000")
HOLD_BUCKETS = ("same_block", "<1h", "1h-1d", "1d-7d", ">=7d", "whole_window")
LP_TYPES = ("jit", "lp_vault", "nft_wallet", "nft_contract", "direct_other")
COHORTS = ("pre_window", "in_window")
LP_LABEL_COLUMNS = ["address", "name", "category", "source_url", "notes"]
N_BOOT = 1000
SEED = 42
_ADDRESS = re.compile(r"^0x[0-9a-f]{40}$")


def load_lp_labels(path: Path) -> pl.DataFrame:
    """Read and validate the LP vault list; a ValueError names the offending line."""
    df = pl.read_csv(path, infer_schema=False)
    if df.columns != LP_LABEL_COLUMNS:
        raise ValueError(f"{path}: columns must be {LP_LABEL_COLUMNS}, got {df.columns}")
    for line, row in enumerate(df.iter_rows(named=True), start=2):
        if not _ADDRESS.match(row["address"] or ""):
            raise ValueError(f"{path} line {line}: address {row['address']!r} is not 0x + 40 hex")
        if row["category"] != "lp_vault":
            raise ValueError(f"{path} line {line}: category {row['category']!r} is not lp_vault")
        if not row["name"]:
            raise ValueError(f"{path} line {line}: name is empty")
        if not (row["source_url"] or "").startswith("https://"):
            raise ValueError(f"{path} line {line}: source_url must be an https:// link")
    dupes = sorted(set(df.filter(pl.col("address").is_duplicated())["address"].to_list()))
    if dupes:
        raise ValueError(f"{path}: duplicate addresses {dupes}")
    return df


@dataclass(frozen=True)
class Edge:
    block: int
    ts_us: int
    sqrt_price_x96: int
    p_cex: float


def width_bp(lo: int, hi: int) -> float:
    return (1.0001 ** (hi - lo) - 1.0) * 1e4


def width_bucket(bp: float) -> str:
    for limit, name in zip((50, 200, 1000, 5000), WIDTH_BUCKETS, strict=False):
        if bp < limit:
            return name
    return WIDTH_BUCKETS[-1]


def hold_bucket(seconds: float, same_block: bool, whole_window: bool) -> str:
    if same_block:
        return "same_block"
    if whole_window:
        return "whole_window"
    if seconds < 3600:
        return "<1h"
    if seconds < DAY_S:
        return "1h-1d"
    if seconds < 7 * DAY_S:
        return "1d-7d"
    return ">=7d"


def position_amounts(liquidity: int, lo: int, hi: int, sqrt_price_x96: int) -> tuple[int, int]:
    """Raw token amounts a position holds at a pool price (rounded down, as burn pays)."""
    sa, sb = get_sqrt_ratio_at_tick(lo), get_sqrt_ratio_at_tick(hi)
    if sqrt_price_x96 <= sa:
        return get_amount0_delta(sa, sb, liquidity, False), 0
    if sqrt_price_x96 < sb:
        return (
            get_amount0_delta(sqrt_price_x96, sb, liquidity, False),
            get_amount1_delta(sa, sqrt_price_x96, liquidity, False),
        )
    return 0, get_amount1_delta(sa, sb, liquidity, False)


def usd(amount0: float, amount1: float, price: float) -> float:
    return amount0 / int(10**DECIMALS0) + amount1 / int(10**DECIMALS1) * price


def tx_receipts(events: pl.DataFrame) -> pl.DataFrame:
    """One row per transaction: tx_hash, receipt_gas_used, receipt_effective_gas_price (every
    log of a transaction carries the same receipt columns)."""
    return events.group_by("tx_hash").agg(
        pl.col("receipt_gas_used").first(), pl.col("receipt_effective_gas_price").first()
    )


def gas_by_position(
    flows_window: pl.DataFrame, events: pl.DataFrame, prices: dict[int, tuple[int, float]]
) -> dict[str, float]:
    """Gas of each window transaction that changed a position, split equally across the
    positions it touched, at the Binance price of its block."""
    receipts = {tx: (g, p) for tx, g, p in tx_receipts(events).iter_rows()}
    touched = flows_window.group_by("tx_hash").agg(
        pl.col("position_id").unique(), pl.col("block_number").first()
    )
    out: dict[str, float] = {}
    for tx, pids, block in touched.iter_rows():
        where = f"transaction {tx} (block {block})"
        if tx not in receipts:
            raise ValueError(f"{where} has no receipt row in the events")
        if block not in prices:
            raise ValueError(f"{where} has no price for its block")
        gas_used, gas_price = receipts[tx]
        if gas_used is None or gas_price is None:
            raise ValueError(f"{where} has a null gas-used or effective-gas-price")
        share = int(gas_used) * int(gas_price) / 1e18 * prices[block][1] / len(pids)
        for pid in pids:
            out[pid] = out.get(pid, 0.0) + share
    return out


def direct_by_position(
    flows_window: pl.DataFrame, tx_direct: pl.DataFrame, prices: dict[int, tuple[int, float]]
) -> dict[str, float]:
    """Direct ETH payments to the block's fee recipient (`pool_tx_direct_payments`) of each window
    transaction that changed a position, split equally across the positions it touched, at the
    Binance price of its block. The other half of a builder payment, beside the priority fee that
    `gas_by_position` already counts. A transaction that also swaps may pay for the swap: the
    caller reports such transactions (`jit_own_swaps`)."""
    paid = {
        tx: int(w)
        for tx, w in tx_direct.group_by("tx_hash").agg(pl.col("direct_wei").sum()).iter_rows()
        if w
    }
    touched = flows_window.group_by("tx_hash").agg(
        pl.col("position_id").unique(), pl.col("block_number").first()
    )
    out: dict[str, float] = {}
    for tx, pids, block in touched.iter_rows():
        wei = paid.get(tx, 0)
        if not wei:
            continue
        if block not in prices:
            raise ValueError(f"transaction {tx} (block {block}) has no price for its block")
        share = wei / 1e18 * prices[block][1] / len(pids)
        for pid in pids:
            out[pid] = out.get(pid, 0.0) + share
    return out


def time_weighted_value(
    liq_path: pl.DataFrame, spans: pl.DataFrame, grid: pl.DataFrame
) -> pl.DataFrame:
    """Mean USD value over the hourly grid points in [t_start, t_exit) of each position.

    liq_path: position_id, ts_us, liquidity (after each change). spans: position_id,
    tick_lower, tick_upper, t_start_us, t_exit_us. grid: ts_us (hourly), sqrt (sqrtPrice/2^96 as
    a float), p_cex. Positions without a grid point are left out (the caller falls back).
    Rows of liq_path that share a timestamp must be in event order: the last one wins."""
    g0 = int(grid["ts_us"].min())  # type: ignore[arg-type]
    n = grid.height
    idx = spans.with_columns(
        first=((pl.col("t_start_us") - g0 + HOUR_US - 1) // HOUR_US).clip(lower_bound=0),
        last=((pl.col("t_exit_us") - g0 - 1) // HOUR_US).clip(upper_bound=n - 1),
    ).filter(pl.col("last") >= pl.col("first"))
    points = (
        idx.with_columns(k=pl.int_ranges("first", pl.col("last") + 1))
        .explode("k")
        .with_columns(ts_us=g0 + pl.col("k") * HOUR_US)
        .sort("ts_us")
    )
    path = liq_path.with_columns(pl.col("liquidity").cast(pl.Float64)).sort(
        "ts_us", maintain_order=True
    )
    joined = points.join_asof(
        path, on="ts_us", by="position_id", strategy="backward", check_sortedness=False
    ).join(grid, on="ts_us", how="left")
    sa = pl.lit(1.0001).pow(pl.col("tick_lower") / 2)
    sb = pl.lit(1.0001).pow(pl.col("tick_upper") / 2)
    sp = pl.col("sqrt").clip(sa, sb)
    liq = pl.col("liquidity").fill_null(0.0)
    value = liq * (1 / sp - 1 / sb) / 10**DECIMALS0 + liq * (sp - sa) / 10**DECIMALS1 * pl.col(
        "p_cex"
    )
    return joined.group_by("position_id").agg(twv=value.mean())


PNL_SCHEMA: dict[str, Any] = {
    "position_id": pl.String,
    "kind": pl.String,
    "lp": pl.String,
    "lp_type": pl.String,
    "cohort": pl.String,
    "tick_lower": pl.Int64,
    "tick_upper": pl.Int64,
    "width_bp": pl.Float64,
    "width_bucket": pl.String,
    "holding": pl.String,
    "start_block": pl.Int64,
    "exit_block": pl.Int64,
    "days_active": pl.Float64,
    "twv_usd": pl.Float64,
    "capital_days": pl.Float64,
    "fee_usd": pl.Float64,
    "lvr_0": pl.Float64,
    "lvr_12": pl.Float64,
    "gas_usd": pl.Float64,
    "direct_usd": pl.Float64,
    "pnl_rebal_usd": pl.Float64,
    "pnl_rebal_12_usd": pl.Float64,
    "pnl_hold_usd": pl.Float64,
    "bp_per_day": pl.Float64,
    "bp_per_day_hold": pl.Float64,
}
PNL_COLUMNS = list(PNL_SCHEMA)


def window_pnl(
    positions: pl.DataFrame,
    accounts: pl.DataFrame,
    flows_window: pl.DataFrame,
    prices: dict[int, tuple[int, float]],
    gas: dict[str, float],
    twv: dict[str, float],
    vaults: set[str],
    has_code: dict[str, bool],
    start: Edge,
    end: Edge,
    direct: dict[str, float] | None = None,
) -> pl.DataFrame:
    """`gas` and `direct` (direct builder payments): USD per position, both charged to it."""
    direct = direct or {}
    pos = {r["position_id"]: r for r in positions.iter_rows(named=True)}
    by_pos: dict[str, list[dict[str, Any]]] = {}
    for f in flows_window.sort("block_number", "log_index").iter_rows(named=True):
        by_pos.setdefault(f["position_id"], []).append(f)
    rows = []
    for a in accounts.filter(pl.col("active")).iter_rows(named=True):
        pid = a["position_id"]
        p = pos[pid]
        lo, hi = p["tick_lower"], p["tick_upper"]
        fl = by_pos.get(pid, [])
        dep0 = dep1 = wd0 = wd1 = 0
        open_at_start = a["liquidity_start"] > 0
        if open_at_start:
            d0, d1 = position_amounts(a["liquidity_start"], lo, hi, start.sqrt_price_x96)
            dep0, dep1, t_start, b_start = d0, d1, start.ts_us, start.block
            first_amounts, first_price = (d0, d1), start.p_cex
        else:
            first = next((f for f in fl if f["liquidity_delta"] > 0), None)
            if first is None:
                raise ValueError(
                    f"{pid} is active, but held no liquidity at the start "
                    "and added none in the window"
                )
            t_start, b_start = first["ts_us"], first["block_number"]
            first_amounts = (first["amount0"], first["amount1"])
            first_price = prices[b_start][1]
        for f in fl:
            if f["event"] in ("mint", "increase"):
                dep0 += f["amount0"]
                dep1 += f["amount1"]
            elif f["event"] in ("burn", "decrease"):
                wd0 += f["amount0"]
                wd1 += f["amount1"]
        liq_end = a["liquidity_end"]
        if liq_end > 0:
            e0, e1 = position_amounts(liq_end, lo, hi, end.sqrt_price_x96)
            exit_block, exit_ts, p_exit = end.block, end.ts_us, end.p_cex
        else:
            removals = [f for f in fl if f["liquidity_delta"] < 0]
            if not removals:
                raise ValueError(f"{pid} ends with no liquidity but has no window removal")
            last = removals[-1]
            e0 = e1 = 0
            exit_block, exit_ts = last["block_number"], last["ts_us"]
            p_exit = prices[exit_block][1]
        g_gas, g_direct = gas.get(pid, 0.0), direct.get(pid, 0.0)
        g = g_gas + g_direct
        pnl_hold = (
            usd(wd0 + e0 + a["fees_raw0"] - dep0, wd1 + e1 + a["fees_raw1"] - dep1, p_exit) - g
        )
        jit = not open_at_start and b_start == exit_block and liq_end == 0
        days = BLOCK_TIME_S / DAY_S if jit else max(exit_ts - t_start, 0) / (DAY_S * US)
        tw = twv.get(pid)
        if tw is None:  # no hourly grid point while open (plan Ruling 5)
            tw = usd(*first_amounts, first_price)
        lp, kind = p["lp"], p["kind"]
        if jit:
            lp_type = "jit"
        elif lp in vaults:
            lp_type = "lp_vault"
        elif kind == "nft":
            if lp not in has_code:
                raise ValueError(f"no owner code for {lp}; run `ulpe fetch-chain-state`")
            lp_type = "nft_contract" if has_code[lp] else "nft_wallet"
        else:
            lp_type = "direct_other"
        w = width_bp(lo, hi)
        capital = tw * days
        rebal = a["fee_usd"] - a["lvr_0"] - g
        rows.append(
            {
                "position_id": pid,
                "kind": kind,
                "lp": lp,
                "lp_type": lp_type,
                "cohort": "pre_window" if open_at_start else "in_window",
                "tick_lower": lo,
                "tick_upper": hi,
                "width_bp": w,
                "width_bucket": width_bucket(w),
                "holding": hold_bucket(
                    (exit_ts - t_start) / US, jit, open_at_start and liq_end > 0
                ),
                "start_block": b_start,
                "exit_block": exit_block,
                "days_active": days,
                "twv_usd": tw,
                "capital_days": capital,
                "fee_usd": a["fee_usd"],
                "lvr_0": a["lvr_0"],
                "lvr_12": a["lvr_12"],
                "gas_usd": g_gas,
                "direct_usd": g_direct,
                "pnl_rebal_usd": rebal,
                "pnl_rebal_12_usd": a["fee_usd"] - a["lvr_12"] - g,
                "pnl_hold_usd": pnl_hold,
                "bp_per_day": rebal / capital * 1e4 if capital > 0 else None,
                "bp_per_day_hold": pnl_hold / capital * 1e4 if capital > 0 else None,
            }
        )
    return pl.DataFrame(rows, schema=PNL_SCHEMA)


JIT_PER_SWAP = {  # summary key -> positions column
    "fee_usd_per_swap": "fee_usd",
    "lvr_0_usd_per_swap": "lvr_0",
    "gas_usd_per_swap": "gas_usd",
    "direct_usd_per_swap": "direct_usd",
    "pnl_rebal_usd_per_swap": "pnl_rebal_usd",
    "pnl_hold_usd_per_swap": "pnl_hold_usd",
}


def jit_per_swap(
    positions: pl.DataFrame, flows_window: pl.DataFrame, swaps: pl.DataFrame
) -> dict[str, Any]:
    """JIT P&L in USD per swap (spec section 6). A jit position is active for the swaps of its
    block that lie, in log order, between its first liquidity add and its last removal; the
    totals of the jit positions are divided by the number of such position-swap pairs. Also the
    median per-position P&L per swap over jit positions with at least one swap. `swaps`:
    block_number and log_index of every swap."""
    jit = positions.filter(pl.col("lp_type") == "jit")
    spans = (
        flows_window.join(jit.select("position_id"), on="position_id", how="semi")
        .group_by("position_id")
        .agg(
            block=pl.col("block_number").first(),
            first_add=pl.col("pool_log_index").filter(pl.col("liquidity_delta") > 0).min(),
            last_remove=pl.col("pool_log_index").filter(pl.col("liquidity_delta") < 0).max(),
        )
    )
    counts = (
        spans.join(
            swaps.select("block_number", "log_index"), left_on="block", right_on="block_number"
        )
        .filter(
            (pl.col("log_index") > pl.col("first_add"))
            & (pl.col("log_index") < pl.col("last_remove"))
        )
        .group_by("position_id")
        .agg(swaps=pl.len())
    )
    per = jit.join(counts, on="position_id", how="left").with_columns(pl.col("swaps").fill_null(0))
    n = int(per["swaps"].sum()) if per.height else 0
    out: dict[str, Any] = {
        "positions": jit.height,
        "positions_with_swaps": int((per["swaps"] > 0).sum()) if per.height else 0,
        "swaps": n,
    }
    for key, col in JIT_PER_SWAP.items():
        out[key] = float(per[col].sum()) / n if n else None
    with_swaps = per.filter(pl.col("swaps") > 0)
    out["median_pnl_rebal_usd_per_swap"] = (
        float((with_swaps["pnl_rebal_usd"] / with_swaps["swaps"]).median())  # type: ignore[arg-type]
        if with_swaps.height
        else None
    )
    return out


def jit_own_swaps(
    positions: pl.DataFrame, flows_window: pl.DataFrame, swaps: pl.DataFrame
) -> dict[str, Any]:
    """JIT transactions that also swap in the pool: how many, the swaps' 0 s markout (the
    swapper's, so negative when the JIT operator's own trade lost at Binance's price), and the gas
    and direct payments charged to JIT positions in them. Such a payment may be for the swap, and
    the rebalancing benchmark takes the operator's own trades as free. `swaps`: tx_hash and
    markout_usd_0 of every swap."""
    jit = positions.filter(pl.col("lp_type") == "jit").select(
        "position_id", "gas_usd", "direct_usd"
    )
    pos_tx = (
        flows_window.join(jit.select("position_id"), on="position_id", how="semi")
        .select("position_id", "tx_hash")
        .unique()
    )
    txs = pos_tx.select("tx_hash").unique()
    own = swaps.join(txs, on="tx_hash", how="semi")
    mixed = own.select("tx_hash").unique()
    # gas and direct payments are per position; a position's costs count once if any of its
    # transactions also swaps (a JIT position lives in one block, almost always one transaction)
    mixed_pos = jit.join(
        pos_tx.join(mixed, on="tx_hash", how="semi").select("position_id").unique(),
        on="position_id",
        how="semi",
    )
    return {
        "jit_txs": txs.height,
        "jit_txs_with_own_swaps": mixed.height,
        "own_swaps": own.height,
        "own_swap_markout_usd_0": float(own["markout_usd_0"].sum()),
        "gas_usd_in_txs_with_own_swaps": float(mixed_pos["gas_usd"].sum()),
        "direct_usd_in_txs_with_own_swaps": float(mixed_pos["direct_usd"].sum()),
    }


def bootstrap_ratio(
    num: NDArray[np.float64], den: NDArray[np.float64], n_boot: int = N_BOOT, seed: int = SEED
) -> tuple[float, float]:
    """95% interval of sum(num) / sum(den) x 1e4, resampling positions."""
    n = len(num)
    if n == 0:
        return math.nan, math.nan
    rng = np.random.default_rng(seed)
    stats = np.empty(n_boot)
    for b in range(n_boot):
        idx = rng.integers(0, n, size=n)
        d = den[idx].sum()
        stats[b] = num[idx].sum() / d * 1e4 if d > 0 else np.nan
    if np.isnan(stats).all():
        return math.nan, math.nan
    lo, hi = np.nanpercentile(stats, [2.5, 97.5])
    return float(lo), float(hi)


def group_table(pnl: pl.DataFrame, by: str, order: tuple[str, ...]) -> pl.DataFrame:
    rows = []
    for value in order:
        g = pnl.filter(pl.col(by) == value)
        if g.height == 0:
            continue
        capital = float(g["capital_days"].sum())
        rebal = float(g["pnl_rebal_usd"].sum())
        hold = float(g["pnl_hold_usd"].sum())
        lo, hi = bootstrap_ratio(
            g["pnl_rebal_usd"].to_numpy().astype(np.float64),
            g["capital_days"].to_numpy().astype(np.float64),
        )
        rows.append(
            {
                by: value,
                "positions": g.height,
                "fees_usd": float(g["fee_usd"].sum()),
                "lvr_0_usd": float(g["lvr_0"].sum()),
                "gas_usd": float(g["gas_usd"].sum()),
                "direct_usd": float(g["direct_usd"].sum()),
                "pnl_rebal_usd": rebal,
                "pnl_hold_usd": hold,
                "share_beat_hold": float((g["pnl_hold_usd"] > 0).mean()),  # type: ignore[arg-type]
                "bp_per_day": rebal / capital * 1e4 if capital > 0 else None,
                "ci_lo_bp": lo,
                "ci_hi_bp": hi,
                "bp_per_day_hold": hold / capital * 1e4 if capital > 0 else None,
            }
        )
    return pl.DataFrame(rows)


def position_spans(
    positions: pl.DataFrame,
    accounts: pl.DataFrame,
    flows_window: pl.DataFrame,
    start: Edge,
    end: Edge,
) -> pl.DataFrame:
    """[t_start, t_exit) of every active position inside the window."""
    f = flows_window.sort("block_number", "log_index")
    first_in = (
        f.filter(pl.col("liquidity_delta") > 0)
        .group_by("position_id")
        .agg(t_first=pl.col("ts_us").first())
    )
    last_out = (
        f.filter(pl.col("liquidity_delta") < 0)
        .group_by("position_id")
        .agg(t_last=pl.col("ts_us").last())
    )
    return (
        accounts.filter(pl.col("active"))
        .select("position_id", "liquidity_start", "liquidity_end")
        .join(positions.select("position_id", "tick_lower", "tick_upper"), on="position_id")
        .join(first_in, on="position_id", how="left")
        .join(last_out, on="position_id", how="left")
        .select(
            "position_id",
            "tick_lower",
            "tick_upper",
            t_start_us=pl.when(pl.col("liquidity_start") > 0)
            .then(pl.lit(start.ts_us, dtype=pl.Int64))
            .otherwise(pl.col("t_first")),
            t_exit_us=pl.when(pl.col("liquidity_end") > 0)
            .then(pl.lit(end.ts_us, dtype=pl.Int64))
            .otherwise(pl.col("t_last")),
        )
    )


def liquidity_path(accounts: pl.DataFrame, flows_window: pl.DataFrame, start: Edge) -> pl.DataFrame:
    """Each position's liquidity after every change, from its window-start liquidity.

    Rows are in event order (the base rows first, then the changes by block and log index), which
    `time_weighted_value` relies on when several changes share a timestamp."""
    base = accounts.select(
        "position_id",
        ts_us=pl.lit(start.ts_us, dtype=pl.Int64),
        liquidity=pl.col("liquidity_start"),
    )
    changes = (
        flows_window.sort("block_number", "log_index")
        .join(
            accounts.select("position_id", "liquidity_start"),
            on="position_id",
            maintain_order="left",
        )
        .with_columns(
            liquidity=pl.col("liquidity_start")
            + pl.col("liquidity_delta").cum_sum().over("position_id")
        )
        .select("position_id", "ts_us", "liquidity")
    )
    return pl.concat([base, changes]).with_columns(pl.col("ts_us").cast(pl.Int64))
