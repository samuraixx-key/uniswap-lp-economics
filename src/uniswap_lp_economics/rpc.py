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
            abi.enc_addr(target)
            + abi.enc_uint(1)
            + abi.enc_uint(0x60)
            + abi.enc_uint(len(payload))
            + padded
        )
    offsets, pos = [], 32 * len(calls)
    for t in tuples:
        offsets.append(abi.enc_uint(pos))
        pos += len(t) // 2
    return (
        _AGGREGATE3
        + abi.enc_uint(0x20)
        + abi.enc_uint(len(calls))
        + "".join(offsets)
        + "".join(tuples)
    )


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
    return {
        "sqrt_price_x96": abi.to_uint(w[0]),
        "tick": abi.to_int(w[1]),
        "fee_protocol": abi.to_uint(w[5]),
    }


def decode_ticks(result: str) -> tuple[int, int, bool]:
    w = abi.words(result)
    return abi.to_uint(w[0]), abi.to_int(w[1]), abi.to_uint(w[7]) == 1
