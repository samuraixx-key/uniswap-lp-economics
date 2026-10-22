"""Binance USDⓈ-M perpetual data (data.binance.vision): funding rates and 1-minute klines."""

from pathlib import Path

import httpx
import polars as pl

from uniswap_lp_economics.data.binance import KLINE_COLS, _read_zip_csv, _to_us, download_verified
from uniswap_lp_economics.strategy.params import HEDGE_SYMBOL

BASE = "https://data.binance.vision/data/futures/um/monthly"
FUTURES_DIR = "binance_futures"
# Header of ETHUSDC-fundingRate-2026-07.zip. The klines files have the same 12 positions as spot.
FUNDING_COLS = ["calc_time", "funding_interval_hours", "last_funding_rate"]


def funding_url(symbol: str, year: int, month: int) -> str:
    return f"{BASE}/fundingRate/{symbol}/{symbol}-fundingRate-{year}-{month:02d}.zip"


def klines_url(symbol: str, interval: str, year: int, month: int) -> str:
    return f"{BASE}/klines/{symbol}/{interval}/{symbol}-{interval}-{year}-{month:02d}.zip"


def fetch_futures(
    months: list[tuple[int, int]], raw_dir: Path, symbol: str = HEDGE_SYMBOL
) -> list[Path]:
    """Funding-rate and 1-minute kline files for each month; files already on disk are kept."""
    out = []
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        for year, month in months:
            for url in (
                funding_url(symbol, year, month),
                klines_url(symbol, "1m", year, month),
            ):
                dest = raw_dir / FUTURES_DIR / url.rsplit("/", 1)[1]
                out.append(download_verified(url, dest, client))
                print(f"  ok {dest.name}")
    return out


def _files(raw_dir: Path, pattern: str) -> list[Path]:
    files = sorted((raw_dir / FUTURES_DIR).glob(pattern))
    if not files:
        raise FileNotFoundError(
            f"no {pattern} files in {raw_dir / FUTURES_DIR}; run `ulpe fetch-futures`"
        )
    return files


def load_funding(raw_dir: Path) -> pl.DataFrame:
    files = _files(raw_dir, f"{HEDGE_SYMBOL}-fundingRate-*.zip")
    return pl.concat(
        _read_zip_csv(p, FUNDING_COLS).select(
            ts_us=_to_us("calc_time"), rate=pl.col("last_funding_rate").cast(pl.Float64)
        )
        for p in files
    ).sort("ts_us")


def load_perp_minutes(raw_dir: Path) -> pl.DataFrame:
    """Perpetual 1-minute closes; ts_us is the minute's open."""
    files = _files(raw_dir, f"{HEDGE_SYMBOL}-1m-*.zip")
    return pl.concat(
        _read_zip_csv(p, KLINE_COLS).select(
            ts_us=_to_us("open_time"), close=pl.col("close").cast(pl.Float64)
        )
        for p in files
    ).sort("ts_us")
