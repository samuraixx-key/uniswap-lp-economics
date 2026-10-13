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
            "event": kind,
            "sender": to_addr(t[0]),
            "recipient": to_addr(t[1]),
            "amount0": to_int(d[0]),
            "amount1": to_int(d[1]),
            "sqrt_price_x96": to_uint(d[2]),
            "liquidity": to_uint(d[3]),
            "tick": to_int(d[4]),
        }
    if kind == "flash":
        return {
            "event": kind,
            "sender": to_addr(t[0]),
            "recipient": to_addr(t[1]),
            "amount0": to_uint(d[0]),
            "amount1": to_uint(d[1]),
            "paid0": to_uint(d[2]),
            "paid1": to_uint(d[3]),
        }
    if kind == "collect_protocol":
        return {
            "event": kind,
            "sender": to_addr(t[0]),
            "recipient": to_addr(t[1]),
            "amount0": to_uint(d[0]),
            "amount1": to_uint(d[1]),
        }
    if kind == "set_fee_protocol":
        return {
            "event": kind,
            "fee_protocol0_old": to_uint(d[0]),
            "fee_protocol1_old": to_uint(d[1]),
            "fee_protocol0_new": to_uint(d[2]),
            "fee_protocol1_new": to_uint(d[3]),
        }

    position = {"owner": to_addr(t[0]), "tick_lower": to_int(t[1]), "tick_upper": to_int(t[2])}
    if kind == "mint":
        return {
            "event": kind,
            **position,
            "sender": to_addr(d[0]),
            "amount": to_uint(d[1]),
            "amount0": to_uint(d[2]),
            "amount1": to_uint(d[3]),
        }
    if kind == "burn":
        return {
            "event": kind,
            **position,
            "amount": to_uint(d[0]),
            "amount0": to_uint(d[1]),
            "amount1": to_uint(d[2]),
        }
    return {
        "event": kind,
        **position,
        "recipient": to_addr(d[0]),
        "amount0": to_uint(d[1]),
        "amount1": to_uint(d[2]),
    }
