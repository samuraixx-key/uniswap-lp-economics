"""Decode raw Uniswap V3 pool logs (topics + data hex) into Python values."""

from typing import Any

# keccak256 of the event signatures in UniswapV3Pool.sol
SWAP_TOPIC = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"
# Swap(address,address,int256,int256,uint160,uint128,int24)
MINT_TOPIC = "0x7a53080ba414158be7ec69b987b5fb7d07dee101fe85488f0853ae16239d0bde"
# Mint(address,address,int24,int24,uint128,uint256,uint256)
BURN_TOPIC = "0x0c396cd989a39f4459b5fa1aed6a9a8dcdbc45908acfd67e028cd568da98982c"
# Burn(address,int24,int24,uint128,uint256,uint256)
COLLECT_TOPIC = "0x70935338e69775456a85ddef226c395fb668b63fa0115f5f20610b388e6ca9c0"
# Collect(address,address,int24,int24,uint128,uint128)

EVENT_TOPICS = {
    SWAP_TOPIC: "swap",
    MINT_TOPIC: "mint",
    BURN_TOPIC: "burn",
    COLLECT_TOPIC: "collect",
}


def _words(hex_str: str) -> list[str]:
    body = hex_str[2:] if hex_str.startswith("0x") else hex_str
    return [body[i : i + 64] for i in range(0, len(body), 64)]


def _uint(word: str) -> int:
    return int(word, 16)


def _int(word: str) -> int:
    value = int(word, 16)
    return value - 2**256 if value >= 2**255 else value


def _addr(word: str) -> str:
    return "0x" + word[-40:].lower()


def decode_event(topics: list[str], data: str) -> dict[str, Any]:
    """Decode one pool log. Raises ValueError for events we don't track."""
    kind = EVENT_TOPICS.get(topics[0].lower())
    if kind is None:
        raise ValueError(f"unknown event topic {topics[0]}")
    t = [_words(x)[0] for x in topics[1:]]
    d = _words(data)

    if kind == "swap":
        return {
            "event": kind,
            "sender": _addr(t[0]),
            "recipient": _addr(t[1]),
            "amount0": _int(d[0]),
            "amount1": _int(d[1]),
            "sqrt_price_x96": _uint(d[2]),
            "liquidity": _uint(d[3]),
            "tick": _int(d[4]),
        }

    position = {"owner": _addr(t[0]), "tick_lower": _int(t[1]), "tick_upper": _int(t[2])}
    if kind == "mint":
        return {
            "event": kind,
            **position,
            "sender": _addr(d[0]),
            "amount": _uint(d[1]),
            "amount0": _uint(d[2]),
            "amount1": _uint(d[3]),
        }
    if kind == "burn":
        return {
            "event": kind,
            **position,
            "amount": _uint(d[0]),
            "amount0": _uint(d[1]),
            "amount1": _uint(d[2]),
        }
    return {
        "event": kind,
        **position,
        "recipient": _addr(d[0]),
        "amount0": _uint(d[1]),
        "amount1": _uint(d[2]),
    }
