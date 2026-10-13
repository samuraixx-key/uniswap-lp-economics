import pytest

from uniswap_lp_economics.events import (
    BURN_TOPIC,
    COLLECT_TOPIC,
    MINT_TOPIC,
    SWAP_TOPIC,
    decode_event,
)

OWNER = "0x" + "ab" * 20
SENDER = "0x" + "cd" * 20


def word(value: int) -> str:
    """ABI-encode an int as a 32-byte word (two's complement for negatives)."""
    return f"{value % 2**256:064x}"


def addr_word(addr: str) -> str:
    return addr[2:].rjust(64, "0")


def topic(value: int) -> str:
    return "0x" + word(value)


def test_swap_negative_and_positive_amounts() -> None:
    # Trader sells 2000 USDC (pool receives, +) for 0.8 WETH (pool pays, -).
    data = "0x" + "".join(
        word(v) for v in (2_000 * 10**6, -8 * 10**17, 2**96 * 22_000, 10**18, -196_256)
    )
    ev = decode_event([SWAP_TOPIC, "0x" + addr_word(SENDER), "0x" + addr_word(OWNER)], data)
    assert ev == {
        "event": "swap",
        "sender": SENDER,
        "recipient": OWNER,
        "amount0": 2_000 * 10**6,
        "amount1": -8 * 10**17,
        "sqrt_price_x96": 2**96 * 22_000,
        "liquidity": 10**18,
        "tick": -196_256,
    }


def test_mint_has_signed_ticks_in_topics() -> None:
    data = "0x" + addr_word(SENDER) + word(123) + word(456) + word(789)
    ev = decode_event([MINT_TOPIC, "0x" + addr_word(OWNER), topic(-200_000), topic(-190_000)], data)
    assert ev == {
        "event": "mint",
        "owner": OWNER,
        "tick_lower": -200_000,
        "tick_upper": -190_000,
        "sender": SENDER,
        "amount": 123,
        "amount0": 456,
        "amount1": 789,
    }


def test_burn() -> None:
    data = "0x" + word(123) + word(456) + word(789)
    ev = decode_event([BURN_TOPIC, "0x" + addr_word(OWNER), topic(195_000), topic(196_000)], data)
    assert ev["event"] == "burn"
    assert (ev["tick_lower"], ev["tick_upper"], ev["amount"]) == (195_000, 196_000, 123)
    assert (ev["amount0"], ev["amount1"]) == (456, 789)


def test_collect() -> None:
    data = "0x" + addr_word(SENDER) + word(11) + word(22)
    ev = decode_event([COLLECT_TOPIC, "0x" + addr_word(OWNER), topic(-10), topic(10)], data)
    assert ev["event"] == "collect"
    assert (ev["recipient"], ev["amount0"], ev["amount1"]) == (SENDER, 11, 22)


def test_unknown_topic_raises() -> None:
    with pytest.raises(ValueError, match="unknown event"):
        decode_event(["0x" + "00" * 32], "0x")
