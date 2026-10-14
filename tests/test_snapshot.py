import json
from pathlib import Path

import polars as pl
import pytest

from uniswap_lp_economics import cli, config, rpc
from uniswap_lp_economics.snapshot import (
    batched,
    bitmap_word_range,
    find_last_block_before,
    pick_sample_blocks,
    read_initialized_ticks,
    ticks_in_word,
)


def test_bitmap_word_range_covers_all_ticks() -> None:
    r = bitmap_word_range()
    assert (r.start, r.stop) == (-347, 347)  # floor(-887272/10) >> 8 = -347; 88727 >> 8 = 346


def test_ticks_in_word_handles_negative_words() -> None:
    assert ticks_in_word(0, 0b101) == [0, 20]
    assert ticks_in_word(-1, 1 << 255) == [-10]  # (-1*256 + 255) * 10


class StubClient:
    def __init__(
        self, timestamps: dict[int, int] | None = None, bitmaps: dict[int, int] | None = None
    ) -> None:
        self.timestamps = timestamps or {}
        self.bitmaps = bitmaps or {}

    def block_timestamp(self, block: int) -> int:
        return self.timestamps[block]

    def multicall(self, calls: list[tuple[str, str]], block: int) -> list[str | None]:
        out: list[str | None] = []
        for _, data in calls:
            word_pos = rpc.abi.to_int(data[10:])
            out.append("0x" + rpc.abi.enc_uint(self.bitmaps.get(word_pos, 0)))
        return out


def test_find_last_block_before() -> None:
    stub = StubClient(timestamps={b: 1000 + 12 * (b - 100) for b in range(100, 200)})
    # ts 1000 + 12*(b-100) < 1600  <=>  b < 150
    assert find_last_block_before(stub, 1600, 100, 199) == 149  # type: ignore[arg-type]


def test_read_initialized_ticks_uses_bitmap() -> None:
    stub = StubClient(bitmaps={0: 0b11, -1: 1 << 255})
    ticks = read_initialized_ticks(stub, 1, range(-1, 1))  # type: ignore[arg-type]
    assert ticks == [-10, 0, 10]


def test_pick_sample_blocks_is_deterministic_and_sorted() -> None:
    a = pick_sample_blocks(1, 10_000, n=50, n_full=5)
    b = pick_sample_blocks(1, 10_000, n=50, n_full=5)
    assert a == b
    blocks, full = a
    assert blocks == sorted(blocks) and len(blocks) == 50 and len(set(blocks)) == 50
    assert len(full) == 5 and set(full) <= set(blocks)
    assert full[0] == blocks[0] and full[-1] == blocks[-1]


def test_fetch_samples_requires_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "RAW_DIR", tmp_path)
    with pytest.raises(SystemExit, match="fetch-snapshot"):
        cli.fetch_samples()


class SnapshotClient:
    def __init__(self, fail_timestamp: bool = False) -> None:
        self.fail_timestamp = fail_timestamp

    def block_timestamp(self, block: int) -> int:
        if self.fail_timestamp:
            raise RuntimeError("rpc down")
        return 1_788_220_799


def _patch_fetch_snapshot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, client: SnapshotClient
) -> None:
    ticks = pl.DataFrame(
        {"tick": [-10, 10], "liquidity_gross": [5, 5], "liquidity_net": [5, -5]},
        schema={"tick": pl.Int64, "liquidity_gross": pl.Int128, "liquidity_net": pl.Int128},
    )
    meta = {"block": 99, "sqrt_price_x96": 2**96, "tick": 0, "fee_protocol": 68, "liquidity": 7}
    monkeypatch.setattr(config, "RAW_DIR", tmp_path)
    monkeypatch.setattr(cli, "_rpc", lambda: client)
    monkeypatch.setattr(cli, "_raw_logs", lambda: pl.DataFrame({"block_number": [1_000, 2_000]}))
    monkeypatch.setattr(cli.snapshot, "find_last_block_before", lambda *a, **k: 99)
    monkeypatch.setattr(cli.snapshot, "read_tick_book", lambda c, b: (ticks, dict(meta)))


def test_fetch_snapshot_writes_meta_last_and_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_fetch_snapshot(monkeypatch, tmp_path, SnapshotClient())
    calls: list[str] = []
    real = cli.write_text_atomic

    def spy(path: Path, text: str) -> None:
        assert (tmp_path / "tickbook_snapshot.parquet").exists()  # ticks first, meta last
        calls.append(path.name)
        real(path, text)

    monkeypatch.setattr(cli, "write_text_atomic", spy)
    cli.fetch_snapshot()
    assert calls == ["snapshot_meta.json"]
    meta = json.loads((tmp_path / "snapshot_meta.json").read_text())
    assert meta["block"] == 99 and meta["timestamp"] == 1_788_220_799
    assert (tmp_path / "tickbook_snapshot.parquet").exists()
    assert sorted(p.name for p in tmp_path.iterdir() if p.name.endswith(".part")) == []


def test_fetch_snapshot_failure_before_meta_leaves_no_skip_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_fetch_snapshot(monkeypatch, tmp_path, SnapshotClient(fail_timestamp=True))
    with pytest.raises(RuntimeError, match="rpc down"):
        cli.fetch_snapshot()
    assert not (tmp_path / "snapshot_meta.json").exists()  # a rerun will redo the snapshot


class FailingMulticall:
    def multicall(self, calls: list[tuple[str, str]], block: int) -> list[str | None]:
        return ["0x01", None][: len(calls)]


def test_batched_raises_on_failed_subcall_unless_allowed() -> None:
    client = FailingMulticall()
    calls = [("0x" + "00" * 20, "0x01"), ("0x" + "00" * 20, "0x02")]
    with pytest.raises(RuntimeError, match="sub-call failed"):
        batched(client, calls, 1)  # type: ignore[arg-type]
    assert batched(client, calls, 1, allow_failure=True) == ["0x01", None]  # type: ignore[arg-type]
