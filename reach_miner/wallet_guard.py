"""SingleWalletGuard: Anti-Sybil EVM Wallet Lock & Pure-Python EIP-55 Checksum."""

from __future__ import annotations

from dataclasses import dataclass
import os
import re
import sqlite3

_HEX_ADDR_RE = re.compile(r"^0[xX][0-9a-fA-F]{40}$")
_ZERO_ADDR = "0x" + ("0" * 40)

# Exact 24 Keccak-f[1600] round constants (original Keccak-256 used by Ethereum EIP-55)
_KECCAK_RC = (
    0x0000000000000001,
    0x0000000000008082,
    0x800000000000808A,
    0x8000000080008000,
    0x000000000000808B,
    0x0000000080000001,
    0x8000000080008081,
    0x8000000000008009,
    0x000000000000008A,
    0x0000000000000088,
    0x0000000080008009,
    0x000000008000000A,
    0x000000008000808B,
    0x800000000000008B,
    0x8000000000008089,
    0x8000000000008003,
    0x8000000000008002,
    0x8000000000000080,
    0x000000000000800A,
    0x800000008000000A,
    0x8000000080008081,
    0x8000000000008080,
    0x0000000080000001,
    0x8000000080008008,
)

_MASK64 = (1 << 64) - 1


def _rotl64(val: int, shift: int) -> int:
    shift &= 63
    if shift == 0:
        return val & _MASK64
    return ((val << shift) | (val >> (64 - shift))) & _MASK64


def keccak256(data: bytes) -> bytes:
    """Compute Ethereum Keccak-256 (pre-FIPS-202 0x01 domain padding) in pure Python."""
    rate_bytes = 136
    state = [0] * 25

    buf = bytearray(data)
    pad_len = rate_bytes - (len(buf) % rate_bytes)
    if pad_len == 1:
        buf.append(0x81)
    else:
        buf.append(0x01)
        buf.extend(b"\x00" * (pad_len - 2))
        buf.append(0x80)

    for block_offset in range(0, len(buf), rate_bytes):
        block = buf[block_offset : block_offset + rate_bytes]
        for lane_idx in range(rate_bytes // 8):
            lane = int.from_bytes(block[lane_idx * 8 : (lane_idx + 1) * 8], "little")
            state[lane_idx] ^= lane

        for rc in _KECCAK_RC:
            # Theta
            c = [
                state[x] ^ state[x + 5] ^ state[x + 10] ^ state[x + 15] ^ state[x + 20]
                for x in range(5)
            ]
            d = [c[(x - 1) % 5] ^ _rotl64(c[(x + 1) % 5], 1) for x in range(5)]
            for idx in range(25):
                state[idx] ^= d[idx % 5]

            # Rho and Pi
            x, y = 1, 0
            current = state[x + 5 * y]
            for t in range(24):
                x, y = y, (2 * x + 3 * y) % 5
                shift = ((t + 1) * (t + 2) // 2) % 64
                prev = state[x + 5 * y]
                state[x + 5 * y] = _rotl64(current, shift)
                current = prev

            # Chi
            for row_start in range(0, 25, 5):
                row = state[row_start : row_start + 5]
                for x_idx in range(5):
                    state[row_start + x_idx] = (
                        row[x_idx] ^ ((~row[(x_idx + 1) % 5]) & row[(x_idx + 2) % 5])
                    ) & _MASK64

            # Iota
            state[0] ^= rc

    out = bytearray()
    for lane_idx in range(4):
        out.extend(state[lane_idx].to_bytes(8, "little"))
    return bytes(out)


class SybilGuardViolationError(RuntimeError):
    """Raised when SingleWalletGuard detects mismatched, invalid, or rotated wallets."""


def to_checksum_address(address: str) -> str:
    """Validate and convert a 20-byte EVM hex address to EIP-55 checksum format."""
    if not isinstance(address, str) or not _HEX_ADDR_RE.match(address.strip()):
        raise SybilGuardViolationError(f"Invalid EVM wallet address format: {address!r}")
    clean = address.strip()
    lower_hex = clean[2:].lower()
    if f"0x{lower_hex}" == _ZERO_ADDR:
        raise SybilGuardViolationError("Zero address (0x000...000) is forbidden for competition binding")

    digest_hex = keccak256(lower_hex.encode("ascii")).hex()
    checksummed_chars = [
        ch.upper() if int(digest_hex[i], 16) >= 8 else ch
        for i, ch in enumerate(lower_hex)
    ]
    checksummed = "0x" + "".join(checksummed_chars)

    # If input had mixed case, enforce strict EIP-55 checksum validity
    raw_body = clean[2:]
    if raw_body != raw_body.lower() and raw_body != raw_body.upper():
        if f"0x{raw_body}" != checksummed:
            raise SybilGuardViolationError(
                f"EIP-55 checksum mismatch: got {clean}, expected {checksummed}"
            )
    return checksummed


@dataclass(frozen=True)
class SingleWalletGuard:
    """Enforces 100% identity across Delphi account, API key binding, DoraHacks BUIDL, and SQLite."""

    delphi_wallet_address: str
    api_bound_wallet_address: str
    dorahacks_wallet_address: str
    canonical_address: str

    @classmethod
    def verify_and_lock(
        cls,
        delphi_wallet: str,
        api_bound_wallet: str,
        dorahacks_wallet: str,
        sqlite_conn: sqlite3.Connection | None = None,
    ) -> "SingleWalletGuard":
        """Validate 3-way address equality and optionally bind immutably into SQLite ledger."""
        addr_delphi = to_checksum_address(delphi_wallet)
        addr_api = to_checksum_address(api_bound_wallet)
        addr_dora = to_checksum_address(dorahacks_wallet)

        if not (addr_delphi == addr_api == addr_dora):
            raise SybilGuardViolationError(
                "ANTI-SYBIL HARD LOCK TRIGGERED: Wallet mismatch across platforms! "
                f"delphi={addr_delphi}, api_bound={addr_api}, dorahacks={addr_dora}"
            )

        if sqlite_conn is not None:
            cls._bind_to_ledger(sqlite_conn, addr_delphi)

        return cls(
            delphi_wallet_address=addr_delphi,
            api_bound_wallet_address=addr_api,
            dorahacks_wallet_address=addr_dora,
            canonical_address=addr_delphi,
        )

    @classmethod
    def from_env(cls, sqlite_conn: sqlite3.Connection | None = None) -> "SingleWalletGuard":
        """Initialize SingleWalletGuard from runtime environment variables."""
        delphi_wallet = os.environ.get("DELPHI_WALLET_ADDRESS", "")
        api_wallet = os.environ.get("DELPHI_API_BOUND_WALLET", "")
        dora_wallet = os.environ.get("DORAHACKS_BUIDL_WALLET", "")
        return cls.verify_and_lock(delphi_wallet, api_wallet, dora_wallet, sqlite_conn=sqlite_conn)

    @staticmethod
    def _bind_to_ledger(conn: sqlite3.Connection, canonical_address: str) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS wallet_identity_lock (
                singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                canonical_wallet TEXT NOT NULL,
                locked_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
            )
            """
        )
        row = conn.execute(
            "SELECT canonical_wallet FROM wallet_identity_lock WHERE singleton_id = 1"
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO wallet_identity_lock (singleton_id, canonical_wallet) VALUES (1, ?)",
                (canonical_address,),
            )
            conn.commit()
        elif row[0] != canonical_address:
            raise SybilGuardViolationError(
                f"LEDGER WALLET ROTATION FORBIDDEN: Ledger is permanently bound to {row[0]}, "
                f"attempted execution with {canonical_address}"
            )
