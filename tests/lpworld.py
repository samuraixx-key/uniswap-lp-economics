"""A small synthetic pool and window for the `ulpe lp` end-to-end test."""

from datetime import UTC, datetime, timedelta
from typing import Any

import polars as pl

from uniswap_lp_economics.config import NPM_ADDRESS
from uniswap_lp_economics.data.chain_state import FEE_SCHEMA, POSITION_STATE_SCHEMA
from uniswap_lp_economics.io import u256_hex
from uniswap_lp_economics.lp.analyze import LpInputs
from uniswap_lp_economics.lp.engine import contexts_from_aligned, replay_window
from uniswap_lp_economics.lp.ledger import Ledger
from uniswap_lp_economics.lp.positions import build_positions
from uniswap_lp_economics.lp.state import FeeAccumulators, PoolState
from uniswap_lp_economics.lp.swapfees import build_swap_fees
from uniswap_lp_economics.replay import iter_block_starts
from uniswap_lp_economics.tickbook import TickBook
from uniswap_lp_economics.v3math import get_sqrt_ratio_at_tick as sqrt_at
from uniswap_lp_economics.v3math import sqrt_price_x96_to_eth_price
from uniswap_lp_economics.v3swap import swap

T = 200_310  # ~2,000 USD per ETH
L = 10**18
SNAP = 5
T0 = datetime(2026, 7, 1, tzinfo=UTC)
US = 1_000_000
D, J = "0x" + "d1" * 20, "0x" + "e1" * 20
WALLET, ZERO = "0x" + "a1" * 20, "0x" + "00" * 20
EVENT_SCHEMA: dict[str, Any] = {
    "block_number": pl.Int64,
    "log_index": pl.Int64,
    "block_timestamp": pl.Datetime("us", "UTC"),
    "tx_hash": pl.String,
    "transaction_index": pl.Int64,
    "event": pl.String,
    "owner": pl.String,
    "sender": pl.String,
    "to_address": pl.String,
    "tick_lower": pl.Int64,
    "tick_upper": pl.Int64,
    "amount": pl.Int128,
    "amount0": pl.Int128,
    "amount1": pl.Int128,
    "sqrt_price_x96": pl.Int128,
    "tick": pl.Int64,
    "liquidity": pl.Int128,
    "paid0": pl.Int128,
    "paid1": pl.Int128,
    "receipt_gas_used": pl.Int64,
    "receipt_effective_gas_price": pl.Int64,
}
NPM_SCHEMA: dict[str, Any] = {
    "block_number": pl.Int64,
    "log_index": pl.Int64,
    "block_timestamp": pl.Datetime("us", "UTC"),
    "tx_hash": pl.String,
    "transaction_index": pl.Int64,
    "event": pl.String,
    "token_id": pl.Int64,
    "liquidity": pl.Int128,
    "amount0": pl.Int128,
    "amount1": pl.Int128,
    "recipient": pl.String,
    "from_owner": pl.String,
    "to_owner": pl.String,
}


def ts(block: int) -> datetime:
    if block <= SNAP:
        return T0 - timedelta(seconds=12 * (SNAP + 1 - block))
    if block >= 11:
        return T0 + timedelta(days=1, seconds=12 * (block - 11))
    return T0 + timedelta(seconds=12 * (block - SNAP))


def ev(block: int, log: int, event: str, **kw: Any) -> dict[str, Any]:
    return {
        "block_number": block,
        "log_index": log,
        "block_timestamp": ts(block),
        "tx_hash": f"0x{block:064x}",
        "transaction_index": 0,
        "event": event,
        "receipt_gas_used": 100_000,
        "receipt_effective_gas_price": 10**9,
        **kw,
    }


def snapshot_book() -> TickBook:
    b = TickBook(tick=T, sqrt_price_x96=sqrt_at(T), liquidity=0)
    b.apply_mint(T - 10, T + 10, L)
    return b


class World:
    """Builds the events; chain-state frames come from an oracle replay."""

    def __init__(self) -> None:
        self.book = snapshot_book()
        self.pool: list[dict[str, Any]] = [
            ev(
                1,
                0,
                "mint",
                owner=D,
                tick_lower=T - 10,
                tick_upper=T + 10,
                amount=L,
                amount0=10**9,
                amount1=10**18,
            )
        ]
        self.npm: list[dict[str, Any]] = []

    def swap(self, block: int, log: int, usdc_in: int) -> None:
        r = swap(self.book, True, usdc_in)
        self.pool.append(
            ev(
                block,
                log,
                "swap",
                sender=J,
                to_address=J,
                amount0=r.amount_in,
                amount1=-r.amount_out,
                sqrt_price_x96=r.sqrt_price_x96,
                tick=r.tick,
                liquidity=r.liquidity,
            )
        )
        self.book.apply_swap(r.sqrt_price_x96, r.tick)

    def flash(self, block: int, log: int, paid0: int, paid1: int) -> None:
        self.pool.append(ev(block, log, "flash", sender=J, to_address=J, paid0=paid0, paid1=paid1))

    def mint(self, block: int, log: int, owner: str, lo: int, hi: int) -> None:
        self.pool.append(
            ev(
                block,
                log,
                "mint",
                owner=owner,
                tick_lower=lo,
                tick_upper=hi,
                amount=L,
                amount0=10**9,
                amount1=10**17,
            )
        )
        self.book.apply_mint(lo, hi, L)

    def burn(self, block: int, log: int, owner: str, lo: int, hi: int) -> None:
        self.pool.append(
            ev(
                block,
                log,
                "burn",
                owner=owner,
                tick_lower=lo,
                tick_upper=hi,
                amount=L,
                amount0=5 * 10**8,
                amount1=5 * 10**16,
            )
        )
        self.book.apply_burn(lo, hi, L)


def build(collects: dict[str, tuple[int, int]] | None = None) -> tuple[World, list[dict[str, Any]]]:
    w = World()
    w.mint(6, 0, NPM_ADDRESS, T - 20, T + 20)
    w.npm += [
        ev(6, 1, "transfer", token_id=1, from_owner=ZERO, to_owner=WALLET),
        ev(6, 2, "increase", token_id=1, liquidity=L, amount0=10**9, amount1=10**17),
    ]
    w.swap(7, 0, 10**9)
    w.flash(8, 0, 1_000_000, 10**15)  # fees in both tokens, no position change
    w.mint(9, 0, J, T - 10, T + 10)
    w.swap(9, 1, 2 * 10**9)
    w.burn(9, 2, J, T - 10, T + 10)
    w.burn(10, 0, NPM_ADDRESS, T - 20, T + 20)
    w.npm.append(
        ev(10, 1, "decrease", token_id=1, liquidity=L, amount0=5 * 10**8, amount1=5 * 10**16)
    )
    if collects is not None:
        j0, j1 = collects["J"]
        w.pool.append(
            ev(
                9,
                3,
                "collect",
                owner=J,
                tick_lower=T - 10,
                tick_upper=T + 10,
                amount=0,
                amount0=j0,
                amount1=j1,
            )
        )
        n0, n1 = collects["nft"]
        w.pool.append(
            ev(
                10,
                2,
                "collect",
                owner=NPM_ADDRESS,
                tick_lower=T - 20,
                tick_upper=T + 20,
                amount=0,
                amount0=n0,
                amount1=n1,
            )
        )
        w.npm.append(ev(10, 3, "npm_collect", token_id=1, recipient=WALLET, amount0=n0, amount1=n1))
    w.swap(11, 0, 10**9)
    w.swap(12, 0, 10**9)
    return w, w.pool


def frames(w: World) -> tuple[pl.DataFrame, pl.DataFrame]:
    pool = pl.DataFrame(w.pool, schema=EVENT_SCHEMA).sort("block_number", "log_index")
    npm = pl.DataFrame(w.npm, schema=NPM_SCHEMA).sort("block_number", "log_index")
    return pool, npm


def aligned_for(events: pl.DataFrame) -> pl.DataFrame:
    swaps = events.filter(pl.col("event") == "swap")
    p = [sqrt_price_x96_to_eth_price(s) for s in swaps["sqrt_price_x96"].to_list()]
    return swaps.select(
        "block_number",
        "log_index",
        "block_timestamp",
        t0_us=pl.col("block_timestamp").dt.epoch("us"),
        p_cex_0=pl.Series(p),
        p_cex_12=pl.Series(p),
        flow_label=pl.lit("searcher"),
        markout_usd_0=-(
            pl.col("amount0").cast(pl.Float64) / 1e6
            + pl.col("amount1").cast(pl.Float64) / 1e18 * pl.Series(p)
        ),
        protocol_fee_usd=pl.lit(0.0),
    )


def snapshot_frames(book: TickBook) -> tuple[pl.DataFrame, pl.DataFrame, dict[str, int]]:
    ticks = pl.DataFrame(
        {"tick": [T - 10, T + 10], "liquidity_gross": [L, L], "liquidity_net": [L, -L]},
        schema={"tick": pl.Int64, "liquidity_gross": pl.Int128, "liquidity_net": pl.Int128},
    )
    fees = pl.DataFrame(
        [
            {
                "block": SNAP,
                "kind": "global",
                "tick": None,
                "fee_growth0": u256_hex(0),
                "fee_growth1": u256_hex(0),
            }
        ]
        + [
            {
                "block": SNAP,
                "kind": "tick",
                "tick": t,
                "fee_growth0": u256_hex(0),
                "fee_growth1": u256_hex(0),
            }
            for t in (T - 10, T + 10)
        ],
        schema=FEE_SCHEMA,
    )
    meta = {
        "block": SNAP,
        "tick": T,
        "sqrt_price_x96": sqrt_at(T),
        "liquidity": L,
        "fee_protocol": 0,
        "timestamp": int(ts(SNAP).timestamp()),
    }
    return ticks, fees, meta


def oracle(events: pl.DataFrame, npm: pl.DataFrame) -> tuple[Ledger, Any]:
    data = build_positions(events, npm)
    ticks, fees, meta = snapshot_frames(snapshot_book())
    start = pl.DataFrame(
        [
            {
                "block": SNAP,
                "kind": "pool_key",
                "owner": D,
                "tick_lower": T - 10,
                "tick_upper": T + 10,
                "token_id": None,
                "found": True,
                "liquidity": L,
                "fee_growth_inside0_last": u256_hex(0),
                "fee_growth_inside1_last": u256_hex(0),
                "tokens_owed0": 0,
                "tokens_owed1": 0,
            }
        ],
        schema=POSITION_STATE_SCHEMA,
    )
    state = PoolState(
        TickBook.from_snapshot(ticks, meta), FeeAccumulators.from_rows(fees, [T - 10, T + 10]), 0
    )
    ledger = Ledger(data, start, SNAP)
    window = events.filter(pl.col("block_number") > SNAP)
    run = replay_window(
        window,
        state,
        contexts_from_aligned(aligned_for(window)),
        {7: [T - 10, T + 10, T - 20, T + 20]},
        ledger,
        npm.filter(pl.col("block_number") > SNAP),
    )
    return ledger, run


def world_inputs() -> LpInputs:
    first, _ = build()
    ledger, _ = oracle(*frames(first))
    j = ledger.keys[(J, T - 10, T + 10)]
    tok = ledger.token_mirror(1)
    assert tok is not None
    w, _ = build({"J": (j.owed0, j.owed1), "nft": (tok.owed0, tok.owed1)})
    pool, npm = frames(w)
    ledger, run = oracle(pool, npm)
    ticks, fees, meta = snapshot_frames(snapshot_book())
    window = pool.filter(pl.col("block_number") > SNAP)

    def state_row(
        kind: str, owner: str | None, lo: int | None, hi: int | None, token: int | None, m: Any
    ) -> dict[str, Any]:
        return {
            "block": 12,
            "kind": kind,
            "owner": owner,
            "tick_lower": lo,
            "tick_upper": hi,
            "token_id": token,
            "found": True,
            "liquidity": m.liquidity,
            "fee_growth_inside0_last": u256_hex(m.last0),
            "fee_growth_inside1_last": u256_hex(m.last1),
            "tokens_owed0": m.owed0,
            "tokens_owed1": m.owed1,
        }

    end = pl.DataFrame(
        [state_row("pool_key", o, lo, hi, None, m) for (o, lo, hi), m in ledger.keys.items()]
        + [{"block": 12, "kind": "npm_token", "token_id": 1, "found": False}],
        schema=POSITION_STATE_SCHEMA,
    )
    cap = run.captures[7]
    sample = pl.DataFrame(
        [
            {
                "block": 7,
                "kind": "global",
                "tick": None,
                "fee_growth0": u256_hex(cap["global0"]),
                "fee_growth1": u256_hex(cap["global1"]),
            }
        ]
        + [
            {
                "block": 7,
                "kind": "tick",
                "tick": t,
                "fee_growth0": u256_hex(o0),
                "fee_growth1": u256_hex(o1),
            }
            for t, (o0, o1) in cap["ticks"].items()
        ],
        schema=FEE_SCHEMA,
    )
    book = TickBook.from_snapshot(ticks, meta)
    rows = []
    blocks = list(range(SNAP + 1, 13))
    for b in iter_block_starts(window, book, 0, blocks[0], blocks[-1]):
        rows.append(
            {"block_number": b, "sqrt_price_x96": book.sqrt_price_x96, "liquidity": book.liquidity}
        )
    for i in range(len(blocks)):
        rows[i]["end_sqrt_price_x96"] = rows[i + 1]["sqrt_price_x96"]
    state_rows = rows[: len(blocks)]
    blocks_state = pl.DataFrame(
        state_rows,
        schema={
            "block_number": pl.Int64,
            "sqrt_price_x96": pl.Int128,
            "liquidity": pl.Int128,
            "end_sqrt_price_x96": pl.Int128,
        },
    ).with_columns(
        ts_us=pl.Series([int(ts(b).timestamp()) * US for b in blocks]),
        p_cex=pl.Series([sqrt_price_x96_to_eth_price(r["sqrt_price_x96"]) for r in state_rows]),
    )
    t_lo = int(ts(SNAP).timestamp()) * US - 60 * US
    t_hi = int(ts(12).timestamp()) * US + 3_700 * US
    seconds = list(range(t_lo, t_hi, US))
    trades = pl.DataFrame(
        {
            "agg_trade_id": list(range(len(seconds))),
            "ts_us": seconds,
            "price": [2000.0 * (1 + 0.0005 * ((i % 7) - 3) / 3) for i in range(len(seconds))],
            "qty": [1.0] * len(seconds),
            "is_buyer_maker": [True] * len(seconds),
        }
    )
    # The pre-window deposit (block 1) needs a 1-minute close within an hour of it.
    minute = pl.DataFrame(
        {"ts_us": [int((T0 - timedelta(minutes=2)).timestamp()) * US], "close": [1900.0]}
    )
    return LpInputs(
        events=window,
        ticks=ticks,
        meta=meta,
        aligned=aligned_for(window),
        blocks_state=blocks_state,
        swap_fees=build_swap_fees(window, TickBook.from_snapshot(ticks, meta), 0),
        trades=trades,
        pool_history=pool,
        npm_history=npm,
        snapshot_fees=fees,
        sample_fees=sample,
        start_positions=pl.DataFrame(
            [
                {
                    "block": SNAP,
                    "kind": "pool_key",
                    "owner": D,
                    "tick_lower": T - 10,
                    "tick_upper": T + 10,
                    "token_id": None,
                    "found": True,
                    "liquidity": L,
                    "fee_growth_inside0_last": u256_hex(0),
                    "fee_growth_inside1_last": u256_hex(0),
                    "tokens_owed0": 0,
                    "tokens_owed1": 0,
                }
            ],
            schema=POSITION_STATE_SCHEMA,
        ),
        end_positions=end,
        owner_code=pl.DataFrame({"address": [WALLET, D, J], "has_code": [False, True, True]}),
        minute_klines=minute,
        lp_labels=pl.DataFrame(
            schema={c: pl.String for c in ("address", "name", "category", "source_url", "notes")}
        ),
        window_end_us=t_hi,
    )
