"""Exact per-swap fees from the bit-exact re-simulation (spec P2).

The fee of each step is the contract's; the protocol takes `fee // feeProtocol` of each step, from
the input token's nibble of slot0.feeProtocol, exactly as UniswapV3Pool.swap does.
"""

from typing import Any

import polars as pl

from uniswap_lp_economics.replay import apply_event, iter_event_rows, required
from uniswap_lp_economics.tickbook import TickBook
from uniswap_lp_economics.v3swap import reproduce_swap

SWAP_FEES_SCHEMA: dict[str, Any] = {
    "block_number": pl.Int64,
    "log_index": pl.Int64,
    "mode": pl.String,
    "fee_token": pl.String,
    "fee_raw": pl.Int128,
    "protocol_fee_raw": pl.Int128,
    "lp_fee_raw": pl.Int128,
    "steps": pl.Int64,
}


def protocol_cut(fee: int, fee_protocol: int, zero_for_one: bool) -> int:
    """The protocol's share of one step's fee (UniswapV3Pool.swap: feeAmount / feeProtocol)."""
    denominator = fee_protocol % 16 if zero_for_one else fee_protocol >> 4
    return fee // denominator if denominator else 0


def build_swap_fees(events: pl.DataFrame, book: TickBook, fee_protocol: int) -> pl.DataFrame:
    """One row per swap in `events`; `book` (the start state) is advanced in place."""
    rows: list[dict[str, Any]] = []
    for row in iter_event_rows(events):
        if row.event == "swap":
            rep = reproduce_swap(
                book,
                required(row, "amount0"),
                required(row, "amount1"),
                required(row, "sqrt_price_x96"),
            )
            base = {"block_number": row.block_number, "log_index": row.log_index}
            if rep is None:
                rows.append({**base, "mode": None, "steps": 0})
            elif rep.run is None:
                rows.append(
                    {
                        **base,
                        "mode": rep.mode,
                        "fee_raw": 0,
                        "protocol_fee_raw": 0,
                        "lp_fee_raw": 0,
                        "steps": 0,
                    }
                )
            else:
                cut = sum(
                    protocol_cut(s.fee, fee_protocol, rep.zero_for_one) for s in rep.run.steps
                )
                rows.append(
                    {
                        **base,
                        "mode": rep.mode,
                        "fee_token": "USDC" if rep.zero_for_one else "WETH",
                        "fee_raw": rep.run.fee,
                        "protocol_fee_raw": cut,
                        "lp_fee_raw": rep.run.fee - cut,
                        "steps": len(rep.run.steps),
                    }
                )
        fee_protocol = apply_event(book, row, fee_protocol)
    return pl.DataFrame(rows, schema=SWAP_FEES_SCHEMA)
