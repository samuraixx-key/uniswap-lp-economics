import json
import logging
from collections.abc import Callable

import httpx
import pytest

from uniswap_lp_economics import abi
from uniswap_lp_economics.rpc import (
    RpcClient,
    RpcError,
    decode_aggregate3,
    decode_slot0,
    decode_ticks,
    encode_aggregate3,
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
        + abi.enc_uint(0x20)
        + abi.enc_uint(1)
        + abi.enc_uint(0x20)
        + abi.enc_addr(target)
        + abi.enc_uint(1)
        + abi.enc_uint(0x60)
        + abi.enc_uint(4)
        + "3850c7bd"
        + "00" * 28
    )
    assert encoded == expected


def test_decode_aggregate3_success_and_failure() -> None:
    result = "0x" + "".join(
        [
            abi.enc_uint(0x20),
            abi.enc_uint(2),
            abi.enc_uint(0x40),
            abi.enc_uint(0xC0),
            abi.enc_uint(1),
            abi.enc_uint(0x40),
            abi.enc_uint(32),
            "01" * 32,
            abi.enc_uint(0),
            abi.enc_uint(0x40),
            abi.enc_uint(0),
        ]
    )
    assert decode_aggregate3(result) == ["0x" + "01" * 32, None]


def test_decode_slot0_and_ticks() -> None:
    slot0 = "0x" + "".join(
        [abi.enc_uint(2**96 * 40), abi.enc_int(-196_256)]
        + [abi.enc_uint(0)] * 3
        + [abi.enc_uint(4 | 5 << 4), abi.enc_uint(1)]
    )
    assert decode_slot0(slot0) == {
        "sqrt_price_x96": 2**96 * 40,
        "tick": -196_256,
        "fee_protocol": 0x54,
    }
    ticks = "0x" + "".join(
        [abi.enc_uint(10), abi.enc_int(-7)] + [abi.enc_uint(0)] * 5 + [abi.enc_uint(1)]
    )
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
        return ok("0x0")()

    RpcClient(URL, transport=httpx.MockTransport(handler)).eth_call(
        "0x" + "22" * 20, "0x3850c7bd", 255
    )
    assert seen[0]["method"] == "eth_call"
    assert seen[0]["params"] == [{"to": "0x" + "22" * 20, "data": "0x3850c7bd"}, "0xff"]


def test_info_logging_never_contains_url(caplog: pytest.LogCaptureFixture) -> None:
    c, _ = client_with([ok("0x10")])
    with caplog.at_level(logging.INFO):
        assert c.block_number() == 16
    assert "SECRETKEY" not in caplog.text


def test_invalid_url_error_is_wrapped_without_chaining() -> None:
    def bad(request: httpx.Request) -> httpx.Response:
        raise httpx.InvalidURL(f"bad {URL}")

    c = RpcClient(URL, transport=httpx.MockTransport(bad), backoff_s=0)
    with pytest.raises(RpcError) as exc:
        c.block_number()
    assert "SECRETKEY" not in str(exc.value)
    assert exc.value.__cause__ is None
    assert exc.value.__context__ is None


def test_non_json_200_is_retried_then_raises_rpc_error() -> None:
    c, calls = client_with([lambda: httpx.Response(200, text="<html>bad gateway</html>")])
    with pytest.raises(RpcError, match="non-JSON") as exc:
        c.block_number()
    assert calls[0] == c.max_retries
    assert exc.value.__context__ is None


def test_non_json_200_then_success() -> None:
    c, calls = client_with([lambda: httpx.Response(200, text="oops"), ok("0x10")])
    assert c.block_number() == 16
    assert calls[0] == 2


@pytest.mark.parametrize(
    "body", [{"jsonrpc": "2.0", "id": 1}, {"error": "boom"}, {"error": None}, [1, 2]]
)
def test_malformed_response_shape_raises_rpc_error(body: object) -> None:
    c, calls = client_with([lambda: httpx.Response(200, json=body)])
    with pytest.raises(RpcError, match="malformed") as exc:
        c.block_number()
    assert calls[0] == 1
    assert exc.value.__context__ is None


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
