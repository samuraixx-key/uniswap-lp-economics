from uniswap_lp_economics import rpc
from uniswap_lp_economics.snapshot import (
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
