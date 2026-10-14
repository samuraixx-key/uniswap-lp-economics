"""Checks L1-L7 (gated) and the reported checks of sub-project 3 (spec section 9)."""

from typing import TYPE_CHECKING, Any

import polars as pl

from uniswap_lp_economics.io import hex_u256
from uniswap_lp_economics.lp.positions import LedgerData
from uniswap_lp_economics.validate import MAX_LISTED, CheckResult

if TYPE_CHECKING:
    from uniswap_lp_economics.lp.ledger import Ledger


def check_l1(swap_fees: pl.DataFrame) -> CheckResult:
    """Every swap re-simulated bit-exactly in one of the reproduction modes."""
    modes = swap_fees.group_by("mode").len().drop_nulls("mode")
    counts: dict[str, Any] = dict(zip(modes["mode"].to_list(), modes["len"].to_list(), strict=True))
    bad = swap_fees.filter(pl.col("mode").is_null())
    listed = [
        {"block": b, "log_index": li}
        for b, li in bad.select("block_number", "log_index").head(MAX_LISTED).iter_rows()
    ]
    return CheckResult(
        "L1 every swap reproduced bit-exactly",
        bad.height == 0 and swap_fees.height > 0,
        {"swaps": swap_fees.height, "unreproduced": bad.height, "by_mode": counts},
        listed,
    )


def check_l2(captures: dict[int, dict[str, Any]], sample_fees: pl.DataFrame) -> CheckResult:
    """Engine fee accumulators vs on-chain fee state at the sample blocks, exactly."""
    bad: list[dict[str, Any]] = []
    n_bad = compared = 0
    blocks = sorted(set(sample_fees["block"].to_list()))
    for b, kind, tick, f0, f1 in sample_fees.select(
        "block", "kind", "tick", "fee_growth0", "fee_growth1"
    ).iter_rows():
        compared += 1
        cap = captures.get(b)
        if cap is None:
            got: tuple[int, int] | None = None
        elif kind == "global":
            got = (cap["global0"], cap["global1"])
        else:
            got = cap["ticks"].get(tick)
        want = (hex_u256(f0), hex_u256(f1))
        if got != want:
            n_bad += 1
            if len(bad) < MAX_LISTED:
                bad.append({"block": b, "kind": kind, "tick": tick, "onchain": want, "engine": got})
    return CheckResult(
        "L2 fee accumulators match the chain",
        n_bad == 0 and compared > 0 and all(b in captures for b in blocks),
        {"blocks": len(blocks), "values_compared": compared, "mismatches": n_bad},
        bad,
    )


def check_l5(
    start: pl.DataFrame, snapshot_ticks: pl.DataFrame, meta: dict[str, int]
) -> CheckResult:
    """Positions open at the snapshot rebuild the snapshot tick book exactly."""
    gross: dict[int, int] = {}
    net: dict[int, int] = {}
    active = 0
    for lo, hi, liq in start.select("tick_lower", "tick_upper", "liquidity").iter_rows():
        for t, sign in ((lo, 1), (hi, -1)):
            gross[t] = gross.get(t, 0) + liq
            net[t] = net.get(t, 0) + sign * liq
        if lo <= meta["tick"] < hi:
            active += liq
    chain = {
        t: (g, nn)
        for t, g, nn in snapshot_ticks.select(
            "tick", "liquidity_gross", "liquidity_net"
        ).iter_rows()
    }
    bad: list[dict[str, Any]] = []
    n_bad = 0
    for t in sorted(set(chain) | set(gross)):
        rebuilt = (gross.get(t, 0), net.get(t, 0))
        if chain.get(t, (0, 0)) != rebuilt:
            n_bad += 1
            if len(bad) < MAX_LISTED:
                bad.append({"tick": t, "onchain": chain.get(t), "rebuilt": rebuilt})
    active_ok = active == meta["liquidity"]
    return CheckResult(
        "L5 positions rebuild the snapshot tick book",
        n_bad == 0 and active_ok and start.height > 0,
        {
            "positions_open_at_snapshot": start.height,
            "ticks_compared": len(set(chain) | set(gross)),
            "tick_mismatches": n_bad,
            "active_liquidity_matches": active_ok,
        },
        bad,
    )


_L7_KEY = [
    "block_number",
    "log_index",
    "event",
    "owner",
    "tick_lower",
    "tick_upper",
    "amount",
    "amount0",
    "amount1",
]


def check_l7(
    window_events: pl.DataFrame, history_window: pl.DataFrame, data: LedgerData
) -> CheckResult:
    """The history's window events equal events.parquet, and each belongs to one position."""
    kinds = ["mint", "burn", "collect"]

    def keyed(df: pl.DataFrame) -> set[tuple[Any, ...]]:
        return set(df.filter(pl.col("event").is_in(kinds)).select(_L7_KEY).iter_rows())

    ours, theirs = keyed(window_events), keyed(history_window)
    missing, extra = ours - theirs, theirs - ours
    noop = {k for k in ours if (k[0], k[1]) in data.noop_collects}
    unassigned = [k for k in ours if (k[0], k[1]) not in data.pool_event_position and k not in noop]
    listed = [
        {"block": k[0], "log_index": k[1], "issue": "missing_in_history"}
        for k in sorted(missing)[:MAX_LISTED]
    ]
    listed += [
        {"block": k[0], "log_index": k[1], "issue": "no_position"}
        for k in sorted(unassigned)[:MAX_LISTED]
    ]
    return CheckResult(
        "L7 history complete and every event assigned",
        not missing and not extra and not unassigned and len(ours) > 0,
        {
            "window_liquidity_events": len(ours),
            "missing_in_history": len(missing),
            "extra_in_history": len(extra),
            "without_position": len(unassigned),
            "noop_collects": len(noop),
        },
        listed,
    )


def check_l3(ledger: "Ledger", end_state: pl.DataFrame) -> CheckResult:
    """The contract mirror equals the chain at the end of the window, and the start state
    matched the rebuilt positions (no start mismatches)."""
    bad: list[dict[str, Any]] = []
    n_bad = 0
    for r in end_state.iter_rows(named=True):
        if r["kind"] == "pool_key":
            m = ledger.keys.get((r["owner"], r["tick_lower"], r["tick_upper"]))
        else:
            m = ledger.token_mirror(r["token_id"])
        if not r["found"]:  # a burned NFT: NPM.burn requires zero liquidity and zero owed
            got: tuple[int, ...] | None = None if m is None else (m.liquidity, m.owed0, m.owed1)
            want: tuple[int, ...] = (0, 0, 0)
        else:
            got = None if m is None else (m.liquidity, m.last0, m.last1, m.owed0, m.owed1)
            want = (
                r["liquidity"],
                hex_u256(r["fee_growth_inside0_last"]),
                hex_u256(r["fee_growth_inside1_last"]),
                r["tokens_owed0"],
                r["tokens_owed1"],
            )
        if got != want:
            n_bad += 1
            if len(bad) < MAX_LISTED:
                bad.append(
                    {
                        "kind": r["kind"],
                        "owner": r["owner"],
                        "token_id": r["token_id"],
                        "tick_lower": r["tick_lower"],
                        "onchain": want,
                        "mirror": got,
                    }
                )
    for s in ledger.start_mismatches[:MAX_LISTED]:
        bad.append({"start": s})
    return CheckResult(
        "L3 position state matches the chain at both ends",
        n_bad == 0 and not ledger.start_mismatches and end_state.height > 0,
        {
            "compared": end_state.height,
            "mismatches": n_bad,
            "start_mismatches": len(ledger.start_mismatches),
        },
        bad,
    )


def check_l4(ledger: "Ledger", end_state: pl.DataFrame, snapshot_block: int) -> CheckResult:
    """Positions opened, closed and fully collected inside the window: fees = collected -
    withdrawn principal, exactly (fully collected = the chain owes nothing at the end)."""
    chain_owed: dict[Any, tuple[int, int]] = {}
    for r in end_state.iter_rows(named=True):
        owed = (int(r["tokens_owed0"] or 0), int(r["tokens_owed1"] or 0)) if r["found"] else (0, 0)
        if r["kind"] == "pool_key":
            chain_owed[(r["owner"], r["tick_lower"], r["tick_upper"])] = owed
        else:
            chain_owed[r["token_id"]] = owed
    flows = ledger.data.flows.filter(pl.col("block_number") > snapshot_block)
    collected = (
        flows.filter(pl.col("event") == "collect")
        .group_by("position_id")
        .agg(pl.col("amount0").sum().alias("c0"), pl.col("amount1").sum().alias("c1"))
    )
    principal = (
        flows.filter(pl.col("event").is_in(["burn", "decrease"]))
        .group_by("position_id")
        .agg(pl.col("amount0").sum().alias("p0"), pl.col("amount1").sum().alias("p1"))
    )
    sums = {r[0]: r[1:] for r in collected.iter_rows()}
    princ = {r[0]: r[1:] for r in principal.iter_rows()}
    pos = {r["position_id"]: r for r in ledger.data.positions.iter_rows(named=True)}
    bad: list[dict[str, Any]] = []
    checked = n_bad = 0
    for pid, acc in ledger.accounts.items():
        p = pos[pid]
        if (
            p["first_block"] <= snapshot_block
            or acc.liquidity != 0
            or acc.carried_owed
            or acc.owed_handed_on
        ):
            continue
        ref = (
            p["token_id"] if p["kind"] == "nft" else (p["owner"], p["tick_lower"], p["tick_upper"])
        )
        if chain_owed.get(ref) != (0, 0):
            continue
        c0, c1 = sums.get(pid, (0, 0))
        p0, p1 = princ.get(pid, (0, 0))
        checked += 1
        if (acc.fees0, acc.fees1) != (c0 - p0, c1 - p1):
            n_bad += 1
            if len(bad) < MAX_LISTED:
                bad.append(
                    {
                        "position_id": pid,
                        "engine": (acc.fees0, acc.fees1),
                        "collected_minus_principal": (c0 - p0, c1 - p1),
                    }
                )
    return CheckResult(
        "L4 fees equal Collect minus principal",
        n_bad == 0 and checked > 0,
        {"positions_checked": checked, "mismatches": n_bad},
        bad,
    )
