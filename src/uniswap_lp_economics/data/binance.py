"""Binance public data (data.binance.vision): checksum-verified downloads and parsing."""

import hashlib
import zipfile
from pathlib import Path

import httpx
import polars as pl

BASE = "https://data.binance.vision/data/spot/monthly"
AGG_COLS = [
    "agg_trade_id",
    "price",
    "qty",
    "first_id",
    "last_id",
    "ts",
    "is_buyer_maker",
    "best_match",
]
KLINE_COLS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "count",
    "taker_base",
    "taker_quote",
    "ignore",
]


class ChecksumError(RuntimeError):
    pass


def agg_trades_url(symbol: str, year: int, month: int) -> str:
    return f"{BASE}/aggTrades/{symbol}/{symbol}-aggTrades-{year}-{month:02d}.zip"


def klines_url(symbol: str, interval: str, year: int, month: int) -> str:
    return f"{BASE}/klines/{symbol}/{interval}/{symbol}-{interval}-{year}-{month:02d}.zip"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download_verified(url: str, dest: Path, client: httpx.Client) -> Path:
    """Download url to dest unless a file matching Binance's published SHA256 is already there.

    The .CHECKSUM text is saved next to the zip so validation (C5) can re-verify offline. If both
    files exist and the zip matches the stored checksum, nothing is requested at all. A zip that
    is missing, corrupt, or has no stored checksum goes through the network path.
    """
    checksum_path = dest.with_name(dest.name + ".CHECKSUM")
    if dest.exists() and checksum_path.exists():
        stored = checksum_path.read_text().split()
        if stored and _sha256(dest) == stored[0]:
            return dest
    checksum_text = client.get(url + ".CHECKSUM").raise_for_status().text
    expected = checksum_text.split()[0]
    if dest.exists() and _sha256(dest) == expected:
        checksum_path.write_text(checksum_text)
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    with client.stream("GET", url) as r, tmp.open("wb") as f:
        r.raise_for_status()
        for chunk in r.iter_bytes():
            f.write(chunk)
    if _sha256(tmp) != expected:
        tmp.unlink()
        raise ChecksumError(f"checksum mismatch for {dest.name}")
    tmp.replace(dest)
    checksum_path.write_text(checksum_text)
    return dest


def _read_zip_csv(zip_path: Path, columns: list[str]) -> pl.DataFrame:
    with zipfile.ZipFile(zip_path) as z:
        raw = z.read(z.namelist()[0])
    has_header = not raw[:1].isdigit()
    return pl.read_csv(raw, has_header=has_header, new_columns=columns, infer_schema=False)


def _to_us(col: str) -> pl.Expr:
    # Binance moved spot data from ms to us; any value above 1e14 is already in us.
    ts = pl.col(col).cast(pl.Int64)
    return pl.when(ts > 10**14).then(ts).otherwise(ts * 1000)


def parse_agg_trades(zip_path: Path) -> pl.DataFrame:
    df = _read_zip_csv(zip_path, AGG_COLS)
    flag = pl.col("is_buyer_maker").str.to_lowercase()
    bad = df.filter(~flag.is_in(["true", "false"]).fill_null(False))
    if bad.height:
        raise ValueError(
            f"{zip_path.name}: {bad.height} rows with is_buyer_maker other than true/false, "
            f"e.g. {bad['is_buyer_maker'][0]!r}"
        )
    return df.select(
        agg_trade_id=pl.col("agg_trade_id").cast(pl.Int64),
        ts_us=_to_us("ts"),
        price=pl.col("price").cast(pl.Float64),
        qty=pl.col("qty").cast(pl.Float64),
        is_buyer_maker=flag == "true",
    )


def parse_klines_close(zip_path: Path) -> pl.DataFrame:
    return _read_zip_csv(zip_path, KLINE_COLS).select(
        ts_us=_to_us("open_time"), close=pl.col("close").cast(pl.Float64)
    )


def fetch_cex(months: list[tuple[int, int]], raw_dir: Path) -> list[Path]:
    out = []
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        for year, month in months:
            urls = (
                agg_trades_url("ETHUSDC", year, month),
                klines_url("ETHUSDT", "1s", year, month),
            )
            for url in urls:
                dest = raw_dir / "binance" / url.rsplit("/", 1)[1]
                out.append(download_verified(url, dest, client))
                print(f"  ok {dest.name}")
    return out
