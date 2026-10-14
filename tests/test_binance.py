import hashlib
import io
import zipfile
from pathlib import Path

import httpx
import polars as pl
import pytest

from uniswap_lp_economics.data.binance import (
    ChecksumError,
    agg_trades_url,
    download_verified,
    load_minute_klines,
    parse_agg_trades,
    parse_klines_close,
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
    header = (
        "agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,"
        "is_buyer_maker,is_best_match\n"
    )
    make_zip(tmp_path / "h.zip", "h.csv", header + "1,2500.5,0.1,1,1,1751328000123,true,true\n")
    assert parse_agg_trades(tmp_path / "h.zip").height == 1


def test_parse_agg_trades_rejects_unknown_is_buyer_maker(tmp_path: Path) -> None:
    make_zip(tmp_path / "bad.zip", "b.csv", "1,2500.5,0.1,1,1,1751328000123,maybe,True\n")
    with pytest.raises(ValueError, match=r"bad\.zip.*is_buyer_maker"):
        parse_agg_trades(tmp_path / "bad.zip")


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
    download_verified("https://x.invalid/f.zip", dest, client)  # file + checksum verify locally
    assert len(hits) == n  # skipped without any request


def test_download_verified_skips_offline_when_local_files_verify(tmp_path: Path) -> None:
    payload = b"zip-bytes"
    digest = hashlib.sha256(payload).hexdigest()
    dest = tmp_path / "f.zip"
    dest.write_bytes(payload)
    (tmp_path / "f.zip.CHECKSUM").write_text(f"{digest}  f.zip\n")

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected network request: {request.url}")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert download_verified("https://x.invalid/f.zip", dest, client) == dest


def test_download_verified_refetches_corrupt_or_unchecked_local_file(tmp_path: Path) -> None:
    payload = b"zip-bytes"
    digest = hashlib.sha256(payload).hexdigest()
    hits: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hits.append(str(request.url))
        if str(request.url).endswith(".CHECKSUM"):
            return httpx.Response(200, text=f"{digest}  f.zip\n")
        return httpx.Response(200, content=payload)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    dest = tmp_path / "f.zip"
    checksum = tmp_path / "f.zip.CHECKSUM"
    dest.write_bytes(b"corrupt")  # checksum file present but the zip does not match it
    checksum.write_text(f"{digest}  f.zip\n")
    download_verified("https://x.invalid/f.zip", dest, client)
    assert dest.read_bytes() == payload and hits
    hits.clear()
    checksum.unlink()  # valid zip but no stored checksum: the network confirms and stores it
    download_verified("https://x.invalid/f.zip", dest, client)
    assert hits and checksum.read_text().startswith(digest)


def test_download_verified_bad_checksum_leaves_nothing(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith(".CHECKSUM"):
            return httpx.Response(200, text="0" * 64 + "  f.zip\n")
        return httpx.Response(200, content=b"tampered")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(ChecksumError):
        download_verified("https://x.invalid/f.zip", tmp_path / "f.zip", client)
    assert list(tmp_path.iterdir()) == []


def test_parse_agg_trades_keeps_the_aggregated_trade_id(tmp_path: Path) -> None:
    make_zip(tmp_path / "a.zip", "a.csv", "42,2500.5,0.1,1,1,1751328000123000,True,True\n")
    df = parse_agg_trades(tmp_path / "a.zip")
    assert df.columns[0] == "agg_trade_id"
    assert df["agg_trade_id"].to_list() == [42]
    assert df["agg_trade_id"].dtype == pl.Int64


def test_load_minute_klines_names_the_command(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="ulpe fetch-price-history"):
        load_minute_klines(tmp_path)
