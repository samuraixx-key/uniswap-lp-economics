"""Minimal ABI helpers: keccak, selectors, topics and 32-byte word encoding."""

from Crypto.Hash import keccak


def keccak256(data: bytes) -> bytes:
    h = keccak.new(digest_bits=256)
    h.update(data)
    return h.digest()


def selector(signature: str) -> str:
    return "0x" + keccak256(signature.encode()).hex()[:8]


def topic(signature: str) -> str:
    return "0x" + keccak256(signature.encode()).hex()


def words(hex_str: str) -> list[str]:
    body = hex_str[2:] if hex_str.startswith("0x") else hex_str
    return [body[i : i + 64] for i in range(0, len(body), 64)]


def to_uint(word: str) -> int:
    return int(word, 16)


def to_int(word: str) -> int:
    value = int(word, 16)
    return value - 2**256 if value >= 2**255 else value


def to_addr(word: str) -> str:
    return "0x" + word[-40:].lower()


def enc_uint(v: int) -> str:
    return f"{v:064x}"


def enc_int(v: int) -> str:
    return f"{v % 2**256:064x}"


def enc_addr(addr: str) -> str:
    return addr[2:].lower().rjust(64, "0")
