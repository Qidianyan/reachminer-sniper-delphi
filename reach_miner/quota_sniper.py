"""QuotaSniper: SQLite 3-Bullet State Machine, Qualification Tracker & Telemetry Ledger."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any

from .models import (
    DelphiMarket,
    EvidencePacket,
    JudgedSubmissionRecord,
    QualificationStatus,
    ShadowJudgeDecision,
)
from .wallet_guard import SingleWalletGuard

MAX_BULLETS_PER_MARKET = 3
MIN_QUALIFYING_MARKETS = 3
MIN_QUALIFYING_SUBMISSIONS = 10


class QuotaExceededError(RuntimeError):
    """Raised when attempting to fire more than 3 bullets on a single Delphi market."""


class QuotaSniper:
    """Persists per-market 3-bullet magazine state, verdicts, and API telemetry in SQLite."""

    def __init__(self, db_path: str | Path, wallet_guard: SingleWalletGuard) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self._init_schema()
        # Enforce immutable wallet lock inside the SQLite database
        self.wallet_guard = SingleWalletGuard.verify_and_lock(
            wallet_guard.delphi_wallet_address,
            wallet_guard.api_bound_wallet_address,
            wallet_guard.dorahacks_wallet_address,
            sqlite_conn=self.conn,
        )

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS market_quotas (
                market_id TEXT PRIMARY KEY,
                question TEXT NOT NULL,
                category TEXT NOT NULL,
                resolution_time_utc TEXT NOT NULL,
                current_probability REAL NOT NULL,
                bullets_used INTEGER NOT NULL DEFAULT 0
                    CHECK (bullets_used >= 0 AND bullets_used <= 3),
                max_bullets INTEGER NOT NULL DEFAULT 3
                    CHECK (max_bullets = 3),
                last_updated_utc TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS evidence_submissions (
                submission_id TEXT PRIMARY KEY,
                packet_id TEXT NOT NULL UNIQUE,
                market_id TEXT NOT NULL REFERENCES market_quotas(market_id),
                wallet_address TEXT NOT NULL,
                bullet_slot INTEGER NOT NULL CHECK (bullet_slot BETWEEN 1 AND 3),
                submitted_at_utc TEXT NOT NULL,
                p_before REAL NOT NULL,
                shadow_p_after REAL NOT NULL,
                official_p_after REAL NOT NULL,
                verdict TEXT NOT NULL CHECK (verdict IN ('ACCEPTED', 'REJECTED', 'PENDING')),
                verdict_rationale TEXT NOT NULL,
                stage1_reward_usdc REAL NOT NULL DEFAULT 0.0,
                stage2_settlement_usdc REAL NOT NULL DEFAULT 0.0,
                api_latency_ms REAL NOT NULL,
                attachment_count INTEGER NOT NULL CHECK (attachment_count BETWEEN 0 AND 3),
                fact_fingerprint_sha256 TEXT NOT NULL,
                explanatory_note TEXT NOT NULL,
                source_links_json TEXT NOT NULL,
                attachments_json TEXT NOT NULL,
                UNIQUE (market_id, bullet_slot),
                UNIQUE (market_id, fact_fingerprint_sha256)
            );

            CREATE TABLE IF NOT EXISTS blocked_attempts (
                attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
                market_id TEXT NOT NULL,
                signal_id TEXT NOT NULL,
                attempted_at_utc TEXT NOT NULL,
                rejection_reason TEXT NOT NULL,
                abs_delta_p REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS api_telemetry (
                telemetry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                endpoint TEXT NOT NULL,
                http_method TEXT NOT NULL,
                status_code INTEGER NOT NULL,
                latency_ms REAL NOT NULL,
                attachment_count INTEGER NOT NULL DEFAULT 0,
                payload_bytes INTEGER NOT NULL DEFAULT 0,
                sdk_mode TEXT NOT NULL DEFAULT 'competition-testnet',
                note TEXT NOT NULL DEFAULT '',
                recorded_at_utc TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS scanned_market_funnel (
                market_id TEXT PRIMARY KEY,
                question TEXT NOT NULL,
                category TEXT NOT NULL,
                prior_p REAL NOT NULL,
                resolution_time_utc TEXT NOT NULL,
                eligible INTEGER NOT NULL,
                rejection_reason TEXT,
                shannon_entropy_bits REAL NOT NULL,
                in_entropy_sweet_spot INTEGER NOT NULL,
                dynamic_beta REAL NOT NULL,
                two_stage_ev_usdc REAL NOT NULL,
                priority_score REAL NOT NULL,
                rank_order INTEGER NOT NULL
            );
            """
        )
        self.conn.commit()

    def save_scanned_funnel(self, ranked_entries: list[Any]) -> None:
        """Persist full MarketSelector funnel evaluation (eligible + rejected) into SQLite."""
        with self.conn:
            self.conn.execute("DELETE FROM scanned_market_funnel")
            for idx, entry in enumerate(ranked_entries):
                self.conn.execute(
                    """
                    INSERT INTO scanned_market_funnel (
                        market_id, question, category, prior_p, resolution_time_utc,
                        eligible, rejection_reason, shannon_entropy_bits, in_entropy_sweet_spot,
                        dynamic_beta, two_stage_ev_usdc, priority_score, rank_order
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entry.market.market_id,
                        entry.market.question,
                        entry.market.category,
                        entry.market.current_probability,
                        entry.market.resolution_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        1 if entry.eligible else 0,
                        entry.rejection_reason,
                        entry.shannon_entropy_bits,
                        1 if entry.in_entropy_sweet_spot else 0,
                        entry.dynamic_beta,
                        entry.two_stage_ev_usdc,
                        entry.priority_score,
                        idx,
                    ),
                )

    def register_market(self, market: DelphiMarket, updated_at_utc: str) -> None:
        """Upsert market metadata without overwriting bullets_used."""
        res_str = market.resolution_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        self.conn.execute(
            """
            INSERT INTO market_quotas (
                market_id, question, category, resolution_time_utc,
                current_probability, bullets_used, max_bullets, last_updated_utc
            ) VALUES (?, ?, ?, ?, ?, 0, 3, ?)
            ON CONFLICT(market_id) DO UPDATE SET
                question = excluded.question,
                category = excluded.category,
                resolution_time_utc = excluded.resolution_time_utc,
                current_probability = excluded.current_probability,
                last_updated_utc = excluded.last_updated_utc
            """,
            (
                market.market_id,
                market.question,
                market.category,
                res_str,
                market.current_probability,
                updated_at_utc,
            ),
        )
        self.conn.commit()

    def get_bullets_used(self, market_id: str) -> int:
        row = self.conn.execute(
            "SELECT bullets_used FROM market_quotas WHERE market_id = ?",
            (market_id,),
        ).fetchone()
        return int(row["bullets_used"]) if row is not None else 0

    def get_remaining_bullets(self, market_id: str) -> int:
        return max(0, MAX_BULLETS_PER_MARKET - self.get_bullets_used(market_id))

    def get_market_history(self, market_id: str) -> tuple[list[str], list[str]]:
        """Return (fact_fingerprints, explanatory_notes) already submitted for market_id."""
        rows = self.conn.execute(
            """
            SELECT fact_fingerprint_sha256, explanatory_note
            FROM evidence_submissions
            WHERE market_id = ?
            ORDER BY bullet_slot ASC
            """,
            (market_id,),
        ).fetchall()
        return (
            [str(r["fact_fingerprint_sha256"]) for r in rows],
            [str(r["explanatory_note"]) for r in rows],
        )

    def record_blocked_attempt(
        self,
        market_id: str,
        signal_id: str,
        attempted_at_utc: str,
        rejection_reason: str,
        abs_delta_p: float,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO blocked_attempts (
                market_id, signal_id, attempted_at_utc, rejection_reason, abs_delta_p
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (market_id, signal_id, attempted_at_utc, rejection_reason, abs_delta_p),
        )
        self.conn.commit()

    def commit_submission(
        self,
        market: DelphiMarket,
        packet: EvidencePacket,
        decision: ShadowJudgeDecision,
        submission_id: str,
        official_p_after: float,
        verdict: str,
        verdict_rationale: str,
        stage1_reward_usdc: float,
        stage2_settlement_usdc: float,
        api_latency_ms: float,
    ) -> JudgedSubmissionRecord:
        """Atomically consume 1 bullet slot (hard cap <= 3) and persist judged submission."""
        if packet.wallet_address != self.wallet_guard.canonical_address:
            raise PermissionError(
                f"Packet wallet {packet.wallet_address} != locked wallet {self.wallet_guard.canonical_address}"
            )
        if not decision.allow_fire:
            raise ValueError(f"Cannot commit submission denied by ShadowJudge: {decision.rejection_reason}")

        self.register_market(market, packet.created_at_utc)

        try:
            with self.conn:
                row = self.conn.execute(
                    "SELECT bullets_used FROM market_quotas WHERE market_id = ?",
                    (market.market_id,),
                ).fetchone()
                used = int(row["bullets_used"]) if row is not None else 0
                if used >= MAX_BULLETS_PER_MARKET:
                    raise QuotaExceededError(
                        f"Market {market.market_id} already consumed {used}/{MAX_BULLETS_PER_MARKET} bullets"
                    )
                next_slot = used + 1
                self.conn.execute(
                    """
                    UPDATE market_quotas
                    SET bullets_used = ?, current_probability = ?, last_updated_utc = ?
                    WHERE market_id = ?
                    """,
                    (next_slot, official_p_after, packet.created_at_utc, market.market_id),
                )

                attachments_meta = [
                    {
                        "filename": a.filename,
                        "media_type": a.media_type,
                        "sha256_hex": a.sha256_hex,
                        "size_bytes": a.size_bytes,
                    }
                    for a in packet.attachments
                ]

                self.conn.execute(
                    """
                    INSERT INTO evidence_submissions (
                        submission_id, packet_id, market_id, wallet_address, bullet_slot,
                        submitted_at_utc, p_before, shadow_p_after, official_p_after,
                        verdict, verdict_rationale, stage1_reward_usdc, stage2_settlement_usdc,
                        api_latency_ms, attachment_count, fact_fingerprint_sha256,
                        explanatory_note, source_links_json, attachments_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        submission_id,
                        packet.packet_id,
                        market.market_id,
                        packet.wallet_address,
                        next_slot,
                        packet.created_at_utc,
                        decision.p_before,
                        decision.p_after,
                        official_p_after,
                        verdict,
                        verdict_rationale,
                        stage1_reward_usdc,
                        stage2_settlement_usdc,
                        api_latency_ms,
                        len(packet.attachments),
                        packet.fact_fingerprint_sha256,
                        packet.explanatory_note,
                        json.dumps(list(packet.source_links)),
                        json.dumps(attachments_meta),
                    ),
                )

                payload_bytes = sum(a.size_bytes for a in packet.attachments) + len(
                    packet.explanatory_note.encode("utf-8")
                )
                self.conn.execute(
                    """
                    INSERT INTO api_telemetry (
                        endpoint, http_method, status_code, latency_ms,
                        attachment_count, payload_bytes, sdk_mode, note, recorded_at_utc
                    ) VALUES (?, 'POST', 200, ?, ?, ?, 'competition-testnet', ?, ?)
                    """,
                    (
                        f"/v1/markets/{market.market_id}/evidence",
                        api_latency_ms,
                        len(packet.attachments),
                        payload_bytes,
                        f"slot={next_slot};verdict={verdict}",
                        packet.created_at_utc,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            if "bullets_used" in str(exc) or "bullet_slot" in str(exc):
                raise QuotaExceededError(f"SQLite atomic constraint blocked >3 bullets: {exc}") from exc
            raise

        return JudgedSubmissionRecord(
            submission_id=submission_id,
            packet_id=packet.packet_id,
            market_id=market.market_id,
            wallet_address=packet.wallet_address,
            bullet_slot=next_slot,
            submitted_at_utc=packet.created_at_utc,
            p_before=decision.p_before,
            shadow_p_after=decision.p_after,
            official_p_after=official_p_after,
            verdict=verdict,
            verdict_rationale=verdict_rationale,
            stage1_reward_usdc=stage1_reward_usdc,
            stage2_settlement_usdc=stage2_settlement_usdc,
            api_latency_ms=api_latency_ms,
            attachment_count=len(packet.attachments),
            fact_fingerprint_sha256=packet.fact_fingerprint_sha256,
            explanatory_note=packet.explanatory_note,
            attachments_meta=attachments_meta,
        )

    def record_api_telemetry(
        self,
        endpoint: str,
        http_method: str,
        status_code: int,
        latency_ms: float,
        recorded_at_utc: str,
        attachment_count: int = 0,
        payload_bytes: int = 0,
        note: str = "",
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO api_telemetry (
                endpoint, http_method, status_code, latency_ms,
                attachment_count, payload_bytes, sdk_mode, note, recorded_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, 'competition-testnet', ?, ?)
            """,
            (
                endpoint,
                http_method,
                status_code,
                latency_ms,
                attachment_count,
                payload_bytes,
                note,
                recorded_at_utc,
            ),
        )
        self.conn.commit()

    def get_qualification_status(self) -> QualificationStatus:
        row = self.conn.execute(
            """
            SELECT
                COUNT(DISTINCT market_id) AS distinct_markets,
                COUNT(*) AS judged_total
            FROM evidence_submissions
            WHERE verdict IN ('ACCEPTED', 'REJECTED')
            """
        ).fetchone()
        return QualificationStatus(
            distinct_judged_markets=int(row["distinct_markets"]) if row else 0,
            total_judged_submissions=int(row["judged_total"]) if row else 0,
            min_markets_required=MIN_QUALIFYING_MARKETS,
            min_judged_required=MIN_QUALIFYING_SUBMISSIONS,
        )

    def export_dashboard_snapshot(self) -> dict[str, Any]:
        """Export complete real SQLite ledger state for the tactical monitoring console."""
        qual = self.get_qualification_status()
        markets_rows = self.conn.execute(
            """
            SELECT market_id, question, category, resolution_time_utc,
                   current_probability, bullets_used, max_bullets, last_updated_utc
            FROM market_quotas
            ORDER BY bullets_used DESC, resolution_time_utc ASC
            """
        ).fetchall()
        sub_rows = self.conn.execute(
            """
            SELECT submission_id, packet_id, market_id, wallet_address, bullet_slot,
                   submitted_at_utc, p_before, shadow_p_after, official_p_after,
                   verdict, verdict_rationale, stage1_reward_usdc, stage2_settlement_usdc,
                   api_latency_ms, attachment_count, fact_fingerprint_sha256,
                   explanatory_note, source_links_json, attachments_json
            FROM evidence_submissions
            ORDER BY submitted_at_utc DESC, bullet_slot DESC
            """
        ).fetchall()
        blocked_rows = self.conn.execute(
            """
            SELECT market_id, signal_id, attempted_at_utc, rejection_reason, abs_delta_p
            FROM blocked_attempts
            ORDER BY attempt_id DESC
            """
        ).fetchall()
        funnel_rows = self.conn.execute(
            """
            SELECT market_id, question, category, prior_p, resolution_time_utc,
                   eligible, rejection_reason, shannon_entropy_bits, in_entropy_sweet_spot,
                   dynamic_beta, two_stage_ev_usdc, priority_score
            FROM scanned_market_funnel
            ORDER BY rank_order ASC
            """
        ).fetchall()

        total_stage1 = sum(float(r["stage1_reward_usdc"]) for r in sub_rows)
        total_stage2 = sum(float(r["stage2_settlement_usdc"]) for r in sub_rows)

        return {
            "wallet_guard": {
                "canonical_wallet": self.wallet_guard.canonical_address,
                "delphi_wallet": self.wallet_guard.delphi_wallet_address,
                "api_bound_wallet": self.wallet_guard.api_bound_wallet_address,
                "dorahacks_wallet": self.wallet_guard.dorahacks_wallet_address,
                "sybil_lock_verified": True,
            },
            "qualification": {
                "distinct_judged_markets": qual.distinct_judged_markets,
                "min_markets_required": qual.min_markets_required,
                "total_judged_submissions": qual.total_judged_submissions,
                "min_judged_required": qual.min_judged_required,
                "is_qualified": qual.is_qualified,
            },
            "totals": {
                "stage1_reward_usdc": round(total_stage1, 2),
                "stage2_settlement_usdc": round(total_stage2, 2),
                "combined_usdc": round(total_stage1 + total_stage2, 2),
                "blocked_bad_shots": len(blocked_rows),
            },
            "market_rankings": [
                {
                    "market_id": r["market_id"],
                    "question": r["question"],
                    "category": r["category"],
                    "prior_p": round(float(r["prior_p"]), 4),
                    "resolution_time_utc": r["resolution_time_utc"],
                    "eligible": bool(r["eligible"]),
                    "rejection_reason": r["rejection_reason"],
                    "shannon_entropy_bits": round(float(r["shannon_entropy_bits"]), 4),
                    "in_entropy_sweet_spot": bool(r["in_entropy_sweet_spot"]),
                    "dynamic_beta": round(float(r["dynamic_beta"]), 2),
                    "two_stage_ev_usdc": round(float(r["two_stage_ev_usdc"]), 2),
                    "priority_score": round(float(r["priority_score"]), 2),
                }
                for r in funnel_rows
            ],
            "markets": [
                {
                    "market_id": r["market_id"],
                    "question": r["question"],
                    "category": r["category"],
                    "resolution_time_utc": r["resolution_time_utc"],
                    "current_probability": round(float(r["current_probability"]), 4),
                    "bullets_used": int(r["bullets_used"]),
                    "remaining_bullets": MAX_BULLETS_PER_MARKET - int(r["bullets_used"]),
                    "max_bullets": int(r["max_bullets"]),
                    "last_updated_utc": r["last_updated_utc"],
                }
                for r in markets_rows
            ],
            "submissions": [
                {
                    "submission_id": r["submission_id"],
                    "packet_id": r["packet_id"],
                    "market_id": r["market_id"],
                    "bullet_slot": int(r["bullet_slot"]),
                    "submitted_at_utc": r["submitted_at_utc"],
                    "p_before": round(float(r["p_before"]), 4),
                    "shadow_p_after": round(float(r["shadow_p_after"]), 4),
                    "official_p_after": round(float(r["official_p_after"]), 4),
                    "verdict": r["verdict"],
                    "verdict_rationale": r["verdict_rationale"],
                    "stage1_reward_usdc": round(float(r["stage1_reward_usdc"]), 2),
                    "stage2_settlement_usdc": round(float(r["stage2_settlement_usdc"]), 2),
                    "api_latency_ms": round(float(r["api_latency_ms"]), 1),
                    "attachment_count": int(r["attachment_count"]),
                    "fact_fingerprint_sha256": r["fact_fingerprint_sha256"],
                    "explanatory_note": r["explanatory_note"],
                    "source_links": json.loads(r["source_links_json"]),
                    "attachments": json.loads(r["attachments_json"]),
                }
                for r in sub_rows
            ],
            "blocked_attempts": [
                {
                    "market_id": r["market_id"],
                    "signal_id": r["signal_id"],
                    "attempted_at_utc": r["attempted_at_utc"],
                    "rejection_reason": r["rejection_reason"],
                    "abs_delta_p": round(float(r["abs_delta_p"]), 4),
                }
                for r in blocked_rows
            ],
        }

    def close(self) -> None:
        self.conn.close()
