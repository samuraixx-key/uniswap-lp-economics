from pathlib import Path

import httpx
import polars as pl

from uniswap_lp_economics.data import relays

R1, R2 = "https://relay-one.example", "https://relay-two.example"


def transport(answers: dict[str, list[httpx.Response]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        queue = answers[f"{request.url.scheme}://{request.url.host}"]
        return queue.pop(0) if len(queue) > 1 else queue[0]

    return httpx.MockTransport(handler)


def test_query_block_tries_relays_in_order_and_retries() -> None:
    payload = [
        {
            "value": "12345",
            "proposer_fee_recipient": "0x" + "ab" * 20,
            "builder_pubkey": "0xbeef",
        }
    ]
    client = httpx.Client(
        transport=transport(
            {
                R1: [httpx.Response(200, json=[])],
                R2: [httpx.Response(429), httpx.Response(200, json=payload)],
            }
        )
    )
    row = relays.query_block(client, 7, (R1, R2), backoff_s=0)
    assert row["found"] and row["relay"] == R2 and row["value_wei"] == 12345


def test_query_block_not_found() -> None:
    client = httpx.Client(transport=transport({R1: [httpx.Response(200, json=[])]}))
    row = relays.query_block(client, 7, (R1,), backoff_s=0)
    assert row == {
        "block_number": 7,
        "relay": None,
        "found": False,
        "value_wei": None,
        "proposer_fee_recipient": None,
        "builder_pubkey": None,
    }


def test_fetch_relay_sample_resumes(tmp_path: Path) -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(int(request.url.params["block_number"]))
        return httpx.Response(200, json=[])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    path = relays.fetch_relay_sample(tmp_path, 1, 100, n=5, client=client, relay_urls=(R1,))
    assert pl.read_parquet(path).height == 5 and len(calls) == 5
    relays.fetch_relay_sample(tmp_path, 1, 100, n=5, client=client, relay_urls=(R1,))
    assert len(calls) == 5  # nothing re-queried
    assert relays.sample_blocks(1, 100, 5) == relays.sample_blocks(1, 100, 5)


def test_resume_keeps_found_rows_with_exact_wei(tmp_path: Path) -> None:
    big = 3 * 10**20
    payload = [{"value": str(big), "proposer_fee_recipient": "0xAB", "builder_pubkey": "0xbeef"}]
    client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
    )
    path = relays.fetch_relay_sample(tmp_path, 1, 100, n=3, client=client, relay_urls=(R1,))
    again = relays.fetch_relay_sample(tmp_path, 1, 100, n=4, client=client, relay_urls=(R1,))
    df = relays.read_exact(again)
    assert again == path and df.height == 4 and set(df["value_wei"].to_list()) == {big}
    assert df["proposer_fee_recipient"][0] == "0xab" and df.schema["value_wei"] == pl.Int128
