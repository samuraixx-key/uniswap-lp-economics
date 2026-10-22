from pathlib import Path

import httpx
import polars as pl
import pytest

from uniswap_lp_economics.data import relays
from uniswap_lp_economics.io import read_exact, write_exact

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
        "relays_unchecked": None,
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
    df = read_exact(again)
    assert again == path and df.height == 4 and set(df["value_wei"].to_list()) == {big}
    assert df["proposer_fee_recipient"][0] == "0xab" and df.schema["value_wei"] == pl.Int128


def test_invalid_json_on_a_200_is_retried() -> None:
    payload = [{"value": "9", "proposer_fee_recipient": "0xab", "builder_pubkey": "0x1"}]
    client = httpx.Client(
        transport=transport(
            {R1: [httpx.Response(200, content=b"not json"), httpx.Response(200, json=payload)]}
        )
    )
    row = relays.query_block(client, 7, (R1,), backoff_s=0)
    assert row["found"] and row["value_wei"] == 9


def test_no_sleep_after_the_last_failed_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(relays.time, "sleep", sleeps.append)
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    row = relays.query_block(client, 7, (R1,), backoff_s=1.0)
    assert not row["found"] and len(calls) == 3
    assert sleeps == [1.0, 2.0]  # between attempts only


def test_an_error_mid_sample_keeps_the_blocks_already_queried(tmp_path: Path) -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 3:
            raise RuntimeError("boom")
        return httpx.Response(200, json=[])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError):
        relays.fetch_relay_sample(tmp_path, 1, 100, n=5, client=client, relay_urls=(R1,))
    assert read_exact(tmp_path / relays.RELAY_FILE).height == 2


def _counting(handlers: dict[str, httpx.Response | Exception]) -> tuple[httpx.Client, list[str]]:
    """A client whose relays answer with fixed responses (or raise); records each request's host."""
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        base = f"{request.url.scheme}://{request.url.host}"
        hosts.append(base)
        answer = handlers[base]
        if isinstance(answer, Exception):
            raise answer
        return answer

    return httpx.Client(transport=httpx.MockTransport(handler)), hosts


def test_a_relay_that_always_times_out_is_skipped_after_three_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(relays.time, "sleep", lambda s: None)
    client, hosts = _counting({R1: httpx.ReadTimeout("slow"), R2: httpx.Response(200, json=[])})
    path = relays.fetch_relay_sample(tmp_path, 1, 100, n=8, client=client, relay_urls=(R1, R2))
    assert hosts.count(R1) == 3 * 3  # 3 blocks x 3 attempts, then no request at all
    assert hosts.count(R2) == 8
    assert R1 in capsys.readouterr().out
    df = read_exact(path)
    assert df.height == 8 and not df["found"].any()
    assert set(df["relays_unchecked"].to_list()) == {R1}  # failed, then skipped


def test_a_relay_that_fails_twice_then_answers_is_not_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(relays.time, "sleep", lambda s: None)
    payload = [{"value": "5", "proposer_fee_recipient": "0xab", "builder_pubkey": "0x1"}]
    # Blocks 1 and 2 fail (503 on all 3 attempts), block 3 answers, then failures resume.
    responses = [httpx.Response(503)] * 6 + [httpx.Response(200, json=payload)]

    def handler(request: httpx.Request) -> httpx.Response:
        return responses.pop(0) if responses else httpx.Response(503)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    breaker = relays.RelayBreaker()
    rows = [relays.query_block(client, b, (R1,), backoff_s=0, breaker=breaker) for b in (1, 2, 3)]
    assert [r["found"] for r in rows] == [False, False, True]
    assert breaker.skipped == set() and breaker.failed_blocks[R1] == 0
    for b in (4, 5):
        relays.query_block(client, b, (R1,), backoff_s=0, breaker=breaker)
    assert breaker.skipped == set()  # only 2 consecutive failures since the reset


def test_not_found_rows_list_the_unchecked_relay() -> None:
    client, _ = _counting({R1: httpx.Response(200, json=[]), R2: httpx.Response(404)})
    row = relays.query_block(client, 7, (R1, R2), backoff_s=0)
    assert not row["found"] and row["relays_unchecked"] is None  # 200 [] and 404 are answers
    client, _ = _counting({R1: httpx.Response(200, json=[]), R2: httpx.Response(500)})
    row = relays.query_block(client, 7, (R1, R2), backoff_s=0)
    assert not row["found"] and row["relays_unchecked"] == R2


def test_get_distinguishes_payloads_absent_and_failed() -> None:
    def get(response: httpx.Response) -> list[object] | None:
        c = httpx.Client(transport=httpx.MockTransport(lambda r: response))
        return relays._get(c, R1, 1, 0)

    assert get(httpx.Response(200, json=[{"value": "1"}])) == [{"value": "1"}]
    assert get(httpx.Response(200, json=[])) == []
    assert get(httpx.Response(200, json={"error": "x"})) == []
    assert get(httpx.Response(400)) == []
    assert get(httpx.Response(429)) is None
    assert get(httpx.Response(502)) is None
    assert get(httpx.Response(200, content=b"nope")) is None


def test_resume_with_an_old_file_lacking_the_new_column(tmp_path: Path) -> None:
    old_block = relays.sample_blocks(1, 100, 3)[0]
    old_cols = {"relays_unchecked", "round"}
    old_schema = {k: v for k, v in relays.RELAY_SCHEMA.items() if k not in old_cols}
    old = pl.DataFrame(
        {
            "block_number": [old_block],
            "relay": [None],
            "found": [False],
            "value_wei": [None],
            "proposer_fee_recipient": [None],
            "builder_pubkey": [None],
        },
        schema=old_schema,
    )
    write_exact(old, tmp_path / relays.RELAY_FILE)
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(int(request.url.params["block_number"]))
        return httpx.Response(200, json=[])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    path = relays.fetch_relay_sample(tmp_path, 1, 100, n=3, client=client, relay_urls=(R1,))
    df = read_exact(path)
    assert old_block not in calls and len(calls) == 2  # the old row is not refetched
    assert df.height == 3 and df.columns == list(relays.RELAY_SCHEMA)
    assert df.schema["relays_unchecked"] == pl.String
    # Old row: unknown (null). New rows: every relay answered, so also null.
    assert df.filter(pl.col("block_number") == old_block)["relays_unchecked"][0] is None


def _row(block: int, found: bool, unchecked: str | None, rnd: str = "seen") -> dict[str, object]:
    return {
        "block_number": block,
        "relay": R1 if found else None,
        "found": found,
        "value_wei": 3 * 10**20 if found else None,
        "proposer_fee_recipient": "0xab" if found else None,
        "builder_pubkey": None,
        "relays_unchecked": unchecked,
        "round": rnd,
    }


def test_an_old_file_without_round_reads_as_seen(tmp_path: Path) -> None:
    old_schema = {k: v for k, v in relays.RELAY_SCHEMA.items() if k != "round"}
    old = pl.DataFrame([_row(5, True, None)], schema=relays.RELAY_SCHEMA).select(list(old_schema))
    write_exact(old, tmp_path / relays.RELAY_FILE)
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[])))
    path = relays.fetch_relay_sample(tmp_path, 1, 100, n=3, client=client, relay_urls=(R1,))
    df = read_exact(path)
    assert df.columns == list(relays.RELAY_SCHEMA) and df.schema["round"] == pl.String
    assert set(df["round"].to_list()) == {"seen"}  # the old row and the two new ones


def test_retry_requeries_only_unchecked_not_found_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(relays.time, "sleep", sleeps.append)
    rows = [_row(1, True, None), _row(2, False, None), _row(3, False, R1), _row(4, False, R1)]
    write_exact(pl.DataFrame(rows, schema=relays.RELAY_SCHEMA), tmp_path / relays.RELAY_FILE)
    big = 7 * 10**20
    payload = [{"value": str(big), "proposer_fee_recipient": "0xCD", "builder_pubkey": "0x1"}]
    blocks: list[int] = []
    timeouts: list[object] = []

    def handler(request: httpx.Request) -> httpx.Response:
        blocks.append(int(request.url.params["block_number"]))
        timeouts.append(request.extensions["timeout"]["read"])
        return httpx.Response(200, json=payload)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    n = relays.retry_unchecked(tmp_path, client, (R1,), pace_s=0.25, timeout_s=60)
    df = read_exact(tmp_path / relays.RELAY_FILE).sort("block_number")
    assert n == 2 and blocks == [3, 4] and timeouts == [60, 60]
    assert sleeps == [0.25]  # between blocks only
    assert df["block_number"].to_list() == [1, 2, 3, 4]  # replaced in place, no duplicate
    assert df["round"].to_list() == ["seen", "seen", "retry", "retry"]
    assert df["value_wei"].to_list() == [3 * 10**20, None, big, big]
    assert df["relays_unchecked"].to_list() == [None] * 4
    assert relays.retry_unchecked(tmp_path, client, (R1,), pace_s=0) == 0  # nothing left


def test_a_retried_block_still_unfound_keeps_its_unchecked_relays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(relays.time, "sleep", lambda s: None)
    rows = [_row(3, False, R1 + "," + R2)]
    write_exact(pl.DataFrame(rows, schema=relays.RELAY_SCHEMA), tmp_path / relays.RELAY_FILE)
    client, _ = _counting({R1: httpx.Response(503), R2: httpx.Response(200, json=[])})
    assert relays.retry_unchecked(tmp_path, client, (R1, R2), pace_s=0) == 1
    df = read_exact(tmp_path / relays.RELAY_FILE)
    assert df.height == 1 and not df["found"][0]
    assert df["round"][0] == "retry" and df["relays_unchecked"][0] == R1
    assert R1 in capsys.readouterr().out


def test_an_error_mid_retry_keeps_every_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(relays.time, "sleep", lambda s: None)
    rows = [_row(b, False, R1) for b in (1, 2, 3)]
    write_exact(pl.DataFrame(rows, schema=relays.RELAY_SCHEMA), tmp_path / relays.RELAY_FILE)
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("boom")
        return httpx.Response(200, json=[])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError):
        relays.retry_unchecked(tmp_path, client, (R1,), pace_s=0)
    df = read_exact(tmp_path / relays.RELAY_FILE).sort("block_number")
    assert df["round"].to_list() == ["retry", "seen", "seen"]  # block 1 retried; 2, 3 untouched


@pytest.mark.parametrize("answer", [[], [{"value": "9", "proposer_fee_recipient": "0xab"}]])
def test_a_retried_holdout_row_stays_in_the_holdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, answer: list[object]
) -> None:
    monkeypatch.setattr(relays.time, "sleep", lambda s: None)
    rows = [_row(3, False, R1, "holdout"), _row(4, False, R1, "seen")]
    write_exact(pl.DataFrame(rows, schema=relays.RELAY_SCHEMA), tmp_path / relays.RELAY_FILE)
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=answer)))
    assert relays.retry_unchecked(tmp_path, client, (R1,), pace_s=0) == 2
    df = read_exact(tmp_path / relays.RELAY_FILE).sort("block_number")
    assert df["round"].to_list() == ["holdout", "retry"]
    assert df["found"].to_list() == [bool(answer)] * 2 and df["relays_unchecked"].null_count() == 2
