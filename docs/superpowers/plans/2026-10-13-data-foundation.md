# Data Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the downloaded Uniswap V3 USDC/WETH 0.05% pool logs into validated tables: decoded events, swaps,
a replayable tick book and Binance reference prices. A validation report proves them correct against the chain.

**Architecture:**
- Pure modules hold the maths and state, with no network or files: `abi`, `v3math`, `events`, `tickbook`.
- Thin I/O modules fetch and store data: `rpc`, `snapshot`, `data/binance`, `data/bigquery`.
- `build` turns raw files into the interim tables. `validate` replays every event against the reconstructed tick
  book and on-chain samples, then writes a PASS/FAIL report.
- `cli.py` exposes each stage, and `ulpe all` runs them in order.

**Tech Stack:** Python 3.13, uv, polars (Int128 for exact integers), httpx, google-cloud-bigquery, pycryptodome
(keccak), pytest, ruff, mypy --strict.

**Spec:** `docs/superpowers/specs/2026-10-13-data-foundation-design.md`. Read it before starting.

## Global Constraints

- Python 3.13 via uv. Run everything as `uv run <cmd>` from the repo root.
- The only new runtime dependency allowed is `pycryptodome`.
- Pool `0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640`. token0 USDC has 6 decimals, token1 WETH has 18. Fee is 500 pips,
  tick spacing 10.
- Study window is `[2026-07-01, 2026-10-01)` UTC.
- **State values are exact integers:** Python `int`, or `pl.Int128` in parquet. Floats are allowed only in readable
  or analysis columns (`amount_usdc`, `amount_eth`, `price_usd`, `*_usd`).
- **Never print, log, or put `ETH_RPC_URL` into an exception message.** The URL contains the API key.
- Tests that touch the network are marked `@pytest.mark.live` and are skipped by default.
- Before every commit, all four must pass: `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src`,
  `uv run pytest -q`.
- Every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Push after every commit
  with `git push`; the user pre-approved pushes to this private repo.

## Review Focus

1. **RPC errors must not leak the API key.** Exceptions from `RpcClient` never contain the URL, including transport
   errors. Test: Task 4 `test_errors_never_contain_url`.
2. **Rate limits can arrive in a JSON body with HTTP 200.** Alchemy may return `{"error": {"code": 429}}`, and this
   must be retried exactly like HTTP 429. Test: Task 4 `test_retries_json_rate_limit`.
3. **Binance timestamp units vary.** Spot files switched from milliseconds to microseconds (2025). Both must parse
   to the same `ts_us`. Test: Task 6 `test_parse_agg_trades_ms_and_us_agree`.
4. **A swap can end exactly on an initialized tick and the next swap can move up from it.** Liquidity must be crossed
   exactly once each way. Test: Task 3 `test_boundary_down_then_up`.
5. **A raw input may be missing.** `build` and `validate` must fail with a message naming the `ulpe` command that
   produces it, not with a polars traceback. Test: Task 7 `test_missing_raw_logs_names_command`.

## File map

| File | Responsibility | Task |
|---|---|---|
| `src/uniswap_lp_economics/abi.py` | keccak, selectors, topics, 32-byte word encode/decode | 1 |
| `src/uniswap_lp_economics/events.py` (modify) | Decode Swap/Mint/Burn/Collect/Flash/CollectProtocol/SetFeeProtocol; topics derived from signatures | 1 |
| `src/uniswap_lp_economics/v3math.py` (modify) | Exact TickMath, swap fee, protocol-fee share | 2 |
| `src/uniswap_lp_economics/tickbook.py` | `TickBook` replay state | 3 |
| `src/uniswap_lp_economics/rpc.py` | JSON-RPC client, retries, Multicall3, pool call encoders/decoders | 4 |
| `src/uniswap_lp_economics/snapshot.py` | Tick-book and sample reads; block-by-timestamp search | 5 |
| `src/uniswap_lp_economics/data/binance.py` | Verified downloads and parsing | 6 |
| `src/uniswap_lp_economics/build.py` | raw → interim tables | 7 |
| `src/uniswap_lp_economics/validate.py` | Replay, checks C1–C6, report, `require_validated` | 8 |
| `src/uniswap_lp_economics/config.py` (modify) | Window constants, paths | 5 |
| `src/uniswap_lp_economics/cli.py` (modify) | Subcommands | 5–8 |
| `scripts/make_fixture.py`, `tests/fixtures/*` | Real-data fixture for offline integration test | 9 |

One deviation from the spec's file list: on-chain sample tick reads go to a second file,
`onchain_sample_ticks.parquet`, because samples and ticks have different row shapes.

---

### Task 1: ABI helpers and full event decoding

**Files:**
- Create: `src/uniswap_lp_economics/abi.py`, `tests/test_abi.py`
- Modify: `src/uniswap_lp_economics/events.py` (rewrite), `tests/test_events.py`, `pyproject.toml` (dependency)

**Interfaces:**
- Produces:
  - `abi.keccak256(data: bytes) -> bytes`
  - `abi.selector(signature: str) -> str` (`"0x" + 8 hex`)
  - `abi.topic(signature: str) -> str` (`"0x" + 64 hex`)
  - `abi.words(hex_str: str) -> list[str]`
  - `abi.to_uint(word: str) -> int`, `abi.to_int(word: str) -> int`, `abi.to_addr(word: str) -> str`
  - `abi.enc_uint(v: int) -> str`, `abi.enc_int(v: int) -> str`, `abi.enc_addr(addr: str) -> str` (64 hex chars, no `0x`)
  - `events.decode_event(topics: list[str], data: str) -> dict[str, Any]`, where `"event"` is one of
    `swap, mint, burn, collect, flash, collect_protocol, set_fee_protocol, other`
  - `events.SWAP_TOPIC`, `MINT_TOPIC`, `BURN_TOPIC`, `COLLECT_TOPIC`, `FLASH_TOPIC`, `COLLECT_PROTOCOL_TOPIC`,
    `SET_FEE_PROTOCOL_TOPIC`, and `events.EVENT_TOPICS: dict[str, str]`

- [ ] **Step 1: Add the dependency**

Run: `uv add pycryptodome`
Expected: `pyproject.toml` lists `pycryptodome`.

- [ ] **Step 2: Write failing ABI tests** in `tests/test_abi.py`

```python
from uniswap_lp_economics import abi


def test_topic_matches_known_swap_hash() -> None:
    # Verified on 2026-10-13 against real pool logs on BigQuery.
    assert (
        abi.topic("Swap(address,address,int256,int256,uint160,uint128,int24)")
        == "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"
    )


def test_selector_matches_known_slot0() -> None:
    # 0x3850c7bd was used successfully against Alchemy on 2026-10-13.
    assert abi.selector("slot0()") == "0x3850c7bd"


def test_int_word_round_trip() -> None:
    for v in (0, 1, -1, 2**255 - 1, -(2**255)):
        assert abi.to_int(abi.enc_int(v)) == v


def test_uint_and_addr_words() -> None:
    assert abi.enc_uint(255) == "0" * 62 + "ff"
    addr = "0x" + "ab" * 20
    assert abi.to_addr(abi.enc_addr(addr)) == addr
    assert abi.words("0x" + "00" * 32 + "11" * 32) == ["00" * 32, "11" * 32]
```

- [ ] **Step 3: Run it and confirm it fails**

Run: `uv run pytest tests/test_abi.py -q`
Expected: FAIL with `ModuleNotFoundError: ... abi`.

- [ ] **Step 4: Implement `src/uniswap_lp_economics/abi.py`**

```python
"""Minimal ABI helpers: keccak, selectors, topics and 32-byte word encoding."""

from Crypto.Hash import keccak


def keccak256(data: bytes) -> bytes:
    h = keccak.new(digest_bits=256)
    h.update(data)
    return h.digest()


def selector(signature: str) -> str:
    return "0x" + keccak256(signature.encode()).hex()[:8]


def topic(signature: str) -> str:
    return "0x" + keccak256(signature.encode()).hex()


def words(hex_str: str) -> list[str]:
    body = hex_str[2:] if hex_str.startswith("0x") else hex_str
    return [body[i : i + 64] for i in range(0, len(body), 64)]


def to_uint(word: str) -> int:
    return int(word, 16)


def to_int(word: str) -> int:
    value = int(word, 16)
    return value - 2**256 if value >= 2**255 else value


def to_addr(word: str) -> str:
    return "0x" + word[-40:].lower()


def enc_uint(v: int) -> str:
    return f"{v:064x}"


def enc_int(v: int) -> str:
    return f"{v % 2**256:064x}"


def enc_addr(addr: str) -> str:
    return addr[2:].lower().rjust(64, "0")
```

- [ ] **Step 5: Run the ABI tests**

Run: `uv run pytest tests/test_abi.py -q`
Expected: 4 passed.

- [ ] **Step 6: Extend the event tests.** In `tests/test_events.py`:
  - Replace `test_unknown_topic_raises` with `test_unknown_topic_is_other`.
  - Add tests for the three new events.
  - Extend the import to include `COLLECT_PROTOCOL_TOPIC, FLASH_TOPIC, SET_FEE_PROTOCOL_TOPIC`.

```python
def test_unknown_topic_is_other() -> None:
    assert decode_event(["0x" + "00" * 32], "0x") == {"event": "other"}


def test_flash() -> None:
    data = "0x" + word(10) + word(20) + word(1) + word(2)
    ev = decode_event([FLASH_TOPIC, "0x" + addr_word(SENDER), "0x" + addr_word(OWNER)], data)
    assert ev == {
        "event": "flash", "sender": SENDER, "recipient": OWNER,
        "amount0": 10, "amount1": 20, "paid0": 1, "paid1": 2,
    }


def test_collect_protocol() -> None:
    data = "0x" + word(5) + word(6)
    ev = decode_event(
        [COLLECT_PROTOCOL_TOPIC, "0x" + addr_word(SENDER), "0x" + addr_word(OWNER)], data
    )
    assert ev == {
        "event": "collect_protocol", "sender": SENDER, "recipient": OWNER,
        "amount0": 5, "amount1": 6,
    }


def test_set_fee_protocol() -> None:
    data = "0x" + word(0) + word(0) + word(4) + word(5)
    ev = decode_event([SET_FEE_PROTOCOL_TOPIC], data)
    assert ev == {
        "event": "set_fee_protocol",
        "fee_protocol0_old": 0, "fee_protocol1_old": 0,
        "fee_protocol0_new": 4, "fee_protocol1_new": 5,
    }
```

- [ ] **Step 7: Run them and confirm they fail**

Run: `uv run pytest tests/test_events.py -q`
Expected: FAIL (ImportError for `FLASH_TOPIC`).

- [ ] **Step 8: Rewrite `src/uniswap_lp_economics/events.py`**

```python
"""Decode raw Uniswap V3 pool logs (topics + data hex) into Python values."""

from typing import Any

from uniswap_lp_economics.abi import to_addr, to_int, to_uint, topic, words

SIGNATURES = {
    "swap": "Swap(address,address,int256,int256,uint160,uint128,int24)",
    "mint": "Mint(address,address,int24,int24,uint128,uint256,uint256)",
    "burn": "Burn(address,int24,int24,uint128,uint256,uint256)",
    "collect": "Collect(address,address,int24,int24,uint128,uint128)",
    "flash": "Flash(address,address,uint256,uint256,uint256,uint256)",
    "collect_protocol": "CollectProtocol(address,address,uint128,uint128)",
    "set_fee_protocol": "SetFeeProtocol(uint8,uint8,uint8,uint8)",
}
EVENT_TOPICS = {topic(sig): name for name, sig in SIGNATURES.items()}

SWAP_TOPIC = topic(SIGNATURES["swap"])
MINT_TOPIC = topic(SIGNATURES["mint"])
BURN_TOPIC = topic(SIGNATURES["burn"])
COLLECT_TOPIC = topic(SIGNATURES["collect"])
FLASH_TOPIC = topic(SIGNATURES["flash"])
COLLECT_PROTOCOL_TOPIC = topic(SIGNATURES["collect_protocol"])
SET_FEE_PROTOCOL_TOPIC = topic(SIGNATURES["set_fee_protocol"])


def decode_event(topics: list[str], data: str) -> dict[str, Any]:
    """Decode one pool log. Unknown topics come back as {"event": "other"}."""
    kind = EVENT_TOPICS.get(topics[0].lower())
    if kind is None:
        return {"event": "other"}
    t = [words(x)[0] for x in topics[1:]]
    d = words(data)

    if kind == "swap":
        return {
            "event": kind, "sender": to_addr(t[0]), "recipient": to_addr(t[1]),
            "amount0": to_int(d[0]), "amount1": to_int(d[1]),
            "sqrt_price_x96": to_uint(d[2]), "liquidity": to_uint(d[3]), "tick": to_int(d[4]),
        }
    if kind == "flash":
        return {
            "event": kind, "sender": to_addr(t[0]), "recipient": to_addr(t[1]),
            "amount0": to_uint(d[0]), "amount1": to_uint(d[1]),
            "paid0": to_uint(d[2]), "paid1": to_uint(d[3]),
        }
    if kind == "collect_protocol":
        return {
            "event": kind, "sender": to_addr(t[0]), "recipient": to_addr(t[1]),
            "amount0": to_uint(d[0]), "amount1": to_uint(d[1]),
        }
    if kind == "set_fee_protocol":
        return {
            "event": kind,
            "fee_protocol0_old": to_uint(d[0]), "fee_protocol1_old": to_uint(d[1]),
            "fee_protocol0_new": to_uint(d[2]), "fee_protocol1_new": to_uint(d[3]),
        }

    position = {"owner": to_addr(t[0]), "tick_lower": to_int(t[1]), "tick_upper": to_int(t[2])}
    if kind == "mint":
        return {
            "event": kind, **position, "sender": to_addr(d[0]),
            "amount": to_uint(d[1]), "amount0": to_uint(d[2]), "amount1": to_uint(d[3]),
        }
    if kind == "burn":
        return {
            "event": kind, **position,
            "amount": to_uint(d[0]), "amount0": to_uint(d[1]), "amount1": to_uint(d[2]),
        }
    return {
        "event": kind, **position, "recipient": to_addr(d[0]),
        "amount0": to_uint(d[1]), "amount1": to_uint(d[2]),
    }
```

- [ ] **Step 9: Run all tests**

Run: `uv run pytest -q`
Expected: all pass. The old topic tests still pass because the constants are now derived from the signatures.

- [ ] **Step 10: Verify the new topics against real data.** The raw logs from `ulpe fetch-logs` are in `data/raw/`.

Run:
```bash
uv run python -c "import polars as pl; from uniswap_lp_economics.events import EVENT_TOPICS as T; df=pl.read_parquet('data/raw/pool_logs_*.parquet'); print(df.group_by(pl.col('topics').list.first().replace_strict(T, default='other').alias('ev')).len().sort('len').rows())"
```
Expected: no `other` row. If `other` remains, print those topic hashes and stop; the user must decide.

- [ ] **Step 11: Lint, type-check, commit, push**

```bash
uv run ruff format . && uv run ruff check . && uv run mypy src && uv run pytest -q
git add -A && git commit -m "Add ABI helpers; decode Flash, CollectProtocol, SetFeeProtocol" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" && git push
```

---

### Task 2: Exact TickMath, swap fee, protocol-fee share

**Files:**
- Modify: `src/uniswap_lp_economics/v3math.py` (append), `tests/test_v3math.py` (append)

**Interfaces:**
- Produces:
  - `MIN_TICK = -887272`, `MAX_TICK = 887272`, `MIN_SQRT_RATIO = 4295128739`,
    `MAX_SQRT_RATIO = 1461446703485210103287273052203988822378723970342`
  - `get_sqrt_ratio_at_tick(tick: int) -> int`
  - `get_tick_at_sqrt_ratio(sqrt_price_x96: int) -> int`
  - `swap_fee_raw(amount_in: int, fee_pips: int = FEE_PIPS) -> int`
  - `fee_protocol_share(fee_protocol: int, zero_for_one: bool) -> float`

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_v3math.py`:

```python
from uniswap_lp_economics.v3math import (
    MAX_SQRT_RATIO, MAX_TICK, MIN_SQRT_RATIO, MIN_TICK,
    fee_protocol_share, get_sqrt_ratio_at_tick, get_tick_at_sqrt_ratio, swap_fee_raw,
)

Q96 = 2**96


def test_tickmath_extremes_match_v3_constants() -> None:
    assert get_sqrt_ratio_at_tick(MIN_TICK) == MIN_SQRT_RATIO
    assert get_sqrt_ratio_at_tick(MAX_TICK) == MAX_SQRT_RATIO


def test_tickmath_every_bit_matches_float() -> None:
    # Each power of two exercises one magic constant; a typo in any constant fails here.
    for k in range(20):
        for t in (2**k, -(2**k)):
            exact = get_sqrt_ratio_at_tick(t) / Q96
            assert exact == pytest.approx(1.0001 ** (t / 2), rel=1e-9), t


def test_tick_at_sqrt_ratio_inverts_exactly() -> None:
    for t in (MIN_TICK, -500_000, -196_256, -1, 0, 1, 12_345, 500_000, MAX_TICK - 1):
        s = get_sqrt_ratio_at_tick(t)
        assert get_tick_at_sqrt_ratio(s) == t
        assert get_tick_at_sqrt_ratio(get_sqrt_ratio_at_tick(t + 1) - 1) == t


def test_tick_at_sqrt_ratio_rejects_out_of_range() -> None:
    with pytest.raises(ValueError):
        get_tick_at_sqrt_ratio(MIN_SQRT_RATIO - 1)
    with pytest.raises(ValueError):
        get_tick_at_sqrt_ratio(MAX_SQRT_RATIO)


def test_swap_fee_rounds_up() -> None:
    assert swap_fee_raw(2_000 * 10**6) == 10**6  # 0.05% of 2000 USDC = 1 USDC
    assert swap_fee_raw(1) == 1
    assert swap_fee_raw(0) == 0


def test_fee_protocol_share_uses_low_nibble_for_token0() -> None:
    packed = 4 | (5 << 4)
    assert fee_protocol_share(packed, zero_for_one=True) == 0.25
    assert fee_protocol_share(packed, zero_for_one=False) == 0.2
    assert fee_protocol_share(0, zero_for_one=True) == 0.0
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `uv run pytest tests/test_v3math.py -q`
Expected: FAIL (ImportError for `MAX_SQRT_RATIO`).

- [ ] **Step 3: Implement.** Append to `src/uniswap_lp_economics/v3math.py`, and add `FEE_PIPS` to its config import:

```python
MIN_TICK = -887272
MAX_TICK = 887272
MIN_SQRT_RATIO = 4295128739
MAX_SQRT_RATIO = 1461446703485210103287273052203988822378723970342

# Port of Uniswap v3-core TickMath.getSqrtRatioAtTick: (bit, multiplier) pairs.
_TICK_FACTORS = (
    (0x2, 0xFFF97272373D413259A46990580E213A),
    (0x4, 0xFFF2E50F5F656932EF12357CF3C7FDCC),
    (0x8, 0xFFE5CACA7E10E4E61C3624EAA0941CD0),
    (0x10, 0xFFCB9843D60F6159C9DB58835C926644),
    (0x20, 0xFF973B41FA98C081472E6896DFB254C0),
    (0x40, 0xFF2EA16466C96A3843EC78B326B52861),
    (0x80, 0xFE5DEE046A99A2A811C461F1969C3053),
    (0x100, 0xFCBE86C7900A88AEDCFFC83B479AA3A4),
    (0x200, 0xF987A7253AC413176F2B074CF7815E54),
    (0x400, 0xF3392B0822B70005940C7A398E4B70F3),
    (0x800, 0xE7159475A2C29B7443B29C7FA6E889D9),
    (0x1000, 0xD097F3BDFD2022B8845AD8F792AA5825),
    (0x2000, 0xA9F746462D870FDF8A65DC1F90E061E5),
    (0x4000, 0x70D869A156D2A1B890BB3DF62BAF32F7),
    (0x8000, 0x31BE135F97D08FD981231505542FCFA6),
    (0x10000, 0x9AA508B5B7A84E1C677DE54F3E99BC9),
    (0x20000, 0x5D6AF8DEDB81196699C329225EE604),
    (0x40000, 0x2216E584F5FA1EA926041BEDFE98),
    (0x80000, 0x48A170391F7DC42444E8FA2),
)


def get_sqrt_ratio_at_tick(tick: int) -> int:
    """Exact sqrtPriceX96 at a tick (TickMath.getSqrtRatioAtTick)."""
    abs_tick = abs(tick)
    if abs_tick > MAX_TICK:
        raise ValueError(f"tick {tick} out of range")
    ratio = (
        0xFFFCB933BD6FAD37AA2D162D1A594001 if abs_tick & 0x1 else 0x100000000000000000000000000000000
    )
    for bit, factor in _TICK_FACTORS:
        if abs_tick & bit:
            ratio = (ratio * factor) >> 128
    if tick > 0:
        ratio = (2**256 - 1) // ratio
    return (ratio >> 32) + (0 if ratio % (1 << 32) == 0 else 1)


def get_tick_at_sqrt_ratio(sqrt_price_x96: int) -> int:
    """Greatest tick whose sqrt ratio is <= sqrt_price_x96 (TickMath.getTickAtSqrtRatio)."""
    if not MIN_SQRT_RATIO <= sqrt_price_x96 < MAX_SQRT_RATIO:
        raise ValueError("sqrt price out of range")
    guess = math.floor(2 * math.log(sqrt_price_x96 / Q96) / math.log(1.0001))
    t = max(MIN_TICK, min(MAX_TICK - 1, guess))
    while t < MAX_TICK and get_sqrt_ratio_at_tick(t + 1) <= sqrt_price_x96:
        t += 1
    while get_sqrt_ratio_at_tick(t) > sqrt_price_x96:
        t -= 1
    return t


def swap_fee_raw(amount_in: int, fee_pips: int = FEE_PIPS) -> int:
    """Fee in base units of the input token; amount_in already includes the fee."""
    return -(-amount_in * fee_pips // 1_000_000)


def fee_protocol_share(fee_protocol: int, zero_for_one: bool) -> float:
    """Fraction of the swap fee taken by the protocol (slot0.feeProtocol packing)."""
    denominator = fee_protocol % 16 if zero_for_one else fee_protocol >> 4
    return 1 / denominator if denominator else 0.0
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_v3math.py -q`
Expected: all pass. If `test_tickmath_every_bit_matches_float` fails for one `k`, the multiplier for bit `2**k` is
wrong. Compare it with v3-core `TickMath.sol`, not with this plan.

- [ ] **Step 5: Lint, type-check, commit, push**

```bash
uv run ruff format . && uv run ruff check . && uv run mypy src && uv run pytest -q
git add -A && git commit -m "Add exact TickMath, swap fee and protocol-fee share" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" && git push
```

---

### Task 3: TickBook

**Files:**
- Create: `src/uniswap_lp_economics/tickbook.py`, `tests/test_tickbook.py`

**Interfaces:**
- Consumes: `v3math.get_sqrt_ratio_at_tick`, used in tests only.
- Produces: `TickBook` with:
  - `TickBook(tick: int, sqrt_price_x96: int, liquidity: int, liquidity_net: dict[int, int] = {}, liquidity_gross: dict[int, int] = {})`
  - `TickBook.from_snapshot(ticks: pl.DataFrame, meta: dict[str, int]) -> TickBook`. `ticks` has columns
    `tick`, `liquidity_gross`, `liquidity_net`; `meta` has keys `tick`, `sqrt_price_x96`, `liquidity`.
  - `.apply_mint(tick_lower: int, tick_upper: int, amount: int) -> None`
  - `.apply_burn(tick_lower: int, tick_upper: int, amount: int) -> None`
  - `.apply_swap(sqrt_price_x96: int, tick: int) -> None`
  - `.active_liquidity() -> int`
  - `.initialized_ticks() -> list[int]`

- [ ] **Step 1: Write the failing tests** in `tests/test_tickbook.py`

```python
import polars as pl
import pytest

from uniswap_lp_economics.tickbook import TickBook
from uniswap_lp_economics.v3math import get_sqrt_ratio_at_tick as sqrt_at


def book_at(tick: int) -> TickBook:
    return TickBook(tick=tick, sqrt_price_x96=sqrt_at(tick), liquidity=0)


def test_mint_in_range_adds_active_liquidity_out_of_range_does_not() -> None:
    b = book_at(0)
    b.apply_mint(-100, 100, 1000)
    b.apply_mint(200, 300, 500)
    assert b.active_liquidity() == 1000
    assert b.liquidity_net == {-100: 1000, 100: -1000, 200: 500, 300: -500}
    assert b.initialized_ticks() == [-100, 100, 200, 300]


def test_mint_exactly_at_tick_lower_is_active_at_tick_upper_is_not() -> None:
    b = book_at(-100)
    b.apply_mint(-100, 100, 7)
    b.apply_mint(-300, -100, 5)
    assert b.active_liquidity() == 7


def test_burn_reverses_mint_and_deinitializes_ticks() -> None:
    b = book_at(0)
    b.apply_mint(-100, 100, 1000)
    b.apply_burn(-100, 100, 1000)
    assert b.active_liquidity() == 0
    assert b.initialized_ticks() == []
    assert b.liquidity_net == {} and b.liquidity_gross == {}


def test_burn_more_than_minted_raises() -> None:
    b = book_at(0)
    b.apply_mint(-100, 100, 10)
    with pytest.raises(ValueError):
        b.apply_burn(-100, 100, 11)


def test_zero_amount_burn_is_a_noop() -> None:
    b = book_at(0)
    b.apply_mint(-100, 100, 10)
    b.apply_burn(-100, 100, 0)
    assert b.active_liquidity() == 10 and b.initialized_ticks() == [-100, 100]


def test_swap_crosses_multiple_ticks_up_then_down() -> None:
    b = book_at(0)
    b.apply_mint(-100, 100, 1000)
    b.apply_mint(200, 300, 500)
    b.apply_swap(sqrt_at(250), 250)  # crosses 100 (-1000) and 200 (+500)
    assert b.active_liquidity() == 500
    b.apply_swap(sqrt_at(-150), -150)  # crosses 200, 100, -100 downward
    assert b.active_liquidity() == 0
    assert b.tick == -150


def test_boundary_down_then_up() -> None:
    b = book_at(50)
    b.apply_mint(-100, 100, 1000)
    b.apply_mint(0, 100, 300)
    assert b.active_liquidity() == 1300
    b.apply_swap(sqrt_at(0), -1)  # ends exactly on tick 0 moving down: V3 reports tick -1
    assert b.active_liquidity() == 1000
    b.apply_swap(sqrt_at(0) + 1, 0)  # tiny move up re-crosses tick 0 once
    assert b.active_liquidity() == 1300


def test_from_snapshot() -> None:
    ticks = pl.DataFrame(
        {"tick": [-100, 100], "liquidity_gross": [1000, 1000], "liquidity_net": [1000, -1000]},
        schema={"tick": pl.Int64, "liquidity_gross": pl.Int128, "liquidity_net": pl.Int128},
    )
    b = TickBook.from_snapshot(ticks, {"tick": 0, "sqrt_price_x96": sqrt_at(0), "liquidity": 1000})
    assert b.active_liquidity() == 1000 and b.initialized_ticks() == [-100, 100]
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `uv run pytest tests/test_tickbook.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `src/uniswap_lp_economics/tickbook.py`**

```python
"""Replayable Uniswap V3 liquidity state: per-tick liquidity, current tick, active liquidity."""

from bisect import bisect_right, insort
from dataclasses import dataclass, field

import polars as pl


@dataclass
class TickBook:
    tick: int
    sqrt_price_x96: int
    liquidity: int
    liquidity_net: dict[int, int] = field(default_factory=dict)
    liquidity_gross: dict[int, int] = field(default_factory=dict)
    _sorted: list[int] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self._sorted = sorted(self.liquidity_gross)

    @classmethod
    def from_snapshot(cls, ticks: pl.DataFrame, meta: dict[str, int]) -> "TickBook":
        t = ticks["tick"].to_list()
        return cls(
            tick=int(meta["tick"]),
            sqrt_price_x96=int(meta["sqrt_price_x96"]),
            liquidity=int(meta["liquidity"]),
            liquidity_net=dict(zip(t, ticks["liquidity_net"].to_list(), strict=True)),
            liquidity_gross=dict(zip(t, ticks["liquidity_gross"].to_list(), strict=True)),
        )

    def _update(self, t: int, gross_delta: int, net_delta: int) -> None:
        gross = self.liquidity_gross.get(t, 0) + gross_delta
        if gross < 0:
            raise ValueError(f"liquidity_gross at tick {t} would go negative")
        if gross == 0:
            self.liquidity_gross.pop(t, None)
            self.liquidity_net.pop(t, None)
            if t in self._sorted:
                self._sorted.remove(t)
            return
        if t not in self.liquidity_gross:
            insort(self._sorted, t)
        self.liquidity_gross[t] = gross
        self.liquidity_net[t] = self.liquidity_net.get(t, 0) + net_delta

    def _in_range(self, tick_lower: int, tick_upper: int) -> bool:
        return tick_lower <= self.tick < tick_upper

    def apply_mint(self, tick_lower: int, tick_upper: int, amount: int) -> None:
        if amount == 0:
            return
        self._update(tick_lower, amount, amount)
        self._update(tick_upper, amount, -amount)
        if self._in_range(tick_lower, tick_upper):
            self.liquidity += amount

    def apply_burn(self, tick_lower: int, tick_upper: int, amount: int) -> None:
        if amount == 0:
            return
        self._update(tick_lower, -amount, -amount)
        self._update(tick_upper, -amount, amount)
        if self._in_range(tick_lower, tick_upper):
            self.liquidity -= amount

    def apply_swap(self, sqrt_price_x96: int, tick: int) -> None:
        """Move to the post-swap state, crossing every initialized tick in between.

        Upward, crossing t (old < t <= new) adds liquidity_net[t]; downward, crossing t
        (new < t <= old) subtracts it. This matches V3, where a downward cross sets tick = t - 1.
        """
        lo, hi = sorted((self.tick, tick))
        crossed = self._sorted[bisect_right(self._sorted, lo) : bisect_right(self._sorted, hi)]
        sign = 1 if tick > self.tick else -1
        for t in crossed:
            self.liquidity += sign * self.liquidity_net[t]
        self.tick = tick
        self.sqrt_price_x96 = sqrt_price_x96

    def active_liquidity(self) -> int:
        return self.liquidity

    def initialized_ticks(self) -> list[int]:
        return list(self._sorted)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_tickbook.py -q`
Expected: 8 passed.

- [ ] **Step 5: Lint, type-check, commit, push**

```bash
uv run ruff format . && uv run ruff check . && uv run mypy src && uv run pytest -q
git add -A && git commit -m "Add TickBook replay state" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" && git push
```

---

### Task 4: RPC client, Multicall3 and pool calls

**Files:**
- Create: `src/uniswap_lp_economics/rpc.py`, `tests/test_rpc.py`
- Modify: `pyproject.toml` (register the `live` marker; skip it by default)

**Interfaces:**
- Consumes: `abi.*` (Task 1).
- Produces:
  - `RpcError(RuntimeError)`
  - `RpcClient(url: str, transport: httpx.BaseTransport | None = None, max_retries: int = 5, backoff_s: float = 1.0)`
    with methods:
    - `.request(method: str, params: list[Any]) -> Any`
    - `.block_number() -> int`
    - `.block_timestamp(block: int) -> int`
    - `.eth_call(to: str, data: str, block: int) -> str`
    - `.multicall(calls: list[tuple[str, str]], block: int) -> list[str | None]`
  - `MULTICALL3 = "0xca11bde05977b3631167028862be2a173976ca11"`
  - `encode_aggregate3(calls: list[tuple[str, str]]) -> str`
  - `decode_aggregate3(result: str) -> list[str | None]`
  - Pool calls: `SLOT0_CALL: str`, `LIQUIDITY_CALL: str`, `tick_bitmap_call(word_pos: int) -> str`,
    `ticks_call(tick: int) -> str`
  - Pool decoders:
    - `decode_slot0(result: str) -> dict[str, int]` (keys `sqrt_price_x96`, `tick`, `fee_protocol`)
    - `decode_uint(result: str) -> int`
    - `decode_ticks(result: str) -> tuple[int, int, bool]` (gross, net, initialized)

- [ ] **Step 1: Register the live marker.** Append to the existing `[tool.pytest.ini_options]` in `pyproject.toml`:

```toml
markers = ["live: needs network access and credentials (run with -m live)"]
addopts = "-m 'not live'"
```

- [ ] **Step 2: Write the failing tests** in `tests/test_rpc.py`

```python
import json
from collections.abc import Callable

import httpx
import pytest

from uniswap_lp_economics import abi
from uniswap_lp_economics.rpc import (
    RpcClient, RpcError, decode_aggregate3, decode_slot0, decode_ticks, encode_aggregate3,
)

URL = "https://example.invalid/v2/SECRETKEY"


def client_with(responses: list[Callable[[], httpx.Response]]) -> tuple[RpcClient, list[int]]:
    """Each call gets a fresh Response from the factory (the last factory repeats)."""
    calls = [0]

    def handler(request: httpx.Request) -> httpx.Response:
        calls[0] += 1
        return responses[min(calls[0] - 1, len(responses) - 1)]()

    return RpcClient(URL, transport=httpx.MockTransport(handler), backoff_s=0), calls


def ok(result: object) -> Callable[[], httpx.Response]:
    return lambda: httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})


def err(code: int, message: str) -> Callable[[], httpx.Response]:
    body = {"jsonrpc": "2.0", "id": 1, "error": {"code": code, "message": message}}
    return lambda: httpx.Response(200, json=body)


def test_encode_aggregate3_single_call_hand_vector() -> None:
    target = "0x" + "11" * 20
    encoded = encode_aggregate3([(target, "0x3850c7bd")])
    expected = (
        abi.selector("aggregate3((address,bool,bytes)[])")
        + abi.enc_uint(0x20) + abi.enc_uint(1) + abi.enc_uint(0x20)
        + abi.enc_addr(target) + abi.enc_uint(1) + abi.enc_uint(0x60) + abi.enc_uint(4)
        + "3850c7bd" + "00" * 28
    )
    assert encoded == expected


def test_decode_aggregate3_success_and_failure() -> None:
    result = "0x" + "".join([
        abi.enc_uint(0x20), abi.enc_uint(2), abi.enc_uint(0x40), abi.enc_uint(0xC0),
        abi.enc_uint(1), abi.enc_uint(0x40), abi.enc_uint(32), "01" * 32,
        abi.enc_uint(0), abi.enc_uint(0x40), abi.enc_uint(0),
    ])
    assert decode_aggregate3(result) == ["0x" + "01" * 32, None]


def test_decode_slot0_and_ticks() -> None:
    slot0 = "0x" + "".join(
        [abi.enc_uint(2**96 * 40), abi.enc_int(-196_256)]
        + [abi.enc_uint(0)] * 3 + [abi.enc_uint(4 | 5 << 4), abi.enc_uint(1)]
    )
    assert decode_slot0(slot0) == {"sqrt_price_x96": 2**96 * 40, "tick": -196_256, "fee_protocol": 0x54}
    ticks = "0x" + "".join([abi.enc_uint(10), abi.enc_int(-7)] + [abi.enc_uint(0)] * 5 + [abi.enc_uint(1)])
    assert decode_ticks(ticks) == (10, -7, True)


def test_retries_http_429_then_succeeds() -> None:
    c, calls = client_with([lambda: httpx.Response(429), ok("0x10")])
    assert c.block_number() == 16
    assert calls[0] == 2


def test_retries_json_rate_limit() -> None:
    c, calls = client_with([err(429, "slow down"), ok("0x10")])
    assert c.block_number() == 16
    assert calls[0] == 2


def test_non_retryable_error_raises_immediately() -> None:
    c, calls = client_with([err(-32000, "execution reverted")])
    with pytest.raises(RpcError, match="execution reverted"):
        c.block_number()
    assert calls[0] == 1


def test_errors_never_contain_url() -> None:
    c, _ = client_with([lambda: httpx.Response(500, text=URL)])
    with pytest.raises(RpcError) as exc:
        c.block_number()
    assert "SECRETKEY" not in str(exc.value)

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {URL}")

    c2 = RpcClient(URL, transport=httpx.MockTransport(boom), backoff_s=0, max_retries=2)
    with pytest.raises(RpcError) as exc2:
        c2.block_number()
    assert "SECRETKEY" not in str(exc2.value)


def test_request_payload_shape() -> None:
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return ok("0x0")

    RpcClient(URL, transport=httpx.MockTransport(handler)).eth_call("0x" + "22" * 20, "0x3850c7bd", 255)
    assert seen[0]["method"] == "eth_call"
    assert seen[0]["params"] == [{"to": "0x" + "22" * 20, "data": "0x3850c7bd"}, "0xff"]


@pytest.mark.live
def test_live_multicall_slot0() -> None:
    from uniswap_lp_economics.config import ETH_RPC_URL, POOL_ADDRESS
    from uniswap_lp_economics.rpc import LIQUIDITY_CALL, SLOT0_CALL, decode_uint

    assert ETH_RPC_URL
    c = RpcClient(ETH_RPC_URL)
    block = c.block_number()
    slot0, liq = c.multicall([(POOL_ADDRESS, SLOT0_CALL), (POOL_ADDRESS, LIQUIDITY_CALL)], block)
    assert slot0 is not None and liq is not None
    assert decode_slot0(slot0)["sqrt_price_x96"] > 0 and decode_uint(liq) > 0
```

- [ ] **Step 3: Run them and confirm they fail**

Run: `uv run pytest tests/test_rpc.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 4: Implement `src/uniswap_lp_economics/rpc.py`**

```python
"""Small JSON-RPC client with retries, Multicall3 batching, and Uniswap V3 pool call codecs.

Never include the RPC URL in messages: it contains the API key.
"""

import time
from typing import Any

import httpx

from uniswap_lp_economics import abi

MULTICALL3 = "0xca11bde05977b3631167028862be2a173976ca11"
_AGGREGATE3 = abi.selector("aggregate3((address,bool,bytes)[])")
_RETRYABLE_JSON_CODES = {429, -32005}

SLOT0_CALL = abi.selector("slot0()")
LIQUIDITY_CALL = abi.selector("liquidity()")
_TICK_BITMAP = abi.selector("tickBitmap(int16)")
_TICKS = abi.selector("ticks(int24)")


class RpcError(RuntimeError):
    pass


class RpcClient:
    def __init__(
        self,
        url: str,
        transport: httpx.BaseTransport | None = None,
        max_retries: int = 5,
        backoff_s: float = 1.0,
    ) -> None:
        self._url = url
        self._client = httpx.Client(transport=transport, timeout=60)
        self.max_retries = max_retries
        self.backoff_s = backoff_s

    def request(self, method: str, params: list[Any]) -> Any:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        last = "no attempt made"
        for attempt in range(self.max_retries):
            try:
                r = self._client.post(self._url, json=payload)
            except httpx.TransportError as e:
                last = f"transport error ({type(e).__name__})"
            else:
                if r.status_code == 429 or r.status_code >= 500:
                    last = f"HTTP {r.status_code}"
                elif r.status_code != 200:
                    raise RpcError(f"{method}: HTTP {r.status_code}")
                else:
                    body = r.json()
                    error = body.get("error")
                    if error is None:
                        return body["result"]
                    if error.get("code") not in _RETRYABLE_JSON_CODES:
                        raise RpcError(f"{method}: {error.get('message', error)}")
                    last = f"rate limited ({error.get('code')})"
            time.sleep(self.backoff_s * 2**attempt)
        raise RpcError(f"{method} failed after {self.max_retries} attempts: {last}")

    def block_number(self) -> int:
        return int(self.request("eth_blockNumber", []), 16)

    def block_timestamp(self, block: int) -> int:
        return int(self.request("eth_getBlockByNumber", [hex(block), False])["timestamp"], 16)

    def eth_call(self, to: str, data: str, block: int) -> str:
        result: str = self.request("eth_call", [{"to": to, "data": data}, hex(block)])
        return result

    def multicall(self, calls: list[tuple[str, str]], block: int) -> list[str | None]:
        return decode_aggregate3(self.eth_call(MULTICALL3, encode_aggregate3(calls), block))


def encode_aggregate3(calls: list[tuple[str, str]]) -> str:
    """ABI-encode aggregate3(Call3[]) with allowFailure = true for every call."""
    tuples = []
    for target, data in calls:
        payload = bytes.fromhex(data[2:])
        padded = payload.hex() + "00" * ((-len(payload)) % 32)
        tuples.append(
            abi.enc_addr(target) + abi.enc_uint(1) + abi.enc_uint(0x60) + abi.enc_uint(len(payload)) + padded
        )
    offsets, pos = [], 32 * len(calls)
    for t in tuples:
        offsets.append(abi.enc_uint(pos))
        pos += len(t) // 2
    return _AGGREGATE3 + abi.enc_uint(0x20) + abi.enc_uint(len(calls)) + "".join(offsets) + "".join(tuples)


def decode_aggregate3(result: str) -> list[str | None]:
    """Decode Result[] = (bool success, bytes returnData)[]; failed calls become None."""
    raw = bytes.fromhex(result[2:])

    def word(offset: int) -> int:
        return int.from_bytes(raw[offset : offset + 32], "big")

    array = word(0)
    base = array + 32
    out: list[str | None] = []
    for i in range(word(array)):
        start = base + word(base + 32 * i)
        data_at = start + word(start + 32)
        data = raw[data_at + 32 : data_at + 32 + word(data_at)]
        out.append("0x" + data.hex() if word(start) == 1 else None)
    return out


def tick_bitmap_call(word_pos: int) -> str:
    return _TICK_BITMAP + abi.enc_int(word_pos)


def ticks_call(tick: int) -> str:
    return _TICKS + abi.enc_int(tick)


def decode_uint(result: str) -> int:
    return abi.to_uint(abi.words(result)[0])


def decode_slot0(result: str) -> dict[str, int]:
    w = abi.words(result)
    return {"sqrt_price_x96": abi.to_uint(w[0]), "tick": abi.to_int(w[1]), "fee_protocol": abi.to_uint(w[5])}


def decode_ticks(result: str) -> tuple[int, int, bool]:
    w = abi.words(result)
    return abi.to_uint(w[0]), abi.to_int(w[1]), abi.to_uint(w[7]) == 1
```

- [ ] **Step 5: Add the BigQuery live smoke test** to the end of `tests/test_bigquery.py`. It's a dry run, so it
  scans nothing. Add `import pytest` at the top of that file.

```python
@pytest.mark.live
def test_live_bigquery_dry_run() -> None:
    from uniswap_lp_economics.data.bigquery import fetch_pool_logs

    assert fetch_pool_logs(date(2026, 9, 1), date(2026, 9, 2), dry_run=True) is None
```

- [ ] **Step 6: Run the offline tests, then the live tests**

Run: `uv run pytest tests/test_rpc.py -q`
Expected: 8 passed, 1 deselected.
Run: `uv run pytest -m live -q`
Expected: 2 passed. These use `.env` `ETH_RPC_URL` and the gcloud credentials, and prove that Multicall3 encoding
works against mainnet.

- [ ] **Step 7: Lint, type-check, commit, push**

```bash
uv run ruff format . && uv run ruff check . && uv run mypy src && uv run pytest -q
git add -A && git commit -m "Add RPC client with retries, Multicall3 and pool call codecs" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" && git push
```

---

### Task 5: Snapshot and validation-sample reads

**Files:**
- Create: `src/uniswap_lp_economics/snapshot.py`, `tests/test_snapshot.py`
- Modify: `src/uniswap_lp_economics/config.py`, `src/uniswap_lp_economics/cli.py`

**Interfaces:**
- Consumes:
  - `RpcClient`, `SLOT0_CALL`, `LIQUIDITY_CALL`, `tick_bitmap_call`, `ticks_call`, `decode_slot0`, `decode_uint`,
    `decode_ticks` (Task 4)
  - `MIN_TICK`, `MAX_TICK` (Task 2)
- Produces:
  - In `config`:
    - `WINDOW_START = date(2026, 7, 1)`, `WINDOW_END = date(2026, 10, 1)`
    - `RAW_DIR = DATA_DIR / "raw"`, `INTERIM_DIR = DATA_DIR / "interim"`
    - `VALIDATION_DIR = ROOT / "data_validation"`. This is committed. See Step 1 for why it isn't
      `data/validation`.
  - In `snapshot`:
    - `bitmap_word_range(tick_lo: int = MIN_TICK, tick_hi: int = MAX_TICK, spacing: int = TICK_SPACING) -> range`
    - `ticks_in_word(word_pos: int, bitmap: int, spacing: int = TICK_SPACING) -> list[int]`
    - `read_state(client, block) -> dict[str, int]` (keys `block`, `sqrt_price_x96`, `tick`, `fee_protocol`,
      `liquidity`)
    - `read_initialized_ticks(client, block, word_range: range) -> list[int]`
    - `read_ticks(client, block, ticks: list[int]) -> pl.DataFrame` (columns `tick` Int64, `liquidity_gross` Int128,
      `liquidity_net` Int128)
    - `read_tick_book(client, block) -> tuple[pl.DataFrame, dict[str, int]]`
    - `find_last_block_before(client, ts: int, lo: int, hi: int) -> int`
    - `read_sample(client, block, n_ticks: int = 20, word_radius: int = 2) -> tuple[dict[str, int], pl.DataFrame]`
    - `pick_sample_blocks(first: int, last: int, n: int = 500, n_full: int = 5, seed: int = 42) -> tuple[list[int], list[int]]`
  - CLI: `ulpe fetch-snapshot`, `ulpe fetch-samples`.
  - Files:
    - `data/raw/tickbook_snapshot.parquet`
    - `data/raw/snapshot_meta.json` (keys `block`, `timestamp`, `sqrt_price_x96`, `tick`, `fee_protocol`, `liquidity`)
    - `data/raw/onchain_samples.parquet` (columns `block`, `sqrt_price_x96`, `tick`, `fee_protocol`, `liquidity`,
      `full_book`)
    - `data/raw/onchain_sample_ticks.parquet` (columns `block`, `tick`, `liquidity_gross`, `liquidity_net`)

- [ ] **Step 1: Extend `config.py`.** Add `from datetime import date` and the constants below.

`/data/` is git-ignored as a whole. The committed report therefore lives in `data_validation/` at the repo root.
That is a small, explicit deviation from the spec's `data/validation/` path, and it avoids fragile un-ignore rules.

```python
WINDOW_START = date(2026, 7, 1)
WINDOW_END = date(2026, 10, 1)  # exclusive

RAW_DIR = DATA_DIR / "raw"
INTERIM_DIR = DATA_DIR / "interim"
VALIDATION_DIR = ROOT / "data_validation"
```

- [ ] **Step 2: Write the failing tests** in `tests/test_snapshot.py`. Fake RPC behaviour is supplied through a
  stub client object, so no network is needed.

```python
from typing import Any

from uniswap_lp_economics import rpc
from uniswap_lp_economics.snapshot import (
    bitmap_word_range, find_last_block_before, pick_sample_blocks, read_initialized_ticks, ticks_in_word,
)


def test_bitmap_word_range_covers_all_ticks() -> None:
    r = bitmap_word_range()
    assert (r.start, r.stop) == (-347, 347)  # floor(-887272/10) >> 8 = -347; 88727 >> 8 = 346


def test_ticks_in_word_handles_negative_words() -> None:
    assert ticks_in_word(0, 0b101) == [0, 20]
    assert ticks_in_word(-1, 1 << 255) == [-10]  # (-1*256 + 255) * 10


class StubClient:
    def __init__(self, timestamps: dict[int, int] | None = None, bitmaps: dict[int, int] | None = None) -> None:
        self.timestamps = timestamps or {}
        self.bitmaps = bitmaps or {}

    def block_timestamp(self, block: int) -> int:
        return self.timestamps[block]

    def multicall(self, calls: list[tuple[str, str]], block: int) -> list[str | None]:
        out: list[str | None] = []
        for _, data in calls:
            word_pos = rpc.abi.to_int(data[10:])
            out.append("0x" + rpc.abi.enc_uint(self.bitmaps.get(word_pos, 0)))
        return out


def test_find_last_block_before() -> None:
    stub = StubClient(timestamps={b: 1000 + 12 * (b - 100) for b in range(100, 200)})
    # ts 1000 + 12*(b-100) < 1600  <=>  b < 150
    assert find_last_block_before(stub, 1600, 100, 199) == 149  # type: ignore[arg-type]


def test_read_initialized_ticks_uses_bitmap() -> None:
    stub = StubClient(bitmaps={0: 0b11, -1: 1 << 255})
    ticks = read_initialized_ticks(stub, 1, range(-1, 1))  # type: ignore[arg-type]
    assert ticks == [-10, 0, 10]


def test_pick_sample_blocks_is_deterministic_and_sorted() -> None:
    a = pick_sample_blocks(1, 10_000, n=50, n_full=5)
    b = pick_sample_blocks(1, 10_000, n=50, n_full=5)
    assert a == b
    blocks, full = a
    assert blocks == sorted(blocks) and len(blocks) == 50 and len(set(blocks)) == 50
    assert len(full) == 5 and set(full) <= set(blocks)
    assert full[0] == blocks[0] and full[-1] == blocks[-1]
```

- [ ] **Step 3: Run them and confirm they fail**

Run: `uv run pytest tests/test_snapshot.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 4: Implement `src/uniswap_lp_economics/snapshot.py`**

```python
"""Read pool tick-book state from chain via Multicall3 (snapshot and validation samples)."""

import random

import polars as pl

from uniswap_lp_economics.config import POOL_ADDRESS, TICK_SPACING
from uniswap_lp_economics.rpc import (
    LIQUIDITY_CALL, SLOT0_CALL, RpcClient, decode_slot0, decode_ticks, decode_uint,
    tick_bitmap_call, ticks_call,
)
from uniswap_lp_economics.v3math import MAX_TICK, MIN_TICK

BATCH = 400
TICK_SCHEMA = {"tick": pl.Int64, "liquidity_gross": pl.Int128, "liquidity_net": pl.Int128}


def bitmap_word_range(tick_lo: int = MIN_TICK, tick_hi: int = MAX_TICK, spacing: int = TICK_SPACING) -> range:
    return range((tick_lo // spacing) >> 8, ((tick_hi // spacing) >> 8) + 1)


def ticks_in_word(word_pos: int, bitmap: int, spacing: int = TICK_SPACING) -> list[int]:
    return [(word_pos * 256 + bit) * spacing for bit in range(256) if bitmap >> bit & 1]


def _batched(client: RpcClient, calls: list[tuple[str, str]], block: int) -> list[str]:
    out: list[str] = []
    for i in range(0, len(calls), BATCH):
        for result in client.multicall(calls[i : i + BATCH], block):
            if result is None:
                raise RuntimeError(f"multicall sub-call failed at block {block}")
            out.append(result)
    return out


def read_state(client: RpcClient, block: int) -> dict[str, int]:
    slot0, liquidity = _batched(client, [(POOL_ADDRESS, SLOT0_CALL), (POOL_ADDRESS, LIQUIDITY_CALL)], block)
    return {"block": block, **decode_slot0(slot0), "liquidity": decode_uint(liquidity)}


def read_initialized_ticks(client: RpcClient, block: int, word_range: range) -> list[int]:
    words = list(word_range)
    results = _batched(client, [(POOL_ADDRESS, tick_bitmap_call(w)) for w in words], block)
    ticks: list[int] = []
    for w, result in zip(words, results, strict=True):
        ticks.extend(ticks_in_word(w, decode_uint(result)))
    return sorted(ticks)


def read_ticks(client: RpcClient, block: int, ticks: list[int]) -> pl.DataFrame:
    results = _batched(client, [(POOL_ADDRESS, ticks_call(t)) for t in ticks], block)
    rows = []
    for t, result in zip(ticks, results, strict=True):
        gross, net, initialized = decode_ticks(result)
        if not initialized:
            raise RuntimeError(f"tick {t} in bitmap but not initialized at block {block}")
        rows.append({"tick": t, "liquidity_gross": gross, "liquidity_net": net})
    return pl.DataFrame(rows, schema=TICK_SCHEMA)


def read_tick_book(client: RpcClient, block: int) -> tuple[pl.DataFrame, dict[str, int]]:
    meta = read_state(client, block)
    return read_ticks(client, block, read_initialized_ticks(client, block, bitmap_word_range())), meta


def find_last_block_before(client: RpcClient, ts: int, lo: int, hi: int) -> int:
    """Largest block with timestamp < ts. Requires ts(lo) < ts <= ts(hi)."""
    if not client.block_timestamp(lo) < ts <= client.block_timestamp(hi):
        raise ValueError("search bounds do not bracket the timestamp")
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if client.block_timestamp(mid) < ts:
            lo = mid
        else:
            hi = mid
    return lo


def read_sample(
    client: RpcClient, block: int, n_ticks: int = 20, word_radius: int = 2
) -> tuple[dict[str, int], pl.DataFrame]:
    state = read_state(client, block)
    center = (state["tick"] // TICK_SPACING) >> 8
    initialized = read_initialized_ticks(client, block, range(center - word_radius, center + word_radius + 1))
    nearest = sorted(sorted(initialized, key=lambda t: abs(t - state["tick"]))[:n_ticks])
    return state, read_ticks(client, block, nearest)


def pick_sample_blocks(
    first: int, last: int, n: int = 500, n_full: int = 5, seed: int = 42
) -> tuple[list[int], list[int]]:
    """n distinct blocks in [first, last] (sorted), and n_full of them spread evenly for full-book checks."""
    blocks = sorted(random.Random(seed).sample(range(first, last + 1), n))
    idx = [round(i * (n - 1) / (n_full - 1)) for i in range(n_full)]
    return blocks, [blocks[i] for i in idx]
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_snapshot.py -q`
Expected: 5 passed.

- [ ] **Step 6: Add the CLI commands.** In `cli.py`, add these imports:

```python
import json
from datetime import UTC, datetime

import polars as pl

from uniswap_lp_economics import config, snapshot
from uniswap_lp_economics.rpc import RpcClient
```

Then add these functions above `main()`:

```python
def _rpc() -> RpcClient:
    if not config.ETH_RPC_URL:
        raise SystemExit("ETH_RPC_URL is not set in .env")
    return RpcClient(config.ETH_RPC_URL)


def _raw_logs() -> pl.DataFrame:
    files = sorted(config.RAW_DIR.glob("pool_logs_*.parquet"))
    if not files:
        raise SystemExit(f"no pool logs in {config.RAW_DIR}; run `ulpe fetch-logs` first")
    return pl.read_parquet(files)


def fetch_snapshot() -> None:
    meta_path = config.RAW_DIR / "snapshot_meta.json"
    if meta_path.exists():
        print("snapshot already downloaded, skipping")
        return
    client = _rpc()
    first_log_block = int(_raw_logs()["block_number"].min())  # type: ignore[arg-type]
    start_ts = int(datetime.combine(config.WINDOW_START, datetime.min.time(), UTC).timestamp())
    block = snapshot.find_last_block_before(client, start_ts, first_log_block - 2_000, first_log_block)
    ticks, meta = snapshot.read_tick_book(client, block)
    ticks.write_parquet(config.RAW_DIR / "tickbook_snapshot.parquet")
    meta["timestamp"] = client.block_timestamp(block)
    meta_path.write_text(json.dumps(meta, indent=2))
    print(f"snapshot at block {block}: {ticks.height} initialized ticks")


def fetch_samples() -> None:
    out = config.RAW_DIR / "onchain_samples.parquet"
    if out.exists():
        print("samples already downloaded, skipping")
        return
    client = _rpc()
    meta = json.loads((config.RAW_DIR / "snapshot_meta.json").read_text())
    last_block = int(_raw_logs()["block_number"].max())  # type: ignore[arg-type]
    blocks, full = snapshot.pick_sample_blocks(meta["block"] + 1, last_block)
    states, tick_frames = [], []
    for i, block in enumerate(blocks):
        if block in full:
            ticks, state = snapshot.read_tick_book(client, block)
        else:
            state, ticks = snapshot.read_sample(client, block)
        states.append({**state, "full_book": block in full})
        tick_frames.append(ticks.with_columns(block=pl.lit(block, dtype=pl.Int64)))
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(blocks)} samples")
    pl.DataFrame(
        states,
        schema={"block": pl.Int64, "sqrt_price_x96": pl.Int128, "tick": pl.Int64,
                "fee_protocol": pl.Int64, "liquidity": pl.Int128, "full_book": pl.Boolean},
    ).write_parquet(out)
    pl.concat(tick_frames).write_parquet(config.RAW_DIR / "onchain_sample_ticks.parquet")
    print(f"wrote {len(blocks)} samples ({len(full)} full-book)")
```

In `main()`, register the two subcommands and dispatch them:

```python
    sub.add_parser("fetch-snapshot", help="read the full tick book just before the window (RPC)")
    sub.add_parser("fetch-samples", help="read on-chain state at 500 random blocks (RPC)")
```

```python
    elif args.command == "fetch-snapshot":
        fetch_snapshot()
    elif args.command == "fetch-samples":
        fetch_samples()
```

- [ ] **Step 7: Run the snapshot for real**

Run: `uv run ulpe fetch-snapshot`
Expected: `snapshot at block <N>: <k> initialized ticks`. `<N>` should be just below 25,433,939 and `<k>` in the
thousands.

Then check snapshot self-consistency (spec check C4) manually:
```bash
uv run python -c "import json,polars as pl; t=pl.read_parquet('data/raw/tickbook_snapshot.parquet'); m=json.loads(open('data/raw/snapshot_meta.json').read()); n=dict(zip(t['tick'].to_list(),t['liquidity_net'].to_list())); print('sum net',sum(n.values())); print('rebuilt==liquidity', sum(v for k,v in n.items() if k<=m['tick'])==m['liquidity']); print('fee_protocol', m['fee_protocol'])"
```
Expected: `sum net 0` and `rebuilt==liquidity True`. Record the printed `fee_protocol` for the report.

- [ ] **Step 8: Run the samples for real.** This needs the snapshot first.

Run: `uv run ulpe fetch-samples`
Expected: progress lines, then `wrote 500 samples (5 full-book)`. It takes several minutes.

- [ ] **Step 9: Lint, type-check, commit, push**

```bash
uv run ruff format . && uv run ruff check . && uv run mypy src && uv run pytest -q
git add -A && git commit -m "Add tick-book snapshot and on-chain sample reads" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" && git push
```

---

### Task 6: Binance downloads and parsing

**Files:**
- Create: `src/uniswap_lp_economics/data/binance.py`, `tests/test_binance.py`
- Modify: `src/uniswap_lp_economics/cli.py`

**Interfaces:**
- Produces:
  - `ChecksumError(RuntimeError)`
  - `agg_trades_url(symbol: str, year: int, month: int) -> str`
  - `klines_url(symbol: str, interval: str, year: int, month: int) -> str`
  - `download_verified(url: str, dest: Path, client: httpx.Client) -> Path`
  - `parse_agg_trades(zip_path: Path) -> pl.DataFrame` (columns `ts_us` Int64, `price` Float64, `qty` Float64,
    `is_buyer_maker` Boolean)
  - `parse_klines_close(zip_path: Path) -> pl.DataFrame` (columns `ts_us` Int64, `close` Float64)
  - `fetch_cex(months: list[tuple[int, int]], raw_dir: Path) -> list[Path]`
  - CLI `ulpe fetch-cex`

- [ ] **Step 1: Write the failing tests** in `tests/test_binance.py`

```python
import hashlib
import io
import zipfile
from pathlib import Path

import httpx
import pytest

from uniswap_lp_economics.data.binance import (
    ChecksumError, agg_trades_url, download_verified, parse_agg_trades, parse_klines_close,
)


def make_zip(path: Path, name: str, text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(name, text)
    path.write_bytes(buf.getvalue())
    return buf.getvalue()


def test_url_layout() -> None:
    assert agg_trades_url("ETHUSDC", 2026, 7) == (
        "https://data.binance.vision/data/spot/monthly/aggTrades/ETHUSDC/ETHUSDC-aggTrades-2026-07.zip"
    )


def test_parse_agg_trades_ms_and_us_agree(tmp_path: Path) -> None:
    ms = make_zip(tmp_path / "ms.zip", "a.csv", "1,2500.5,0.1,1,1,1751328000123,True,True\n")
    us = make_zip(tmp_path / "us.zip", "b.csv", "1,2500.5,0.1,1,1,1751328000123000,False,True\n")
    assert ms and us
    a = parse_agg_trades(tmp_path / "ms.zip")
    b = parse_agg_trades(tmp_path / "us.zip")
    assert a["ts_us"].to_list() == b["ts_us"].to_list() == [1751328000123000]
    assert a["is_buyer_maker"].to_list() == [True] and b["is_buyer_maker"].to_list() == [False]
    assert a["price"].to_list() == [2500.5]


def test_parse_agg_trades_with_header(tmp_path: Path) -> None:
    header = "agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker,is_best_match\n"
    make_zip(tmp_path / "h.zip", "h.csv", header + "1,2500.5,0.1,1,1,1751328000123,true,true\n")
    assert parse_agg_trades(tmp_path / "h.zip").height == 1


def test_parse_klines_close(tmp_path: Path) -> None:
    make_zip(tmp_path / "k.zip", "k.csv", "1751328000000,1,2,0.5,1.5,10,1751328000999,15,3,5,7,0\n")
    df = parse_klines_close(tmp_path / "k.zip")
    assert df.rows() == [(1751328000000000, 1.5)]


def test_download_verified_ok_and_skip(tmp_path: Path) -> None:
    payload = b"zip-bytes"
    digest = hashlib.sha256(payload).hexdigest()
    hits = []

    def handler(request: httpx.Request) -> httpx.Response:
        hits.append(str(request.url))
        if str(request.url).endswith(".CHECKSUM"):
            return httpx.Response(200, text=f"{digest}  f.zip\n")
        return httpx.Response(200, content=payload)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    dest = tmp_path / "f.zip"
    download_verified("https://x.invalid/f.zip", dest, client)
    assert dest.read_bytes() == payload
    assert (tmp_path / "f.zip.CHECKSUM").read_text().startswith(digest)  # kept for C5
    n = len(hits)
    download_verified("https://x.invalid/f.zip", dest, client)  # valid file present: no re-download
    assert len(hits) == n + 1  # only the checksum is fetched again


def test_download_verified_bad_checksum_leaves_nothing(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith(".CHECKSUM"):
            return httpx.Response(200, text="0" * 64 + "  f.zip\n")
        return httpx.Response(200, content=b"tampered")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(ChecksumError):
        download_verified("https://x.invalid/f.zip", tmp_path / "f.zip", client)
    assert list(tmp_path.iterdir()) == []
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `uv run pytest tests/test_binance.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `src/uniswap_lp_economics/data/binance.py`**

```python
"""Binance public data (data.binance.vision): checksum-verified downloads and parsing."""

import hashlib
import zipfile
from pathlib import Path

import httpx
import polars as pl

BASE = "https://data.binance.vision/data/spot/monthly"
AGG_COLS = ["agg_trade_id", "price", "qty", "first_id", "last_id", "ts", "is_buyer_maker", "best_match"]
KLINE_COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time",
              "quote_volume", "count", "taker_base", "taker_quote", "ignore"]


class ChecksumError(RuntimeError):
    pass


def agg_trades_url(symbol: str, year: int, month: int) -> str:
    return f"{BASE}/aggTrades/{symbol}/{symbol}-aggTrades-{year}-{month:02d}.zip"


def klines_url(symbol: str, interval: str, year: int, month: int) -> str:
    return f"{BASE}/klines/{symbol}/{interval}/{symbol}-{interval}-{year}-{month:02d}.zip"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download_verified(url: str, dest: Path, client: httpx.Client) -> Path:
    """Download url to dest unless a file matching Binance's published SHA256 is already there.

    The .CHECKSUM text is saved next to the zip so validation (C5) can re-verify offline.
    """
    checksum_text = client.get(url + ".CHECKSUM").raise_for_status().text
    expected = checksum_text.split()[0]
    checksum_path = dest.with_name(dest.name + ".CHECKSUM")
    if dest.exists() and _sha256(dest) == expected:
        checksum_path.write_text(checksum_text)
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    with client.stream("GET", url) as r, tmp.open("wb") as f:
        r.raise_for_status()
        for chunk in r.iter_bytes():
            f.write(chunk)
    if _sha256(tmp) != expected:
        tmp.unlink()
        raise ChecksumError(f"checksum mismatch for {dest.name}")
    tmp.replace(dest)
    checksum_path.write_text(checksum_text)
    return dest


def _read_zip_csv(zip_path: Path, columns: list[str]) -> pl.DataFrame:
    with zipfile.ZipFile(zip_path) as z:
        raw = z.read(z.namelist()[0])
    has_header = not raw[:1].isdigit()
    return pl.read_csv(raw, has_header=has_header, new_columns=columns, infer_schema=False)


def _to_us(col: str) -> pl.Expr:
    ts = pl.col(col).cast(pl.Int64)
    return pl.when(ts > 10**14).then(ts).otherwise(ts * 1000)  # Binance moved spot data from ms to us


def parse_agg_trades(zip_path: Path) -> pl.DataFrame:
    return _read_zip_csv(zip_path, AGG_COLS).select(
        ts_us=_to_us("ts"),
        price=pl.col("price").cast(pl.Float64),
        qty=pl.col("qty").cast(pl.Float64),
        is_buyer_maker=pl.col("is_buyer_maker").str.to_lowercase() == "true",
    )


def parse_klines_close(zip_path: Path) -> pl.DataFrame:
    return _read_zip_csv(zip_path, KLINE_COLS).select(
        ts_us=_to_us("open_time"), close=pl.col("close").cast(pl.Float64)
    )


def fetch_cex(months: list[tuple[int, int]], raw_dir: Path) -> list[Path]:
    out = []
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        for year, month in months:
            for url in (agg_trades_url("ETHUSDC", year, month), klines_url("ETHUSDT", "1s", year, month)):
                dest = raw_dir / "binance" / url.rsplit("/", 1)[1]
                out.append(download_verified(url, dest, client))
                print(f"  ok {dest.name}")
    return out
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_binance.py -q`
Expected: 6 passed.

- [ ] **Step 5: Add the CLI command.** In `cli.py`, add `from uniswap_lp_economics.data import binance`, then:

```python
def fetch_cex() -> None:
    months = [(d.year, d.month) for d, _ in bigquery.month_windows(config.WINDOW_START, config.WINDOW_END)]
    binance.fetch_cex(months, config.RAW_DIR)
```

Register `sub.add_parser("fetch-cex", help="download Binance ETHUSDC trades and ETHUSDT 1s klines")` and dispatch
`elif args.command == "fetch-cex": fetch_cex()`.

- [ ] **Step 6: Run it for real**

Run: `uv run ulpe fetch-cex`
Expected: six `ok` lines (3 months × 2 files), about 400 MB in total. Running it again prints the same lines without
downloading again.

- [ ] **Step 7: Lint, type-check, commit, push**

```bash
uv run ruff format . && uv run ruff check . && uv run mypy src && uv run pytest -q
git add -A && git commit -m "Add checksum-verified Binance downloads and parsing" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" && git push
```

---

### Task 7: Build interim tables

**Files:**
- Create: `src/uniswap_lp_economics/build.py`, `tests/test_build.py`
- Modify: `src/uniswap_lp_economics/cli.py`

**Interfaces:**
- Consumes:
  - `decode_event` (Task 1)
  - `swap_fee_raw`, `fee_protocol_share`, `Q96` (Task 2)
  - `parse_agg_trades`, `parse_klines_close` (Task 6)
  - `config.RAW_DIR`, `config.INTERIM_DIR`
- Produces:
  - `EVENT_SCHEMA: dict[str, pl.DataType]`
  - `load_raw_logs(raw_dir: Path) -> pl.DataFrame`. Raises `FileNotFoundError` naming `ulpe fetch-logs`.
  - `load_snapshot_meta(raw_dir: Path) -> dict[str, int]`. Raises `FileNotFoundError` naming `ulpe fetch-snapshot`.
  - `decode_logs(logs: pl.DataFrame) -> pl.DataFrame` (events table, columns below)
  - `build_swaps(events: pl.DataFrame, start_sqrt_price_x96: int, start_fee_protocol: int) -> pl.DataFrame`
  - `build_cex(raw_dir: Path) -> tuple[pl.DataFrame, pl.DataFrame]`. Raises `FileNotFoundError` naming
    `ulpe fetch-cex`.
  - `build_all(raw_dir: Path, interim_dir: Path) -> None`. Writes `events.parquet`, `swaps.parquet`,
    `cex_ethusdc.parquet` and `cex_ethusdt_1s.parquet`.
  - **events columns:**
    - Source: `block_number`, `block_timestamp`, `tx_hash`, `transaction_index`, `log_index`, `from_address`,
      `to_address`, `receipt_gas_used`, `receipt_effective_gas_price`, `max_priority_fee_per_gas`
    - Decoded: `event`, `sender`, `recipient`, `owner`, `amount0`, `amount1`, `sqrt_price_x96`, `liquidity`, `tick`,
      `tick_lower`, `tick_upper`, `amount`, `paid0`, `paid1`, `fee_protocol0_new`, `fee_protocol1_new`
    - Readable: `amount_usdc`, `amount_eth`, `price_usd`
  - **swaps columns:** all event columns, plus `direction`, `zero_for_one`, `notional_usd`, `fee_token`,
    `fee_amount_raw`, `fee_usd`, `pre_sqrt_price_x96`, `pre_price_usd`, `fee_protocol`, `fee_protocol_share`
  - CLI `ulpe build`

- [ ] **Step 1: Write the failing tests** in `tests/test_build.py`

```python
from pathlib import Path

import polars as pl
import pytest

from uniswap_lp_economics.build import build_swaps, decode_logs, load_raw_logs
from uniswap_lp_economics.events import SET_FEE_PROTOCOL_TOPIC, SWAP_TOPIC
from uniswap_lp_economics.v3math import eth_price_to_sqrt_price_x96


def word(v: int) -> str:
    return f"{v % 2**256:064x}"


ADDR = "0x" + "00" * 12 + "ab" * 20


def swap_log(block: int, idx: int, a0: int, a1: int, price: float, liq: int = 10**18) -> dict[str, object]:
    sqrt = eth_price_to_sqrt_price_x96(price)
    return {
        "block_number": block, "block_timestamp": None, "transaction_hash": f"0x{block:064x}",
        "transaction_index": 0, "log_index": idx, "topics": [SWAP_TOPIC, ADDR, ADDR],
        "data": "0x" + "".join(word(v) for v in (a0, a1, sqrt, liq, -196_000)),
        "from_address": ADDR, "to_address": ADDR, "receipt_gas_used": 1,
        "receipt_effective_gas_price": 1, "max_priority_fee_per_gas": 1,
    }


def fee_log(block: int, idx: int, new0: int, new1: int) -> dict[str, object]:
    row = swap_log(block, idx, 0, 0, 2000.0)
    row["topics"] = [SET_FEE_PROTOCOL_TOPIC]
    row["data"] = "0x" + word(0) + word(0) + word(new0) + word(new1)
    return row


def logs(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(rows).with_columns(
        block_timestamp=pl.datetime(2026, 7, 1, time_zone="UTC") + pl.duration(seconds=pl.col("block_number") * 12)
    )


def test_decode_logs_exact_ints_and_readable_columns() -> None:
    ev = decode_logs(logs([swap_log(1, 0, 2_000 * 10**6, -10**18, 2000.0)]))
    assert ev.schema["amount1"] == pl.Int128 and ev.schema["sqrt_price_x96"] == pl.Int128
    row = ev.row(0, named=True)
    assert row["event"] == "swap" and row["amount1"] == -(10**18)
    assert row["amount_usdc"] == 2000.0 and row["amount_eth"] == -1.0
    assert row["price_usd"] == pytest.approx(2000.0, rel=1e-9)
    assert row["tx_hash"] == f"0x{1:064x}"


def test_build_swaps_direction_fee_pre_price_and_protocol_share() -> None:
    ev = decode_logs(logs([
        swap_log(1, 0, 2_000 * 10**6, -10**18, 2001.0),  # trader sells USDC, buys ETH
        fee_log(2, 0, 4, 5),
        swap_log(3, 0, -2_000 * 10**6, 10**18, 1999.0),  # trader sells ETH
        swap_log(4, 0, 0, 0, 1999.0),  # zero-amount swap
    ]))
    start = eth_price_to_sqrt_price_x96(2000.0)
    s = build_swaps(ev, start_sqrt_price_x96=start, start_fee_protocol=0)
    assert s["direction"].to_list() == ["buy_eth", "sell_eth", "none"]
    assert s["fee_token"].to_list() == ["USDC", "WETH", None]
    assert s["fee_amount_raw"].to_list() == [10**6, 5 * 10**14, 0]
    assert s["pre_sqrt_price_x96"].to_list()[0] == start
    assert s["pre_price_usd"].to_list()[1] == pytest.approx(2001.0, rel=1e-9)
    assert s["fee_usd"].to_list()[0] == pytest.approx(1.0)
    assert s["fee_usd"].to_list()[1] == pytest.approx(0.0005 * 2001.0, rel=1e-6)
    # Before the switch: 0. After SetFeeProtocol(4, 5): ETH-in swaps use token1's 1/5.
    # The zero-amount swap has no token0 input, so it also reads token1's share (its fee is 0 anyway).
    assert s["fee_protocol_share"].to_list() == [0.0, 0.2, 0.2]


def test_missing_raw_logs_names_command(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="ulpe fetch-logs"):
        load_raw_logs(tmp_path)
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `uv run pytest tests/test_build.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `src/uniswap_lp_economics/build.py`**

```python
"""Raw downloads -> interim tables (events, swaps, CEX prices)."""

import json
from pathlib import Path
from typing import Any

import polars as pl

from uniswap_lp_economics.config import DECIMALS0, DECIMALS1
from uniswap_lp_economics.data.binance import parse_agg_trades, parse_klines_close
from uniswap_lp_economics.events import decode_event
from uniswap_lp_economics.v3math import Q96, fee_protocol_share, swap_fee_raw

EVENT_SCHEMA: dict[str, Any] = {
    "event": pl.String, "sender": pl.String, "recipient": pl.String, "owner": pl.String,
    "amount0": pl.Int128, "amount1": pl.Int128, "sqrt_price_x96": pl.Int128, "liquidity": pl.Int128,
    "tick": pl.Int64, "tick_lower": pl.Int64, "tick_upper": pl.Int64, "amount": pl.Int128,
    "paid0": pl.Int128, "paid1": pl.Int128, "fee_protocol0_new": pl.Int64, "fee_protocol1_new": pl.Int64,
}


def load_raw_logs(raw_dir: Path) -> pl.DataFrame:
    files = sorted(raw_dir.glob("pool_logs_*.parquet"))
    if not files:
        raise FileNotFoundError(f"no pool logs in {raw_dir}; run `ulpe fetch-logs` first")
    return pl.read_parquet(files).sort("block_number", "log_index")


def load_snapshot_meta(raw_dir: Path) -> dict[str, int]:
    path = raw_dir / "snapshot_meta.json"
    if not path.exists():
        raise FileNotFoundError(f"{path} missing; run `ulpe fetch-snapshot` first")
    meta: dict[str, int] = json.loads(path.read_text())
    return meta


def decode_logs(logs: pl.DataFrame) -> pl.DataFrame:
    rows = [decode_event(t, d) for t, d in zip(logs["topics"].to_list(), logs["data"].to_list(), strict=True)]
    decoded = pl.from_dicts(rows, schema=EVENT_SCHEMA)
    base = logs.drop("topics", "data").rename({"transaction_hash": "tx_hash"})
    sqrt = pl.col("sqrt_price_x96").cast(pl.Float64) / Q96
    return pl.concat([base, decoded], how="horizontal").with_columns(
        amount_usdc=pl.col("amount0").cast(pl.Float64) / 10**DECIMALS0,
        amount_eth=pl.col("amount1").cast(pl.Float64) / 10**DECIMALS1,
        price_usd=pl.when(pl.col("event") == "swap").then(10 ** (DECIMALS1 - DECIMALS0) / (sqrt * sqrt)),
    )


def build_swaps(events: pl.DataFrame, start_sqrt_price_x96: int, start_fee_protocol: int) -> pl.DataFrame:
    fee_protocols, fp = [], start_fee_protocol
    for kind, new0, new1 in events.select("event", "fee_protocol0_new", "fee_protocol1_new").iter_rows():
        if kind == "set_fee_protocol":
            fp = new0 + (new1 << 4)
        elif kind == "swap":
            fee_protocols.append(fp)

    swaps = events.filter(pl.col("event") == "swap")
    a0, a1 = swaps["amount0"].to_list(), swaps["amount1"].to_list()
    zero_for_one = [x > 0 for x in a0]
    amount_in = [x if x > 0 else (y if y > 0 else 0) for x, y in zip(a0, a1, strict=True)]
    fee_token = ["USDC" if z else ("WETH" if y > 0 else None) for z, y in zip(zero_for_one, a1, strict=True)]
    pre_sqrt = [start_sqrt_price_x96, *swaps["sqrt_price_x96"].to_list()[:-1]]
    pre = pl.Series("pre_sqrt_price_x96", pre_sqrt, dtype=pl.Int128).cast(pl.Float64) / Q96

    return swaps.with_columns(
        direction=pl.when(pl.col("amount1") < 0).then(pl.lit("buy_eth"))
        .when(pl.col("amount1") > 0).then(pl.lit("sell_eth")).otherwise(pl.lit("none")),
        zero_for_one=pl.Series(zero_for_one),
        notional_usd=pl.col("amount_usdc").abs(),
        fee_token=pl.Series(fee_token, dtype=pl.String),
        fee_amount_raw=pl.Series([swap_fee_raw(x) for x in amount_in], dtype=pl.Int128),
        pre_sqrt_price_x96=pl.Series(pre_sqrt, dtype=pl.Int128),
        pre_price_usd=10 ** (DECIMALS1 - DECIMALS0) / (pre * pre),
        fee_protocol=pl.Series(fee_protocols, dtype=pl.Int64),
        fee_protocol_share=pl.Series(
            [fee_protocol_share(f, z) for f, z in zip(fee_protocols, zero_for_one, strict=True)]
        ),
    ).with_columns(
        fee_usd=pl.when(pl.col("fee_token") == "USDC")
        .then(pl.col("fee_amount_raw").cast(pl.Float64) / 10**DECIMALS0)
        .when(pl.col("fee_token") == "WETH")
        .then(pl.col("fee_amount_raw").cast(pl.Float64) / 10**DECIMALS1 * pl.col("pre_price_usd"))
        .otherwise(0.0),
    )


def build_cex(raw_dir: Path) -> tuple[pl.DataFrame, pl.DataFrame]:
    agg = sorted((raw_dir / "binance").glob("ETHUSDC-aggTrades-*.zip"))
    kl = sorted((raw_dir / "binance").glob("ETHUSDT-1s-*.zip"))
    if not agg or not kl:
        raise FileNotFoundError(f"Binance files missing in {raw_dir / 'binance'}; run `ulpe fetch-cex` first")
    trades = pl.concat([parse_agg_trades(p) for p in agg]).sort("ts_us")
    klines = pl.concat([parse_klines_close(p) for p in kl]).sort("ts_us")
    return trades, klines


def build_all(raw_dir: Path, interim_dir: Path) -> None:
    interim_dir.mkdir(parents=True, exist_ok=True)
    meta = load_snapshot_meta(raw_dir)
    events = decode_logs(load_raw_logs(raw_dir))
    events.write_parquet(interim_dir / "events.parquet")
    swaps = build_swaps(events, int(meta["sqrt_price_x96"]), int(meta["fee_protocol"]))
    swaps.write_parquet(interim_dir / "swaps.parquet")
    trades, klines = build_cex(raw_dir)
    trades.write_parquet(interim_dir / "cex_ethusdc.parquet")
    klines.write_parquet(interim_dir / "cex_ethusdt_1s.parquet")
    print(f"events {events.height:,}  swaps {swaps.height:,}  cex trades {trades.height:,}  klines {klines.height:,}")
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_build.py -q`
Expected: 3 passed. If polars rejects a Python int above Int128, the test data is wrong. Never widen the column to a
float.

- [ ] **Step 5: Add the CLI command.** In `cli.py`, add `from uniswap_lp_economics import build` and register
  `sub.add_parser("build", help="decode raw data into interim tables")`. Dispatch it with:

```python
    elif args.command == "build":
        try:
            build.build_all(config.RAW_DIR, config.INTERIM_DIR)
        except FileNotFoundError as e:
            raise SystemExit(str(e)) from e
```

- [ ] **Step 6: Run it for real**

Run: `uv run ulpe build`
Expected: one summary line with about 556,664 events and about 534,377 swaps.

- [ ] **Step 7: Lint, type-check, commit, push**

```bash
uv run ruff format . && uv run ruff check . && uv run mypy src && uv run pytest -q
git add -A && git commit -m "Build events, swaps and CEX interim tables" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" && git push
```

---

### Task 8: Validation (C1–C6), report, `require_validated`, `ulpe all`

**Files:**
- Create: `src/uniswap_lp_economics/validate.py`, `tests/test_validate.py`
- Modify: `src/uniswap_lp_economics/cli.py`

**Interfaces:**
- Consumes:
  - `TickBook` (Task 3)
  - `get_sqrt_ratio_at_tick`, `get_tick_at_sqrt_ratio` (Task 2)
  - `load_snapshot_meta`, `build_all` (Task 7)
  - `config.*`
- Produces:
  - `CheckResult` dataclass: `name: str`, `passed: bool`, `summary: dict[str, Any]`, `mismatches: list[dict[str, Any]]`
  - `c2_tick_ok(sqrt_price_x96: int, tick: int) -> tuple[bool, bool]`. Returns `(ok, is_boundary_case)`.
  - `replay(events: pl.DataFrame, book: TickBook, fee_protocol: int, sample_ticks: dict[int, list[int]], full_blocks: set[int]) -> ReplayResult`
  - `ReplayResult` dataclass:
    - `c1: CheckResult`, `c2: CheckResult`
    - `states: dict[int, dict[str, Any]]`. Each state has keys `sqrt_price_x96`, `tick`, `liquidity`,
      `fee_protocol` and `ticks`, where `ticks` maps tick → `(gross, net)` for the requested ticks, or the full book
      for full blocks.
  - `check_c3(states, samples: pl.DataFrame, sample_ticks: pl.DataFrame) -> CheckResult`
  - `check_c4(ticks: pl.DataFrame, meta: dict[str, int]) -> CheckResult`
  - `check_c5(raw_logs: pl.DataFrame, events: pl.DataFrame, trades: pl.DataFrame, binance_dir: Path) -> CheckResult`
  - `check_c6(swaps: pl.DataFrame, trades: pl.DataFrame) -> CheckResult`
  - `write_report(results: list[CheckResult], out_dir: Path, extra: dict[str, Any]) -> str`. Returns `"PASS"` or
    `"FAIL"`.
  - `require_validated(report_dir: Path = VALIDATION_DIR) -> None`. Raises `RuntimeError` unless the report says PASS.
  - `run_validation() -> str`
  - CLI `ulpe validate` (exits 1 on FAIL) and `ulpe all`

- [ ] **Step 1: Write the failing tests** in `tests/test_validate.py`

```python
import json
from pathlib import Path

import polars as pl
import pytest

from uniswap_lp_economics.tickbook import TickBook
from uniswap_lp_economics.v3math import get_sqrt_ratio_at_tick as sqrt_at
from uniswap_lp_economics.validate import (
    CheckResult, c2_tick_ok, check_c3, check_c4, check_c6, replay, require_validated, write_report,
)


def ev(block: int, idx: int, event: str, **kw: int) -> dict[str, object]:
    row: dict[str, object] = {"block_number": block, "log_index": idx, "event": event, "tick": None,
                              "sqrt_price_x96": None, "liquidity": None, "tick_lower": None,
                              "tick_upper": None, "amount": None, "fee_protocol0_new": None,
                              "fee_protocol1_new": None}
    row.update(kw)
    return row


SCHEMA = {"block_number": pl.Int64, "log_index": pl.Int64, "event": pl.String, "tick": pl.Int64,
          "sqrt_price_x96": pl.Int128, "liquidity": pl.Int128, "tick_lower": pl.Int64, "tick_upper": pl.Int64,
          "amount": pl.Int128, "fee_protocol0_new": pl.Int64, "fee_protocol1_new": pl.Int64}


def events(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=SCHEMA)


def fresh_book() -> TickBook:
    b = TickBook(tick=50, sqrt_price_x96=sqrt_at(50), liquidity=0)
    b.apply_mint(-100, 100, 1000)
    return b


def test_c2_rule() -> None:
    assert c2_tick_ok(sqrt_at(10) + 5, 10) == (True, False)
    assert c2_tick_ok(sqrt_at(10), 9) == (True, True)  # downward swap stopping on the boundary
    assert c2_tick_ok(sqrt_at(10) + 5, 9) == (False, False)


def test_replay_consistent_events_pass_and_capture_states() -> None:
    e = events([
        ev(1, 0, "mint", tick_lower=0, tick_upper=200, amount=500),
        ev(1, 1, "swap", tick=150, sqrt_price_x96=sqrt_at(150) + 1, liquidity=500),  # crosses 100 (-1000)
        ev(2, 0, "set_fee_protocol", fee_protocol0_new=4, fee_protocol1_new=4),
        ev(3, 0, "burn", tick_lower=0, tick_upper=200, amount=500),
    ])
    r = replay(e, fresh_book(), fee_protocol=0, sample_ticks={1: [0, 100], 2: [0]}, full_blocks={2})
    assert r.c1.passed and r.c2.passed
    assert r.states[1]["liquidity"] == 500 and r.states[1]["tick"] == 150
    assert r.states[1]["ticks"] == {0: (500, 500), 100: (1000, -1000)}
    assert r.states[2]["fee_protocol"] == 4 | 4 << 4
    assert set(r.states[2]["ticks"]) == {-100, 0, 100, 200}  # full book


def test_replay_reports_c1_mismatch_with_location() -> None:
    e = events([ev(7, 3, "swap", tick=60, sqrt_price_x96=sqrt_at(60) + 1, liquidity=999)])
    r = replay(e, fresh_book(), fee_protocol=0, sample_ticks={}, full_blocks=set())
    assert not r.c1.passed
    assert r.c1.mismatches[0] == {"block": 7, "log_index": 3, "expected": 999, "replayed": 1000}


def test_c3_compares_exactly() -> None:
    states = {5: {"sqrt_price_x96": 1, "tick": 2, "liquidity": 3, "fee_protocol": 0, "ticks": {10: (4, -4)}}}
    samples = pl.DataFrame({"block": [5], "sqrt_price_x96": [1], "tick": [2], "fee_protocol": [0],
                            "liquidity": [3], "full_book": [False]})
    ticks = pl.DataFrame({"block": [5], "tick": [10], "liquidity_gross": [4], "liquidity_net": [-4]})
    assert check_c3(states, samples, ticks).passed
    bad = ticks.with_columns(liquidity_net=pl.lit(-5))
    assert not check_c3(states, samples, bad).passed


def test_c4_snapshot_consistency() -> None:
    ticks = pl.DataFrame({"tick": [-100, 100], "liquidity_gross": [10, 10], "liquidity_net": [10, -10]})
    assert check_c4(ticks, {"tick": 0, "liquidity": 10}).passed
    assert not check_c4(ticks, {"tick": 0, "liquidity": 11}).passed


def test_c6_median_deviation() -> None:
    ts = pl.datetime(2026, 7, 1, time_zone="UTC")
    swaps = pl.DataFrame({"block_timestamp": [1_000_000, 2_000_000], "price_usd": [2000.0, 2001.0]}).with_columns(
        block_timestamp=ts + pl.duration(microseconds=pl.col("block_timestamp"))
    )
    base = int(swaps["block_timestamp"].dt.epoch("us").min())  # type: ignore[arg-type]
    trades = pl.DataFrame({"ts_us": [base - 10, base + 999_000], "price": [2000.2, 2001.0]})
    r = check_c6(swaps, trades)
    assert r.passed and r.summary["median_bp"] == pytest.approx(0.5, abs=0.01)


def test_report_and_require_validated(tmp_path: Path) -> None:
    ok = CheckResult("C1", True, {"n": 1}, [])
    assert write_report([ok], tmp_path, {"commit": "abc"}) == "PASS"
    require_validated(tmp_path)
    assert "C1" in (tmp_path / "validation_report.md").read_text()
    write_report([ok, CheckResult("C2", False, {}, [{"x": 1}])], tmp_path, {})
    with pytest.raises(RuntimeError, match="FAIL"):
        require_validated(tmp_path)
    assert json.loads((tmp_path / "validation_report.json").read_text())["status"] == "FAIL"


def test_require_validated_missing_report(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="ulpe validate"):
        require_validated(tmp_path)
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `uv run pytest tests/test_validate.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `src/uniswap_lp_economics/validate.py`**

```python
"""Validation checks C1-C6 (see the data-foundation spec) and the committed report."""

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from uniswap_lp_economics import config
from uniswap_lp_economics.build import load_snapshot_meta
from uniswap_lp_economics.tickbook import TickBook
from uniswap_lp_economics.v3math import get_sqrt_ratio_at_tick, get_tick_at_sqrt_ratio

MAX_LISTED = 20
C6_MAX_MEDIAN_BP = 10.0


@dataclass
class CheckResult:
    name: str
    passed: bool
    summary: dict[str, Any]
    mismatches: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ReplayResult:
    c1: CheckResult
    c2: CheckResult
    states: dict[int, dict[str, Any]]


def c2_tick_ok(sqrt_price_x96: int, tick: int) -> tuple[bool, bool]:
    t = get_tick_at_sqrt_ratio(sqrt_price_x96)
    if tick == t:
        return True, False
    boundary = tick == t - 1 and sqrt_price_x96 == get_sqrt_ratio_at_tick(t)
    return boundary, boundary


def _capture(book: TickBook, fee_protocol: int, ticks: list[int] | None) -> dict[str, Any]:
    wanted = book.initialized_ticks() if ticks is None else ticks
    return {
        "sqrt_price_x96": book.sqrt_price_x96, "tick": book.tick, "liquidity": book.liquidity,
        "fee_protocol": fee_protocol,
        "ticks": {t: (book.liquidity_gross.get(t, 0), book.liquidity_net.get(t, 0)) for t in wanted},
    }


def replay(
    events: pl.DataFrame,
    book: TickBook,
    fee_protocol: int,
    sample_ticks: dict[int, list[int]],
    full_blocks: set[int],
) -> ReplayResult:
    """Replay events in (block, log_index) order; check C1/C2 and capture state after sample blocks."""
    pending = sorted(set(sample_ticks) | full_blocks)
    states: dict[int, dict[str, Any]] = {}
    c1_bad: list[dict[str, Any]] = []
    c2_bad: list[dict[str, Any]] = []
    n_swaps = c1_count = c2_count = boundary = 0
    cols = ["block_number", "log_index", "event", "tick", "sqrt_price_x96", "liquidity",
            "tick_lower", "tick_upper", "amount", "fee_protocol0_new", "fee_protocol1_new"]

    def flush(before_block: int | None) -> None:
        while pending and (before_block is None or pending[0] < before_block):
            b = pending.pop(0)
            states[b] = _capture(book, fee_protocol, None if b in full_blocks else sample_ticks.get(b, []))

    for blk, idx, kind, tick, sqrt, liq, lo, hi, amount, fp0, fp1 in events.sort(
        "block_number", "log_index"
    ).select(cols).iter_rows():
        flush(blk)
        if kind == "mint":
            book.apply_mint(lo, hi, amount)
        elif kind == "burn":
            book.apply_burn(lo, hi, amount)
        elif kind == "set_fee_protocol":
            fee_protocol = fp0 + (fp1 << 4)
        elif kind == "swap":
            n_swaps += 1
            book.apply_swap(sqrt, tick)
            if book.liquidity != liq:
                c1_count += 1
                if len(c1_bad) < MAX_LISTED:
                    c1_bad.append({"block": blk, "log_index": idx, "expected": liq, "replayed": book.liquidity})
                book.liquidity = liq  # resync so one bug doesn't cascade into every later swap
            ok, is_boundary = c2_tick_ok(sqrt, tick)
            boundary += is_boundary
            if not ok:
                c2_count += 1
                if len(c2_bad) < MAX_LISTED:
                    c2_bad.append({"block": blk, "log_index": idx, "tick": tick, "sqrt_price_x96": sqrt})
    flush(None)

    c1 = CheckResult("C1 active liquidity per swap", c1_count == 0,
                     {"swaps": n_swaps, "mismatches": c1_count}, c1_bad)
    c2 = CheckResult("C2 tick vs sqrt price", c2_count == 0,
                     {"swaps": n_swaps, "mismatches": c2_count, "boundary_cases": boundary}, c2_bad)
    return ReplayResult(c1, c2, states)


def check_c3(states: dict[int, dict[str, Any]], samples: pl.DataFrame, sample_ticks: pl.DataFrame) -> CheckResult:
    bad: list[dict[str, Any]] = []
    n_bad = n_ticks = 0
    ticks_by_block = sample_ticks.partition_by("block", as_dict=True)
    for row in samples.iter_rows(named=True):
        b = row["block"]
        s = states[b]
        for key in ("sqrt_price_x96", "tick", "liquidity", "fee_protocol"):
            if s[key] != row[key]:
                n_bad += 1
                if len(bad) < MAX_LISTED:
                    bad.append({"block": b, "field": key, "onchain": row[key], "replayed": s[key]})
        onchain = ticks_by_block.get((b,), pl.DataFrame())
        onchain_ticks = {
            t: (g, n) for t, g, n in onchain.select("tick", "liquidity_gross", "liquidity_net").iter_rows()
        } if onchain.height else {}
        replayed = s["ticks"]
        compare = set(onchain_ticks) | (set(replayed) if row["full_book"] else set())
        for t in compare:
            n_ticks += 1
            if onchain_ticks.get(t, (0, 0)) != replayed.get(t, (0, 0)):
                n_bad += 1
                if len(bad) < MAX_LISTED:
                    bad.append({"block": b, "tick": t, "onchain": onchain_ticks.get(t), "replayed": replayed.get(t)})
    return CheckResult("C3 on-chain samples", n_bad == 0,
                       {"blocks": samples.height, "full_book_blocks": int(samples["full_book"].sum()),
                        "ticks_compared": n_ticks, "mismatches": n_bad}, bad)


def check_c4(ticks: pl.DataFrame, meta: dict[str, int]) -> CheckResult:
    net = dict(zip(ticks["tick"].to_list(), ticks["liquidity_net"].to_list(), strict=True))
    total = sum(net.values())
    rebuilt = sum(v for t, v in net.items() if t <= meta["tick"])
    ok = total == 0 and rebuilt == meta["liquidity"]
    return CheckResult("C4 snapshot self-consistency", ok,
                       {"initialized_ticks": len(net), "sum_liquidity_net": total,
                        "rebuilt_active": rebuilt, "onchain_liquidity": meta["liquidity"]})


def check_c5(raw_logs: pl.DataFrame, events: pl.DataFrame, trades: pl.DataFrame, binance_dir: Path) -> CheckResult:
    start = datetime.combine(config.WINDOW_START, datetime.min.time(), UTC)
    end = datetime.combine(config.WINDOW_END, datetime.min.time(), UTC)
    dupes = raw_logs.height - raw_logs.select("block_number", "log_index").n_unique()
    unjoined = raw_logs["from_address"].null_count()
    ts = raw_logs["block_timestamp"]
    outside = raw_logs.filter((ts < start) | (ts >= end)).height
    other = events.filter(pl.col("event") == "other").height
    bad_sums = []
    zips = sorted(binance_dir.glob("*.zip"))
    for z in zips:
        checksum = z.with_name(z.name + ".CHECKSUM")
        if not checksum.exists() or hashlib.sha256(z.read_bytes()).hexdigest() != checksum.read_text().split()[0]:
            bad_sums.append(z.name)  # a missing checksum file counts as unverified
    max_gap_s = float(trades["ts_us"].diff().max() or 0) / 1e6  # type: ignore[arg-type]
    ok = dupes == 0 and unjoined == 0 and outside == 0 and not bad_sums and len(zips) > 0
    return CheckResult("C5 raw data integrity", ok,
                       {"logs": raw_logs.height, "duplicates": dupes, "unjoined_tx": unjoined,
                        "outside_window": outside, "other_events": other, "binance_files": len(zips),
                        "bad_checksums": bad_sums, "max_binance_trade_gap_s": max_gap_s})


def check_c6(swaps: pl.DataFrame, trades: pl.DataFrame) -> CheckResult:
    s = swaps.select(ts_us=pl.col("block_timestamp").dt.epoch("us"), price_usd="price_usd").sort("ts_us")
    joined = s.join_asof(trades.select("ts_us", "price").sort("ts_us"), on="ts_us", strategy="backward")
    dev = (joined["price_usd"] / joined["price"] - 1).abs() * 1e4
    median = float(dev.median() or 0.0)  # type: ignore[arg-type]
    return CheckResult("C6 pool vs Binance sanity", median < C6_MAX_MEDIAN_BP,
                       {"swaps": joined.height, "median_bp": median,
                        "p95_bp": float(dev.quantile(0.95) or 0.0), "bound_bp": C6_MAX_MEDIAN_BP})


def write_report(results: list[CheckResult], out_dir: Path, extra: dict[str, Any]) -> str:
    status = "PASS" if all(r.passed for r in results) else "FAIL"
    out_dir.mkdir(parents=True, exist_ok=True)
    body = {"status": status, **extra,
            "checks": [{"name": r.name, "passed": r.passed, "summary": r.summary, "mismatches": r.mismatches}
                       for r in results]}
    (out_dir / "validation_report.json").write_text(json.dumps(body, indent=2, default=str))
    lines = [f"# Validation report: **{status}**", ""]
    lines += [f"- {k}: `{v}`" for k, v in extra.items()]
    lines += ["", "| Check | Result | Summary |", "|---|---|---|"]
    lines += [f"| {r.name} | {'PASS' if r.passed else 'FAIL'} | "
              + ", ".join(f"{k}={v}" for k, v in r.summary.items()) + " |" for r in results]
    for r in results:
        if r.mismatches:
            lines += ["", f"## {r.name}: first mismatches", "", "```", *map(str, r.mismatches), "```"]
    (out_dir / "validation_report.md").write_text("\n".join(lines) + "\n")
    return status


def require_validated(report_dir: Path = config.VALIDATION_DIR) -> None:
    path = report_dir / "validation_report.json"
    if not path.exists():
        raise RuntimeError(f"{path} missing; run `ulpe validate` first")
    status = json.loads(path.read_text())["status"]
    if status != "PASS":
        raise RuntimeError(f"validation status is {status}; fix the data before analysis")


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def run_validation() -> str:
    raw, interim = config.RAW_DIR, config.INTERIM_DIR
    for p in (interim / "events.parquet", interim / "swaps.parquet", interim / "cex_ethusdc.parquet"):
        if not p.exists():
            raise FileNotFoundError(f"{p} missing; run `ulpe build` first")
    for p in (raw / "onchain_samples.parquet", raw / "onchain_sample_ticks.parquet"):
        if not p.exists():
            raise FileNotFoundError(f"{p} missing; run `ulpe fetch-samples` first")
    meta = load_snapshot_meta(raw)
    snap = pl.read_parquet(raw / "tickbook_snapshot.parquet")
    events = pl.read_parquet(interim / "events.parquet")
    swaps = pl.read_parquet(interim / "swaps.parquet")
    trades = pl.read_parquet(interim / "cex_ethusdc.parquet")
    samples = pl.read_parquet(raw / "onchain_samples.parquet")
    sample_ticks = pl.read_parquet(raw / "onchain_sample_ticks.parquet")
    raw_logs = pl.read_parquet(sorted(raw.glob("pool_logs_*.parquet")))

    full = set(samples.filter("full_book")["block"].to_list())
    wanted = {b: g["tick"].to_list() for (b,), g in sample_ticks.partition_by("block", as_dict=True).items()}
    for b in samples["block"].to_list():
        wanted.setdefault(b, [])
    r = replay(events, TickBook.from_snapshot(snap, meta), int(meta["fee_protocol"]), wanted, full)
    results = [r.c1, r.c2, check_c3(r.states, samples, sample_ticks), check_c4(snap, meta),
               check_c5(raw_logs, events, trades, raw / "binance"), check_c6(swaps, trades)]
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    extra = {"generated_utc": datetime.now(UTC).isoformat(timespec="seconds"), "git_commit": commit,
             "window": f"[{config.WINDOW_START}, {config.WINDOW_END})", "snapshot_block": meta["block"],
             "snapshot_fee_protocol": meta["fee_protocol"],
             "input_sha256_16": {p.name: _file_hash(p) for p in sorted(raw.glob("pool_logs_*.parquet"))}}
    status = write_report(results, config.VALIDATION_DIR, extra)
    for res in results:
        print(f"{'PASS' if res.passed else 'FAIL'}  {res.name}: {res.summary}")
    return status
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_validate.py -q`
Expected: 8 passed. Fix the implementation, not the tests, unless a test contradicts the spec.

- [ ] **Step 5: Add `validate` and `all` to the CLI.** In `cli.py`, add `from uniswap_lp_economics import validate`,
  register `validate` and `all`, and dispatch them:

```python
    elif args.command == "validate":
        try:
            status = validate.run_validation()
        except FileNotFoundError as e:
            raise SystemExit(str(e)) from e
        raise SystemExit(0 if status == "PASS" else 1)
    elif args.command == "all":
        for start, end in bigquery.month_windows(config.WINDOW_START, config.WINDOW_END):
            if not bigquery.raw_logs_path(start, end).exists():
                bigquery.fetch_pool_logs(start, end)
        fetch_snapshot()
        fetch_cex()
        fetch_samples()
        build.build_all(config.RAW_DIR, config.INTERIM_DIR)
        raise SystemExit(0 if validate.run_validation() == "PASS" else 1)
```

- [ ] **Step 6: Run validation for real**

Run: `uv run ulpe validate`
Expected: six `PASS` lines and exit code 0. On FAIL:
- Read `data_validation/validation_report.md`.
- Use superpowers:systematic-debugging on the first mismatch.
- Do not loosen a check to make it pass. If the C2 boundary rule is contradicted by real data, stop and report it to
  the user.

- [ ] **Step 7: Lint, type-check, commit (including the report), push**

```bash
uv run ruff format . && uv run ruff check . && uv run mypy src && uv run pytest -q
git add -A && git commit -m "Add validation checks C1-C6, report, require_validated and ulpe all" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" && git push
```

---

### Task 9: Real-data fixture and offline integration test

**Files:**
- Create: `scripts/make_fixture.py`, `tests/fixtures/fixture_events.parquet`, `tests/fixtures/fixture_ticks.parquet`,
  `tests/fixtures/fixture_meta.json`, `tests/test_integration.py`

**Interfaces:**
- Consumes: `replay`, `TickBook.from_snapshot`, and the interim/raw files from Tasks 5 and 7.
- Produces: a committed fixture of the first 400 events of the window, plus snapshot ticks within ±3,000 of the
  starting tick.

- [ ] **Step 1: Write `scripts/make_fixture.py`**

```python
"""Cut a small real-data fixture (first 400 events + nearby snapshot ticks) for the offline integration test."""

import json
from pathlib import Path

import polars as pl

from uniswap_lp_economics import config

N_EVENTS = 400
BAND = 3_000
OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures"

meta = json.loads((config.RAW_DIR / "snapshot_meta.json").read_text())
cols = ["block_number", "log_index", "event", "tick", "sqrt_price_x96", "liquidity",
        "tick_lower", "tick_upper", "amount", "fee_protocol0_new", "fee_protocol1_new"]
events = pl.read_parquet(config.INTERIM_DIR / "events.parquet").sort("block_number", "log_index").head(N_EVENTS)
events = events.select(cols)
lo, hi = meta["tick"] - BAND, meta["tick"] + BAND
touched = pl.concat([events["tick"], events["tick_lower"], events["tick_upper"]]).drop_nulls()
assert touched.filter(touched.is_between(lo, hi)).len() > 0
assert events.filter(pl.col("event") == "swap")["tick"].is_between(lo, hi).all(), "price left the band"
ticks = pl.read_parquet(config.RAW_DIR / "tickbook_snapshot.parquet").filter(pl.col("tick").is_between(lo, hi))
OUT.mkdir(parents=True, exist_ok=True)
events.write_parquet(OUT / "fixture_events.parquet")
ticks.write_parquet(OUT / "fixture_ticks.parquet")
(OUT / "fixture_meta.json").write_text(json.dumps(meta, indent=2))
print(f"fixture: {events.height} events, {ticks.height} ticks")
```

- [ ] **Step 2: Generate the fixture**

Run: `uv run python scripts/make_fixture.py`
Expected: `fixture: 400 events, <k> ticks`, with three files written under `tests/fixtures/`. Together they should be
under about 100 KB.

- [ ] **Step 3: Write the integration test** in `tests/test_integration.py`

```python
"""Offline replay of real mainnet events: runs in CI without keys or network."""

import json
from pathlib import Path

import polars as pl

from uniswap_lp_economics.tickbook import TickBook
from uniswap_lp_economics.validate import replay

FIX = Path(__file__).parent / "fixtures"


def test_real_events_replay_cleanly() -> None:
    meta = json.loads((FIX / "fixture_meta.json").read_text())
    book = TickBook.from_snapshot(pl.read_parquet(FIX / "fixture_ticks.parquet"), meta)
    events = pl.read_parquet(FIX / "fixture_events.parquet")
    r = replay(events, book, int(meta["fee_protocol"]), sample_ticks={}, full_blocks=set())
    assert r.c1.summary["swaps"] > 0
    assert r.c1.passed, r.c1.mismatches
    assert r.c2.passed, r.c2.mismatches
```

- [ ] **Step 4: Run it**

Run: `uv run pytest tests/test_integration.py -q`
Expected: 1 passed.

- [ ] **Step 5: Lint, type-check, commit, push, and check CI**

```bash
uv run ruff format . && uv run ruff check . && uv run mypy src && uv run pytest -q
git add -A && git commit -m "Add real-data fixture and offline integration test" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" && git push
gh run list --limit 1
```
Expected: the latest CI run reaches `success`. Check it once; don't poll in a loop.

---

### Task 10: Document results in the README

**Files:**
- Modify: `README.md` (Data, Reproduce and Repo map sections only; TL;DR stays pending)

- [ ] **Step 1: Read the final numbers** from `data_validation/validation_report.json`: C1 swaps, C3 blocks and ticks
  compared, C6 median, the snapshot block, and the `fee_protocol`.

- [ ] **Step 2: Update the README sections**
  - **Data:** replace the "match rate will be reported here" sentence with the actual numbers. Example shape:
    "Validation (full report: `data_validation/validation_report.md`): 534,377/534,377 swaps replay to the exact
    on-chain active liquidity; 500/500 random blocks match on-chain `slot0`, `liquidity()` and sampled `ticks()`
    exactly…". Use the real counts, never these example ones.
  - **Data:** state the protocol-fee finding as read from chain (on or off, and the value).
  - **Reproduce:** list `uv run ulpe all`, plus the requirements: a `.env` with `ETH_RPC_URL`, and
    `gcloud auth application-default login`.
  - **Repo map:** list every module from the file map at the top of this plan, one line each.

- [ ] **Step 3: Commit and push**

```bash
git add README.md && git commit -m "Document data foundation and validation results in README" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" && git push
```
