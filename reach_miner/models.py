"""Core strongly-typed domain models for ReachMiner-Sniper."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class DelphiMarket:
    """Represents an active or historical market on Gensyn Delphi."""

    market_id: str
    question: str
    category: str  # e.g., "open_source_release", "tech_milestone", "macro_policy", "crypto_protocol"
    current_probability: float  # Forecaster belief p in (0, 1)
    resolution_time: datetime  # UTC timestamp
    liquidity_beta_base: float = 100.0
    accumulated_evidence_quality: float = 0.0
    last_evidence_updated_at: datetime | None = None
    primary_sensor_type: str = "github_release"
    primary_sensor_target: str = ""
    status: str = "OPEN"


@dataclass(frozen=True)
class MarketRankEntry:
    """Actuarial evaluation of a Delphi market under arXiv:2606.07434."""

    market: DelphiMarket
    eligible: bool
    rejection_reason: str | None
    shannon_entropy_bits: float
    in_entropy_sweet_spot: bool
    dynamic_beta: float
    expected_kl_gain: float
    two_stage_ev_usdc: float
    staleness_hours: float
    priority_score: float


@dataclass(frozen=True)
class CandidateSignal:
    """Primary-source signal captured by agent-reach / primary sensor."""

    signal_id: str
    market_id: str
    observed_at_utc: datetime
    authoritative_entity: str
    quantitative_fact: str
    verbatim_quote: str
    source_urls: tuple[str, ...]
    raw_source_text: str
    structured_diff_payload: dict[str, Any]
    direction: int  # +1 supports YES outcome, -1 supports NO outcome
    authority_tier: float  # in [0.0, 1.0], e.g. 0.98 for signed GitHub release / SEC filing
    corroborating_sources_count: int = 2


@dataclass(frozen=True)
class AttachmentFile:
    """Supporting file attached to a Delphi Evidence Mining submission (max 3)."""

    filename: str
    media_type: str
    content_text: str
    sha256_hex: str
    size_bytes: int


@dataclass(frozen=True)
class CiteCheckReport:
    """Deterministic character-level verification result."""

    passed: bool
    quote_verified: bool
    quote_char_offset: int
    quantitative_tokens_verified: bool
    missing_tokens: tuple[str, ...]
    raw_source_sha256: str
    failure_reason: str | None = None


@dataclass(frozen=True)
class EvidencePacket:
    """Formatted objective evidence packet ready for ShadowJudge & Delphi submission."""

    packet_id: str
    market_id: str
    wallet_address: str
    explanatory_note: str
    source_links: tuple[str, ...]
    attachments: tuple[AttachmentFile, ...]
    fact_fingerprint_sha256: str
    created_at_utc: str
    cite_check: CiteCheckReport


@dataclass(frozen=True)
class ShadowJudgeDecision:
    """Local pre-submission evaluation predicting belief shift and checking gates."""

    allow_fire: bool
    p_before: float
    p_after: float
    delta_p: float
    abs_delta_p: float
    expected_lmsr_payoff: float
    is_novel_fact: bool
    cite_check_passed: bool
    remaining_bullets_before: int
    recommended_slot: str
    rejection_reason: str | None = None


@dataclass(frozen=True)
class QualificationStatus:
    """Tracks DoraHacks leaderboard minimum qualifying threshold (>=3 markets, >=10 judged)."""

    distinct_judged_markets: int
    total_judged_submissions: int
    min_markets_required: int = 3
    min_judged_required: int = 10

    @property
    def is_qualified(self) -> bool:
        return (
            self.distinct_judged_markets >= self.min_markets_required
            and self.total_judged_submissions >= self.min_judged_required
        )


@dataclass(frozen=True)
class JudgedSubmissionRecord:
    """Persisted record of a submitted evidence packet and Delphi verdict."""

    submission_id: str
    packet_id: str
    market_id: str
    wallet_address: str
    bullet_slot: int  # 1, 2, or 3
    submitted_at_utc: str
    p_before: float
    shadow_p_after: float
    official_p_after: float
    verdict: str  # "ACCEPTED" | "REJECTED" | "PENDING"
    verdict_rationale: str
    stage1_reward_usdc: float
    stage2_settlement_usdc: float
    api_latency_ms: float
    attachment_count: int
    fact_fingerprint_sha256: str
    explanatory_note: str = ""
    attachments_meta: list[dict[str, Any]] = field(default_factory=list)
