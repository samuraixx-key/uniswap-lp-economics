from uniswap_lp_economics import abi


def test_topic_matches_known_swap_hash() -> None:
    # Verified on 2026-10-13 against real pool logs on BigQuery.
    assert (
        abi.topic("Swap(address,address,int256,int256,uint160,uint128,int24)")
        == "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"
    )


def test_selector_matches_known_slot0() -> None:
    # 0x3850c7bd was used successfully against Alchemy on 2026-10-13.
    assert abi.selector("slot0()") == "0x3850c7bd"


def test_int_word_round_trip() -> None:
    for v in (0, 1, -1, 2**255 - 1, -(2**255)):
        assert abi.to_int(abi.enc_int(v)) == v


def test_uint_and_addr_words() -> None:
    assert abi.enc_uint(255) == "0" * 62 + "ff"
    addr = "0x" + "ab" * 20
    assert abi.to_addr(abi.enc_addr(addr)) == addr
    assert abi.words("0x" + "00" * 32 + "11" * 32) == ["00" * 32, "11" * 32]
