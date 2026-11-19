"""Unit tests for SingleWalletGuard and pure-Python Ethereum Keccak-256 / EIP-55."""

from __future__ import annotations

import sqlite3
import pytest

from reach_miner.wallet_guard import (
    SingleWalletGuard,
    SybilGuardViolationError,
    keccak256,
    to_checksum_address,
)

# Official Ethereum EIP-55 specification test vectors
EIP55_VECTORS = [
    "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed",
    "0xfB6916095ca1df60bB79Ce92cE3Ea74c37c5d359",
    "0xdbF03B407c01E7cD3CBea99509d93f8DDDC8C6FB",
    "0xD1220A0cf47c7B9Be7A2E6BA89F429762e7b9aDb",
]


def test_keccak256_empty_and_multiblock() -> None:
    # Known Ethereum Keccak-256("") vector
    assert (
        keccak256(b"").hex()
        == "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
    )
    # Test exact boundary lengths around 136-byte rate (134, 135, 136, 137, 272)
    for length in (134, 135, 136, 137, 272):
        digest = keccak256(b"a" * length)
        assert len(digest) == 32


@pytest.mark.parametrize("expected_eip55", EIP55_VECTORS)
def test_eip55_official_vectors(expected_eip55: str) -> None:
    assert to_checksum_address(expected_eip55.lower()) == expected_eip55
    assert to_checksum_address(expected_eip55.upper().replace("0X", "0x")) == expected_eip55
    assert to_checksum_address(expected_eip55) == expected_eip55


def test_eip55_rejects_bad_mixed_case_and_zero_address() -> None:
    bad_mixed = "0x5aaeb6053F3E94C9b9A09f33669435E7Ef1BeAed"
    with pytest.raises(SybilGuardViolationError, match="EIP-55 checksum mismatch"):
        to_checksum_address(bad_mixed)

    with pytest.raises(SybilGuardViolationError, match="Zero address"):
        to_checksum_address("0x0000000000000000000000000000000000000000")


def test_single_wallet_guard_three_way_match_and_sqlite_lock() -> None:
    conn = sqlite3.connect(":memory:")
    addr = EIP55_VECTORS[0]
    guard = SingleWalletGuard.verify_and_lock(addr.lower(), addr, addr, sqlite_conn=conn)
    assert guard.canonical_address == addr

    # Re-verifying with same wallet succeeds
    guard_again = SingleWalletGuard.verify_and_lock(addr, addr, addr, sqlite_conn=conn)
    assert guard_again.canonical_address == addr

    # Mismatched DoraHacks address fails immediately
    with pytest.raises(SybilGuardViolationError, match="Wallet mismatch"):
        SingleWalletGuard.verify_and_lock(addr, addr, EIP55_VECTORS[1])

    # Attempting to rotate to a second wallet on the same SQLite ledger fails
    second = EIP55_VECTORS[1]
    with pytest.raises(SybilGuardViolationError, match="LEDGER WALLET ROTATION FORBIDDEN"):
        SingleWalletGuard.verify_and_lock(second, second, second, sqlite_conn=conn)
    conn.close()
