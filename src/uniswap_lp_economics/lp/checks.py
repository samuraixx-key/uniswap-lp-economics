"""Checks L1-L7 (gated) and the reported checks of sub-project 3 (spec section 9)."""

from typing import TYPE_CHECKING, Any

import polars as pl

from uniswap_lp_economics.arbprofit import coinbase_payments
from uniswap_lp_economics.io import hex_u256
from uniswap_lp_economics.lp.pnl import LP_TYPES
from uniswap_lp_economics.lp.positions import LedgerData
from uniswap_lp_economics.validate import MAX_LISTED, CheckResult

if TYPE_CHECKING:
    from uniswap_lp_economics.lp.ledger import Ledger


def check_l1(swap_fees: pl.DataFrame, engine_unmatched: int) -> CheckResult:
    """Every swap re-simulated bit-exactly in one of the reproduction modes, both in
    `swap_fees` (sub-project 2's replay) and in the LP engine's own replay (`engine_unmatched`:
    swaps the engine could not reproduce from its state, which would accrue no fees)."""
    modes = swap_fees.group_by("mode").len().drop_nulls("mode").sort("mode")  # stable order
    counts: dict[str, Any] = dict(zip(modes["mode"].to_list(), modes["len"].to_list(), strict=True))
    bad = swap_fees.filter(pl.col("mode").is_null())
    listed = [
        {"block": b, "log_index": li}
        for b, li in bad.select("block_number", "log_index").head(MAX_LISTED).iter_rows()
    ]
    return CheckResult(
        "L1 every swap reproduced bit-exactly",
        bad.height == 0 and engine_unmatched == 0 and swap_fees.height > 0,
        {
            "swaps": swap_fees.height,
            "unreproduced": bad.height,
            "by_mode": counts,
            "engine_unmatched": engine_unmatched,
        },
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


L6_REL_TOL = 1e-9


def check_l6(
    steps: pl.DataFrame,
    accounts: pl.DataFrame,
    aligned: pl.DataFrame,
    swap_fees: pl.DataFrame,
    n_window_flows: int,
) -> CheckResult:
    """Accounting identities (spec L6, plan Ruling 13).

    Pool-level LP fees are summed over every accrued step, flash fees included (a flash grows fee
    growth like a swap fee). Position fees floor at every checkpoint, so they may fall short of
    the pool's by at most one raw unit per accrued step, one per window flow and two per account,
    and can never exceed them."""
    accrued = steps.filter(pl.col("accrued"))
    pool0 = int(accrued.filter(pl.col("zero_for_one"))["lp_fee"].sum())
    pool1 = int(accrued.filter(~pl.col("zero_for_one"))["lp_fee"].sum())
    pos0, pos1 = int(accounts["fees_raw0"].sum()), int(accounts["fees_raw1"].sum())
    tol = accrued.height + n_window_flows + 2 * accounts.height
    fees_ok = 0 <= pool0 - pos0 <= tol and 0 <= pool1 - pos1 <= tol
    pool_lvr = float(accrued["lvr_0"].sum())
    pos_lvr = float(accounts["lvr_0"].sum())
    lvr_ok = abs(pool_lvr - pos_lvr) <= L6_REL_TOL * max(1.0, abs(pool_lvr))
    fee_usd = aligned.join(swap_fees, on=["block_number", "log_index"], how="left").select(
        pl.when(pl.col("fee_token") == "USDC")
        .then(pl.col("fee_raw").cast(pl.Float64) / 1e6)
        .when(pl.col("fee_token") == "WETH")
        .then(pl.col("fee_raw").cast(pl.Float64) / 1e18 * pl.col("p_cex_0"))
        .otherwise(0.0)
        .alias("fee_usd"),
        "markout_usd_0",
    )
    identity = float((fee_usd["fee_usd"] + fee_usd["markout_usd_0"]).sum())
    all_lvr = float(steps["lvr_0"].sum())
    identity_ok = abs(all_lvr - identity) <= L6_REL_TOL * max(1.0, abs(all_lvr))
    return CheckResult(
        "L6 accounting identities",
        fees_ok and lvr_ok and identity_ok and steps.height > 0,
        {
            "pool_lp_fees_raw": [pool0, pool1],
            "position_fees_raw": [pos0, pos1],
            "fee_shortfall_tolerance": tol,
            "pool_lvr_0_usd": pool_lvr,
            "position_lvr_0_usd": pos_lvr,
            "markout_identity_lvr_usd": identity,
            "all_steps_lvr_0_usd": all_lvr,
        },
    )


def _relay_matches(found: pl.DataFrame) -> tuple[int, int]:
    """(within 1 wei, within 1% of the relay value) of found rows joined with the split."""
    if not found.height:
        return 0, 0
    diff = (found["value_wei"] - found["payment_wei"]).abs()
    within = diff.cast(pl.Float64) <= 0.01 * found["value_wei"].cast(pl.Float64)
    return int((diff <= 1).sum()), int(within.sum())


def check_r1_relays(relays: pl.DataFrame, split: pl.DataFrame) -> CheckResult:
    """Relay-reported proposer payment vs Q_b, with a breakdown by block type: `paid` (the last
    transaction is from the fee recipient) and `self_built` (it is not, so Q_b = R_b). Not-found
    blocks are split by whether some relay gave no answer (`relays_unchecked`); both counts are
    None for a relay file written before that column existed."""
    found = relays.filter(pl.col("found"))
    both = found.join(split.select("block_number", "payment_wei"), on="block_number", how="inner")
    exact, within = _relay_matches(both)
    typed = relays.join(
        split.select("block_number", "miner", "revenue_wei", "payment_wei", "self_built"),
        on="block_number",
        how="inner",
    )
    has_recipient = "proposer_fee_recipient" in relays.columns
    by_type: dict[str, dict[str, Any]] = {}
    for name, flag in (("paid", False), ("self_built", True)):
        rows = typed.filter(pl.col("self_built") == flag)
        hits = rows.filter(pl.col("found"))
        m1, m1pct = _relay_matches(hits)
        with_revenue = hits.filter(pl.col("revenue_wei") > 0)
        ratio = with_revenue["value_wei"].cast(pl.Float64) / with_revenue["revenue_wei"].cast(
            pl.Float64
        )
        by_type[name] = {
            "sampled": rows.height,
            "found": hits.height,
            "match_within_1_wei": m1,
            "match_within_1pct": m1pct,
            # Relay-reported payment / on-chain builder revenue R_b, and found blocks whose relay
            # names a proposer fee recipient other than the block's fee recipient.
            "median_relay_value_over_revenue": (
                float(ratio.median()) if with_revenue.height else None  # type: ignore[arg-type]
            ),
            "relay_recipient_not_fee_recipient": (
                int((hits["proposer_fee_recipient"] != hits["miner"]).sum())
                if has_recipient
                else None
            ),
        }
    not_found = relays.filter(~pl.col("found"))
    unchecked: int | None = None
    answered: int | None = None
    if "relays_unchecked" in relays.columns:
        unchecked = int(not_found["relays_unchecked"].is_not_null().sum())
        answered = not_found.height - unchecked
    return CheckResult(
        "R1 relay vs on-chain proposer payment (reported)",
        True,
        {
            "sampled": relays.height,
            "found_on_a_relay": found.height,  # before the join with our per-block split
            "compared_with_on_chain": both.height,
            "match_within_1_wei": exact,
            "match_within_1pct": within,
            "by_block_type": by_type,
            "not_found_unchecked": unchecked,
            "not_found_all_answered": answered,
        },
        reported=True,
    )


def check_r2_traces_vs_alchemy(
    tx_direct: pl.DataFrame,
    bot_transfers: pl.DataFrame,
    blocks: pl.DataFrame,
    pool_txs: pl.DataFrame,
) -> CheckResult:
    """Top-bot payments to the fee recipient (Alchemy) vs the trace-based direct payments, on
    the same population: `tx_direct` only covers transactions touching our pool, while the
    Alchemy transfers cover every transaction of the bots, so they are cut to `pool_txs`."""
    alchemy = coinbase_payments(bot_transfers, blocks).join(
        pool_txs.select("tx_hash").unique(), on="tx_hash", how="semi"
    )
    both = alchemy.join(tx_direct, on="tx_hash", how="left")
    same = (
        int((both["coinbase_wei"] == both["direct_wei"].fill_null(0)).sum()) if both.height else 0
    )
    return CheckResult(
        "R2 traces vs Alchemy builder payments, top bots (reported)",
        True,
        {"alchemy_pool_txs_with_payment": alchemy.height, "same_amount_in_traces": same},
        reported=True,
    )


def check_r3_lp_types(positions: pl.DataFrame) -> CheckResult:
    order = pl.DataFrame({"lp_type": list(LP_TYPES), "_o": list(range(len(LP_TYPES)))})
    by = (
        positions.group_by("lp_type")
        .agg(positions=pl.len(), fee_usd=pl.col("fee_usd").sum())
        .join(order, on="lp_type", how="left")
        .sort("_o", "lp_type", nulls_last=True)  # pnl.LP_TYPES order, stable between runs
        .drop("_o")
    )
    return CheckResult(
        "R3 LP-type coverage (reported)", True, {"by_lp_type": by.to_dicts()}, reported=True
    )


def check_r4_transferred(positions_table: pl.DataFrame, active_ids: list[str]) -> CheckResult:
    active = positions_table.filter(pl.col("position_id").is_in(active_ids))
    return CheckResult(
        "R4 NFT positions transferred while open (reported)",
        True,
        {"window_active": active.height, "transferred": int(active["transferred"].sum())},
        reported=True,
    )


def check_r5_null_12s(null_12s_steps: int, steps: pl.DataFrame) -> CheckResult:
    return CheckResult(
        "R5 steps without a 12 s reference (reported)",
        True,
        {"steps": steps.height, "without_12s_reference": null_12s_steps},
        reported=True,
    )
