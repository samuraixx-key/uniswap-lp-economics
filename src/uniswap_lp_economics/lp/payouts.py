"""Who pays the proposer (spec section 4): every window block gets one of five classes from chain
data only. The relay is not used here; it checks the classes on a holdout later."""

import random

import polars as pl

from uniswap_lp_economics.data.chain_state import parse_code

EMPTY, PAID, PAYOUT = "empty", "paid", "payout"
PROPOSER_IS_FEE_RECIPIENT, UNEXPLAINED = "proposer_is_fee_recipient", "unexplained"
CLASSES = (EMPTY, PAID, PAYOUT, PROPOSER_IS_FEE_RECIPIENT, UNEXPLAINED)
PAYOUT_MIN_BLOCKS = 50
PAYOUT_MIN_POSITIVE_SHARE = 0.99
HOLDOUT_SEED = 44
HOLDOUT_PER_STRATUM = 300
SIMPLE_TRANSFER_GAS = 21_000
RECIPIENT_TYPES = ("wallet", "7702_wallet", "contract")


def payout_pairs(block_revenue: pl.DataFrame, min_blocks: int = PAYOUT_MIN_BLOCKS) -> pl.DataFrame:
    """(miner, last_from) where a sender other than the fee recipient sent the block's last
    transaction in at least `min_blocks` (PAYOUT_MIN_BLOCKS) of the miner's blocks, with value > 0
    in at least PAYOUT_MIN_POSITIVE_SHARE of them. Learned from block_revenue only."""
    return (
        block_revenue.filter(pl.col("last_from").is_not_null())
        .filter(pl.col("last_from") != pl.col("miner"))
        .group_by("miner", "last_from")
        .agg(n=pl.len(), positive=(pl.col("last_value_wei") > 0).sum())
        .filter(
            (pl.col("n") >= min_blocks)
            & (pl.col("positive") >= PAYOUT_MIN_POSITIVE_SHARE * pl.col("n"))
        )
        .select("miner", "last_from")
        .sort("miner", "last_from")
    )


def block_classes(
    block_revenue: pl.DataFrame, last_tx: pl.DataFrame, min_blocks: int = PAYOUT_MIN_BLOCKS
) -> pl.DataFrame:
    """One class per block, first match wins: empty (no transactions) -> paid (last transaction
    from the fee recipient) -> payout (last transaction from the miner's payout address, value > 0,
    to someone other than the miner) -> proposer_is_fee_recipient (the miner has no paid or payout
    block anywhere, so it is taken to be the proposer) -> unexplained. `payout_pair` marks blocks
    of a payout pair, which `class_counts` needs for top-ups. `min_blocks` is the pair threshold;
    only the stability table varies it."""
    df = block_revenue.select("block_number", "miner", "last_from", "last_value_wei").join(
        last_tx.select("block_number", "to_address", "receipt_gas_used"),
        on="block_number",
        how="left",
    )
    missing = df.filter(pl.col("last_from").is_not_null() & pl.col("receipt_gas_used").is_null())
    if missing.height:
        first_missing = missing.sort("block_number")["block_number"][0]
        raise ValueError(f"block {first_missing} has transactions but no last_tx row")
    pairs = payout_pairs(block_revenue, min_blocks).with_columns(payout_pair=pl.lit(True))
    df = df.join(pairs, on=["miner", "last_from"], how="left").with_columns(
        pl.col("payout_pair").fill_null(False)
    )
    payout = (
        pl.col("payout_pair")
        & (pl.col("last_value_wei") > 0)
        & pl.col("to_address").is_not_null()
        & (pl.col("to_address") != pl.col("miner"))
    )
    first = (
        pl.when(pl.col("last_from").is_null())
        .then(pl.lit(EMPTY))
        .when(pl.col("last_from") == pl.col("miner"))
        .then(pl.lit(PAID))
        .when(payout)
        .then(pl.lit(PAYOUT))
    )
    return (
        df.with_columns(cls=first)
        .with_columns(pays=pl.col("cls").is_in([PAID, PAYOUT]).any().over("miner"))
        .with_columns(
            cls=pl.when(pl.col("cls").is_not_null())
            .then(pl.col("cls"))
            .when(~pl.col("pays"))
            .then(pl.lit(PROPOSER_IS_FEE_RECIPIENT))
            .otherwise(pl.lit(UNEXPLAINED))
        )
        .drop("pays")
        .sort("block_number")
    )


def class_counts(classes: pl.DataFrame) -> dict[str, int]:
    """Blocks per class, plus `n_top_up`: payout-pair blocks whose last transaction goes to the
    fee recipient itself (the builder topping up its payout address, not paying a proposer)."""
    counts = {c: int((classes["cls"] == c).sum()) for c in CLASSES}
    top_up = classes["payout_pair"] & (classes["to_address"] == classes["miner"])
    return {**counts, "n_top_up": int(top_up.sum())}


def draw_holdout(
    classes: pl.DataFrame,
    exclude: set[int],
    seed: int = HOLDOUT_SEED,
    n: int = HOLDOUT_PER_STRATUM,
) -> pl.DataFrame:
    """`n` payout blocks and `n` blocks of the other classes with a payment (paid,
    proposer_is_fee_recipient, unexplained; empty blocks are in neither), none in `exclude`.
    Candidates are sorted by block number before sampling, so the draw depends only on the seed
    and the candidates. Raises if a stratum has fewer than `n` candidates."""
    strata = {
        "payout": [PAYOUT],
        "rest": [PAID, PROPOSER_IS_FEE_RECIPIENT, UNEXPLAINED],
    }
    rng = random.Random(seed)
    parts = []
    for stratum, cls in strata.items():
        cand = sorted(
            classes.filter(pl.col("cls").is_in(cls) & ~pl.col("block_number").is_in(list(exclude)))[
                "block_number"
            ].to_list()
        )
        if len(cand) < n:
            raise ValueError(f"holdout stratum {stratum!r} has {len(cand)} candidates, need {n}")
        parts.append(
            pl.DataFrame(
                {"block_number": sorted(rng.sample(cand, n)), "stratum": stratum, "seed": seed},
                schema={"block_number": pl.Int64, "stratum": pl.String, "seed": pl.Int64},
            )
        )
    return pl.concat(parts)


def _payments_with_code(classes: pl.DataFrame) -> pl.DataFrame:
    return classes.filter(
        (pl.col("cls") == PAYOUT) & (pl.col("receipt_gas_used") > SIMPLE_TRANSFER_GAS)
    )


def recipient_reads(classes: pl.DataFrame) -> list[tuple[str, int]]:
    """(address, block) code reads for the payout recipients: each distinct `to_address` of a
    payout block with gas above 21,000 (a plain transfer needs no read, it is a wallet), at its
    first and last such block."""
    g = (
        _payments_with_code(classes)
        .group_by("to_address")
        .agg(first=pl.col("block_number").min(), last=pl.col("block_number").max())
    )
    reads = {(a, int(b)) for a, f, la in g.iter_rows() for b in (f, la)}
    return sorted(reads)


def _code_type(code: str) -> str:
    has_code, delegate = parse_code(code)
    return "7702_wallet" if delegate else "contract" if has_code else "wallet"


def recipient_types(
    classes: pl.DataFrame, code: pl.DataFrame, block_usd: pl.DataFrame
) -> tuple[pl.DataFrame, int]:
    """Payout blocks by recipient type (wallet, 7702_wallet, contract): payments (one per block),
    blocks, paid_eth, builder_paid_usd (0 where `block_usd` has no row). A plain 21,000-gas
    transfer is a wallet. Otherwise the type comes from the recipient's code at its first and last
    payout block: any EIP-7702 delegate -> 7702_wallet, else any code -> contract, else wallet.
    Also returns the number of recipients whose two reads give different types."""
    have = {(a, b): c for a, b, c in code.select("address", "block", "code").iter_rows()}
    types: dict[str, str] = {}
    differing = 0
    for address, group in _group_reads(recipient_reads(classes)).items():
        kinds = []
        for block in group:
            if (address, block) not in have:
                raise ValueError(
                    f"no code read for {address} at block {block}; run fetch-payout-code"
                )
            kinds.append(_code_type(have[(address, block)]))
        differing += len(set(kinds)) > 1
        types[address] = (
            "7702_wallet"
            if "7702_wallet" in kinds
            else "contract"
            if "contract" in kinds
            else "wallet"
        )
    pay = (
        classes.filter(pl.col("cls") == PAYOUT)
        .join(
            pl.DataFrame(
                {"to_address": list(types), "kind": list(types.values())},
                schema={"to_address": pl.String, "kind": pl.String},  # empty when no code reads
            ),
            on="to_address",
            how="left",
        )
        .join(block_usd.select("block_number", "builder_paid_usd"), on="block_number", how="left")
        .with_columns(
            type=pl.when(pl.col("receipt_gas_used") > SIMPLE_TRANSFER_GAS)
            .then(pl.col("kind"))
            .otherwise(pl.lit("wallet")),
            builder_paid_usd=pl.col("builder_paid_usd").fill_null(0.0),
        )
    )
    rows = []
    for t in RECIPIENT_TYPES:
        sub = pay.filter(pl.col("type") == t)
        rows.append(
            {
                "type": t,
                "payments": sub.height,
                "blocks": sub.height,
                "paid_eth": float(sum(sub["last_value_wei"].to_list())) / 1e18,
                "builder_paid_usd": float(sub["builder_paid_usd"].sum()),
            }
        )
    return pl.DataFrame(
        rows, schema_overrides={"payments": pl.Int64, "blocks": pl.Int64}
    ), differing


def _group_reads(reads: list[tuple[str, int]]) -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    for address, block in reads:
        out.setdefault(address, []).append(block)
    return out
