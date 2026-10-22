import hashlib
import io
import zipfile
from pathlib import Path
from typing import Any

import pytest

from uniswap_lp_economics.data import futures
from uniswap_lp_economics.data.binance import KLINE_COLS

# Headers as published in ETHUSDC-fundingRate-2026-07.zip and ETHUSDC-1m-2026-07.zip.
FUNDING_HEADER = "calc_time,funding_interval_hours,last_funding_rate\n"
KLINE_HEADER = (
    "open_time,open,high,low,close,volume,close_time,quote_volume,count,"
    "taker_buy_volume,taker_buy_quote_volume,ignore\n"
)


def make_zip(path: Path, text: str) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("data.csv", text)
    path.write_bytes(buf.getvalue())


def test_urls() -> None:
    base = "https://data.binance.vision/data/futures/um/monthly"
    assert futures.funding_url("ETHUSDC", 2026, 7) == (
        f"{base}/fundingRate/ETHUSDC/ETHUSDC-fundingRate-2026-07.zip"
    )
    assert futures.klines_url("ETHUSDC", "1m", 2026, 7) == (
        f"{base}/klines/ETHUSDC/1m/ETHUSDC-1m-2026-07.zip"
    )


def test_pinned_funding_columns_match_the_published_header() -> None:
    assert FUNDING_HEADER.strip().split(",") == futures.FUNDING_COLS
    assert KLINE_HEADER.count(",") + 1 == len(KLINE_COLS)


@pytest.mark.parametrize("header", [FUNDING_HEADER, ""], ids=["header", "no-header"])
@pytest.mark.parametrize("factor", [1, 1000], ids=["ms", "us"])
def test_parse_funding(tmp_path: Path, header: str, factor: int) -> None:
    folder = tmp_path / futures.FUTURES_DIR
    folder.mkdir()
    rows = f"{1782864000000 * factor},8,0.00006512\n{1782892800000 * factor},8,-0.00001542\n"
    make_zip(folder / "ETHUSDC-fundingRate-2026-07.zip", header + rows)
    out = futures.load_funding(tmp_path)
    assert out.columns == ["ts_us", "rate"]
    assert out["ts_us"].to_list() == [1782864000000000, 1782892800000000]
    assert out["rate"].to_list() == [0.00006512, -0.00001542]


@pytest.mark.parametrize("header", [KLINE_HEADER, ""], ids=["header", "no-header"])
@pytest.mark.parametrize("factor", [1, 1000], ids=["ms", "us"])
def test_parse_klines(tmp_path: Path, header: str, factor: int) -> None:
    folder = tmp_path / futures.FUTURES_DIR
    folder.mkdir()
    t0 = 1782864000000 * factor
    step = 60_000 * factor
    rows = (
        f"{t0 + step},1571.02,1571.39,1570.07,1570.64,434.691,{t0 + 2 * step - 1},1,719,1,1,0\n"
        f"{t0},1569.54,1571.45,1569.54,1571.00,685.031,{t0 + step - 1},1,999,1,1,0\n"
    )
    make_zip(folder / "ETHUSDC-1m-2026-07.zip", header + rows)
    out = futures.load_perp_minutes(tmp_path)
    assert out.columns == ["ts_us", "close"]
    assert out["ts_us"].to_list() == [1782864000000000, 1782864060000000]  # sorted
    assert out["close"].to_list() == [1571.00, 1570.64]


def test_load_without_files_names_the_command(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="ulpe fetch-futures"):
        futures.load_funding(tmp_path)
    with pytest.raises(FileNotFoundError, match="ulpe fetch-futures"):
        futures.load_perp_minutes(tmp_path)


class NoNetwork:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def __enter__(self) -> "NoNetwork":
        return self

    def __exit__(self, *exc: object) -> None:
        pass

    def get(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("a file on disk was requested again")

    stream = get


def test_fetch_skips_existing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    folder = tmp_path / futures.FUTURES_DIR
    folder.mkdir()
    paths = [
        folder / "ETHUSDC-fundingRate-2026-07.zip",
        folder / "ETHUSDC-1m-2026-07.zip",
    ]
    for p in paths:
        make_zip(p, "x\n")
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        p.with_name(p.name + ".CHECKSUM").write_text(f"{digest}  {p.name}\n")
    monkeypatch.setattr(futures.httpx, "Client", NoNetwork)
    assert futures.fetch_futures([(2026, 7)], tmp_path) == paths
