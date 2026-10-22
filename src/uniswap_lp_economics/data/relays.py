"""Relay-reported proposer payments for a random sample of window blocks (spec D6).

Free public endpoints (`proposer_payload_delivered`); used only to cross-check the on-chain
proposer payment (a reported check). Resumable: blocks already in the file are not re-queried.
"""

import random
import time
from pathlib import Path
from typing import Any

import httpx
import polars as pl

from uniswap_lp_economics.config import N_RELAY_SAMPLES, RELAYS
from uniswap_lp_economics.io import read_exact, write_exact
from uniswap_lp_economics.lp.payouts import HOLDOUT_PER_STRATUM, HOLDOUT_SEED, draw_holdout

RELAY_FILE = "relays.parquet"
HOLDOUT_FILE = "relay_holdout.parquet"
PATH = "/relay/v1/data/bidtraces/proposer_payload_delivered"
RELAY_SCHEMA: dict[str, Any] = {
    "block_number": pl.Int64,
    "relay": pl.String,
    "found": pl.Boolean,
    "value_wei": pl.Int128,
    "proposer_fee_recipient": pl.String,
    "builder_pubkey": pl.String,
    # Not-found rows only: relay base URLs (comma-separated) that were skipped by the circuit
    # breaker or failed after retries, i.e. did not give a definite answer. Null: every relay
    # answered, or (rows fetched before this column existed) unknown.
    "relays_unchecked": pl.String,
    # Which pass produced the row: "seen" (the base sample, or rows fetched before this column
    # existed), "retry" (re-queried by `retry_unchecked`), "holdout" (the holdout draw).
    "round": pl.String,
}
_RETRIES = 3
MAX_CONSECUTIVE_FAILED_BLOCKS = 3


def sample_blocks(first: int, last: int, n: int, seed: int = 42) -> list[int]:
    return sorted(random.Random(seed).sample(range(first, last + 1), n))


def _get(
    client: httpx.Client,
    url: str,
    block: int,
    backoff_s: float,
    params: dict[str, Any] | None = None,
    timeout_s: float = 30,
) -> list[Any] | None:
    """The relay's payload list for a block: a non-empty list when it delivered one, `[]` when it
    gave a definite answer without a payload (a 200 with an empty or non-list body, or a 4xx
    other than 429), and `None` when it failed (retries exhausted).

    Network errors, timeouts, 429, 5xx and a 200 whose body is not JSON are retried with backoff
    (no sleep after the last attempt)."""
    for attempt in range(_RETRIES):
        try:
            r = client.get(url, params=params or {"block_number": block}, timeout=timeout_s)
            if r.status_code == 200:
                body = r.json()
                return body if isinstance(body, list) else []
            if r.status_code != 429 and r.status_code < 500:
                return []
        except (httpx.RequestError, ValueError):  # ValueError: invalid JSON
            pass
        if attempt < _RETRIES - 1:
            time.sleep(backoff_s * 2**attempt)
    return None


class RelayBreaker:
    """Circuit breaker: a relay that failed on `max_failed` consecutive blocks where it was
    queried is skipped for the rest of the run. Any non-failed answer resets its counter."""

    def __init__(self, max_failed: int = MAX_CONSECUTIVE_FAILED_BLOCKS) -> None:
        self.max_failed = max_failed
        self.failed_blocks: dict[str, int] = {}
        self.skipped: set[str] = set()

    def record(self, relay: str, failed: bool) -> None:
        if not failed:
            self.failed_blocks[relay] = 0
            return
        self.failed_blocks[relay] = self.failed_blocks.get(relay, 0) + 1
        if self.failed_blocks[relay] >= self.max_failed and relay not in self.skipped:
            self.skipped.add(relay)
            print(f"  skipping {relay} for the rest of the run: failed on {self.max_failed} blocks")


def query_block(
    client: httpx.Client,
    block: int,
    relays: tuple[str, ...] = RELAYS,
    backoff_s: float = 1.0,
    breaker: RelayBreaker | None = None,
    timeout_s: float = 30,
) -> dict[str, Any]:
    """The first relay (in order) that delivered the block's payload, else a not-found row that
    lists the relays that were skipped or failed (`relays_unchecked`)."""
    unchecked: list[str] = []
    for relay in relays:
        if breaker is not None and relay in breaker.skipped:
            unchecked.append(relay)
            continue
        payloads = _get(client, relay + PATH, block, backoff_s, timeout_s=timeout_s)
        if breaker is not None:
            breaker.record(relay, payloads is None)
        if payloads is None:
            unchecked.append(relay)
        elif payloads:
            p = payloads[0]
            return {
                "block_number": block,
                "relay": relay,
                "found": True,
                "value_wei": int(p["value"]),
                "proposer_fee_recipient": str(p.get("proposer_fee_recipient", "")).lower(),
                "builder_pubkey": p.get("builder_pubkey"),
                "relays_unchecked": None,
            }
    return {
        "block_number": block,
        "relay": None,
        "found": False,
        "value_wei": None,
        "proposer_fee_recipient": None,
        "builder_pubkey": None,
        "relays_unchecked": ",".join(unchecked) if unchecked else None,
    }


def _read(out: Path) -> pl.DataFrame:
    """The relay file in the current schema. Columns missing from an older file read as: no
    `relays_unchecked` (unknown, not refetched), `round` "seen"."""
    done = read_exact(out) if out.exists() else pl.DataFrame(schema=RELAY_SCHEMA)
    for col, fill in (("relays_unchecked", None), ("round", "seen")):
        if col not in done.columns:
            done = done.with_columns(pl.lit(fill, dtype=pl.String).alias(col))
    return done.select(list(RELAY_SCHEMA))


def fetch_relay_sample(
    raw_dir: Path,
    first: int,
    last: int,
    n: int = N_RELAY_SAMPLES,
    client: httpx.Client | None = None,
    relay_urls: tuple[str, ...] = RELAYS,
) -> Path:
    out = raw_dir / RELAY_FILE
    raw_dir.mkdir(parents=True, exist_ok=True)
    done = _read(out)
    breaker = RelayBreaker()
    seen = set(done["block_number"].to_list())
    todo = [b for b in sample_blocks(first, last, n) if b not in seen]
    rows: list[dict[str, Any]] = []
    own = client is None
    http = client or httpx.Client(follow_redirects=True)
    try:
        for i, b in enumerate(todo):
            rows.append({**query_block(http, b, relay_urls, breaker=breaker), "round": "seen"})
            if (i + 1) % 100 == 0:
                write_exact(pl.concat([done, pl.DataFrame(rows, schema=RELAY_SCHEMA)]), out)
                print(f"  {i + 1}/{len(todo)} blocks")
    finally:
        # Also on an error or interrupt: keep every block queried so far.
        if rows or not out.exists():
            write_exact(pl.concat([done, pl.DataFrame(rows, schema=RELAY_SCHEMA)]), out)
        if own:
            http.close()
    return out


def retry_unchecked(
    raw_dir: Path,
    client: httpx.Client | None = None,
    relay_urls: tuple[str, ...] = RELAYS,
    pace_s: float = 0.5,
    timeout_s: float = 60,
) -> int:
    """Re-query the not-found blocks a relay never answered (`relays_unchecked` set), paced and
    with a fresh breaker and a longer timeout. Each such row is replaced in place and marked
    `round = "retry"`, found or not; holdout rows are retried too but stay "holdout". Returns the
    number of blocks retried."""
    out = raw_dir / RELAY_FILE
    done = _read(out)
    todo = done.filter(~pl.col("found") & pl.col("relays_unchecked").is_not_null())
    todo_blocks = todo["block_number"].to_list()
    holdout = set(todo.filter(pl.col("round") == "holdout")["block_number"].to_list())
    keep = done.filter(~pl.col("block_number").is_in(todo_blocks))
    breaker = RelayBreaker()
    rows: list[dict[str, Any]] = []
    own = client is None
    http = client or httpx.Client(follow_redirects=True)

    def save() -> None:  # blocks not retried yet stay in the file as they were
        pending = todo.filter(~pl.col("block_number").is_in([r["block_number"] for r in rows]))
        write_exact(pl.concat([keep, pending, pl.DataFrame(rows, schema=RELAY_SCHEMA)]), out)

    try:
        for i, b in enumerate(todo_blocks):
            if i:
                time.sleep(pace_s)
            row = query_block(http, b, relay_urls, breaker=breaker, timeout_s=timeout_s)
            # A holdout row stays in the holdout: its membership is not a retry's to rewrite.
            rows.append({**row, "round": "holdout" if b in holdout else "retry"})
            if (i + 1) % 100 == 0:
                # Rows not retried yet must stay in the file: write them back with the new ones.
                save()
                print(f"  {i + 1}/{len(todo_blocks)} blocks")
    finally:
        if rows:
            save()
        if own:
            http.close()
    left = pl.DataFrame(rows, schema=RELAY_SCHEMA).filter(pl.col("relays_unchecked").is_not_null())
    print(f"  retried {len(rows)} blocks; {left.height} still unchecked")
    for relay, n in left["relays_unchecked"].str.split(",").explode().value_counts().iter_rows():
        print(f"    {relay}: {n}")
    return len(rows)


def fetch_holdout(
    raw_dir: Path,
    classes: pl.DataFrame,
    client: httpx.Client | None = None,
    relay_urls: tuple[str, ...] = RELAYS,
    pace_s: float = 0.5,
    timeout_s: float = 60,
    n: int = HOLDOUT_PER_STRATUM,
) -> Path:
    """The holdout that checks the payout rule against the relay: `n` payout blocks and `n` others,
    seed 44, the blocks already in the relay file excluded. The draw is written to disk before the
    first relay call and never redrawn; a rerun reads it and queries only the blocks still missing
    from the relay file (rows marked `round = "holdout"`). Returns the holdout file's path."""
    out = raw_dir / RELAY_FILE
    path = raw_dir / HOLDOUT_FILE
    raw_dir.mkdir(parents=True, exist_ok=True)
    done = _read(out)
    if path.exists():
        holdout = read_exact(path)
        if set(holdout["seed"].to_list()) != {HOLDOUT_SEED}:
            raise ValueError(f"{path} was drawn with another seed than {HOLDOUT_SEED}")
    else:
        holdout = draw_holdout(classes, set(done["block_number"].to_list()), n=n)
        write_exact(holdout, path)
    seen = set(done["block_number"].to_list())
    todo = [b for b in holdout["block_number"].to_list() if b not in seen]
    breaker = RelayBreaker()
    rows: list[dict[str, Any]] = []
    own = client is None
    http = client or httpx.Client(follow_redirects=True)

    def save() -> None:
        write_exact(pl.concat([done, pl.DataFrame(rows, schema=RELAY_SCHEMA)]), out)

    try:
        for i, b in enumerate(todo):
            if i:
                time.sleep(pace_s)
            row = query_block(http, b, relay_urls, breaker=breaker, timeout_s=timeout_s)
            rows.append({**row, "round": "holdout"})
            if (i + 1) % 100 == 0:
                save()
                print(f"  {i + 1}/{len(todo)} holdout blocks")
    finally:
        if rows:
            save()
        if own:
            http.close()
    print(f"  holdout: {len(rows)} blocks queried, {holdout.height} drawn")
    return path
