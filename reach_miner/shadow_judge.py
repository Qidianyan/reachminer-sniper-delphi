"""CiteCheckVerifier & ShadowJudge: Deterministic Quote Check and Belief-Shift Gate."""

from __future__ import annotations

import hashlib
import math
import re
from typing import Sequence

from .market_selector import dynamic_liquidity_beta, lmsr_kl_information_gain
from .models import (
    CandidateSignal,
    CiteCheckReport,
    DelphiMarket,
    EvidencePacket,
    ShadowJudgeDecision,
)

# Extracts numbers, percentages, semantic versions (v1.2.3), ISO dates, hex commit prefixes
_QUANT_TOKEN_RE = re.compile(
    r"(?:v?\d+\.\d+(?:\.\d+)?(?:-[a-zA-Z0-9.]+)?|\d{4}-\d{2}-\d{2}|\b\d+(?:\.\d+)?%?|\$[0-9,]+(?:\.\d+)?)"
)
_WORD_TOKEN_RE = re.compile(r"[a-z0-9_.\-]+")


def _normalize_ws(text: str) -> str:
    return " ".join(text.split())


class CiteCheckVerifier:
    """Deterministic character-level quote & quantitative token verifier (zero hallucination)."""

    def verify(self, signal: CandidateSignal) -> CiteCheckReport:
        raw_bytes = signal.raw_source_text.encode("utf-8")
        raw_sha256 = hashlib.sha256(raw_bytes).hexdigest()

        quote = signal.verbatim_quote.strip()
        if not quote:
            return CiteCheckReport(
                passed=False,
                quote_verified=False,
                quote_char_offset=-1,
                quantitative_tokens_verified=False,
                missing_tokens=(),
                raw_source_sha256=raw_sha256,
                failure_reason="EMPTY_VERBATIM_QUOTE",
            )

        # 1. Direct substring match first, fallback to whitespace-normalized match
        offset = signal.raw_source_text.find(quote)
        if offset < 0:
            norm_raw = _normalize_ws(signal.raw_source_text)
            norm_quote = _normalize_ws(quote)
            offset = norm_raw.find(norm_quote)

        quote_verified = offset >= 0

        # 2. Every quantitative token in quantitative_fact must appear in raw_source_text
        raw_norm_lower = _normalize_ws(signal.raw_source_text).lower()
        tokens = _QUANT_TOKEN_RE.findall(signal.quantitative_fact)
        missing: list[str] = []
        for tok in tokens:
            if tok.lower() not in raw_norm_lower:
                missing.append(tok)

        quant_ok = len(missing) == 0
        passed = quote_verified and quant_ok
        failure_reason: str | None = None
        if not quote_verified:
            failure_reason = "VERBATIM_QUOTE_NOT_IN_PRIMARY_SOURCE"
        elif not quant_ok:
            failure_reason = f"UNVERIFIED_QUANTITATIVE_TOKENS:{','.join(missing)}"

        return CiteCheckReport(
            passed=passed,
            quote_verified=quote_verified,
            quote_char_offset=offset,
            quantitative_tokens_verified=quant_ok,
            missing_tokens=tuple(missing),
            raw_source_sha256=raw_sha256,
            failure_reason=failure_reason,
        )


def _extract_core_fact_clause(note: str) -> str:
    """Strip [UTC] [Entity] prefix and trailing Verbatim Primary Excerpt wrapper."""
    core = note.split("| Verbatim Primary Excerpt:", 1)[0].strip()
    # Strip leading bracketed [UTC] and [Entity] headers
    core = re.sub(r"^(?:\[[^\]]+\]\s*){1,2}", "", core)
    return core.strip()


def _is_redundant_fact(note_a: str, note_b: str, threshold: float) -> bool:
    """Detect duplicate or paraphrased restatements of the same quantitative event."""
    clause_a = _extract_core_fact_clause(note_a)
    clause_b = _extract_core_fact_clause(note_b)
    set_a = set(_WORD_TOKEN_RE.findall(clause_a.lower()))
    set_b = set(_WORD_TOKEN_RE.findall(clause_b.lower()))
    if not set_a or not set_b:
        return False

    jaccard = len(set_a & set_b) / len(set_a | set_b)
    if jaccard >= threshold:
        quant_a = {q.lower() for q in _QUANT_TOKEN_RE.findall(clause_a)}
        quant_b = {q.lower() for q in _QUANT_TOKEN_RE.findall(clause_b)}
        # Distinct quantitative milestones (e.g., rc1 -> rc2 or 81% -> 82%) are sequential updates, not duplicates
        if quant_a and quant_b and quant_a != quant_b:
            return False
        return True
    return False


SLOT_NAMES = {
    1: "SLOT_1_FIRST_MOVER_BREAKTHROUGH",
    2: "SLOT_2_CORROBORATED_CONFIRMATION",
    3: "SLOT_3_TERMINAL_SETTLEMENT_ANCHOR",
}


class ShadowJudge:
    """Local pre-submission judge predicting |Δp| and blocking low-impact or duplicate bullets."""

    def __init__(
        self,
        min_abs_delta_p: float = 0.05,
        max_bullets_per_market: int = 3,
        duplicate_jaccard_threshold: float = 0.78,
        base_log_odds_impulse: float = 1.15,
    ) -> None:
        self.min_abs_delta_p = min_abs_delta_p
        self.max_bullets_per_market = max_bullets_per_market
        self.duplicate_jaccard_threshold = duplicate_jaccard_threshold
        self.base_log_odds_impulse = base_log_odds_impulse

    def evaluate(
        self,
        market: DelphiMarket,
        signal: CandidateSignal,
        packet: EvidencePacket,
        bullets_used: int,
        existing_fingerprints: Sequence[str],
        existing_notes: Sequence[str] = (),
    ) -> ShadowJudgeDecision:
        """Simulate Delphi LLM-as-a-Judge belief update before spending a precious bullet."""
        remaining_before = max(0, self.max_bullets_per_market - bullets_used)
        next_slot_num = min(self.max_bullets_per_market, bullets_used + 1)
        slot_label = SLOT_NAMES.get(next_slot_num, "SLOT_EXHAUSTED")
        p_before = min(max(market.current_probability, 0.005), 0.995)

        if remaining_before <= 0:
            return ShadowJudgeDecision(
                allow_fire=False,
                p_before=round(p_before, 6),
                p_after=round(p_before, 6),
                delta_p=0.0,
                abs_delta_p=0.0,
                expected_lmsr_payoff=0.0,
                is_novel_fact=False,
                cite_check_passed=packet.cite_check.passed,
                remaining_bullets_before=0,
                recommended_slot="QUOTA_EXHAUSTED",
                rejection_reason="MARKET_QUOTA_EXHAUSTED_MAX_3",
            )

        if not packet.cite_check.passed:
            return ShadowJudgeDecision(
                allow_fire=False,
                p_before=round(p_before, 6),
                p_after=round(p_before, 6),
                delta_p=0.0,
                abs_delta_p=0.0,
                expected_lmsr_payoff=0.0,
                is_novel_fact=True,
                cite_check_passed=False,
                remaining_bullets_before=remaining_before,
                recommended_slot=slot_label,
                rejection_reason=f"CITECHECK_FAILED:{packet.cite_check.failure_reason}",
            )

        # Deduplication check: exact SHA-256 fingerprint + semantic/quantitative redundancy check
        is_novel = packet.fact_fingerprint_sha256 not in set(existing_fingerprints)
        if is_novel:
            for prev_note in existing_notes:
                if _is_redundant_fact(packet.explanatory_note, prev_note, self.duplicate_jaccard_threshold):
                    is_novel = False
                    break

        if not is_novel:
            return ShadowJudgeDecision(
                allow_fire=False,
                p_before=round(p_before, 6),
                p_after=round(p_before, 6),
                delta_p=0.0,
                abs_delta_p=0.0,
                expected_lmsr_payoff=0.0,
                is_novel_fact=False,
                cite_check_passed=True,
                remaining_bullets_before=remaining_before,
                recommended_slot=slot_label,
                rejection_reason="DUPLICATE_FACT_ZERO_SCORE_GUARD",
            )

        # Dual-blind Bayesian log-odds update
        direction = 1.0 if signal.direction >= 0 else -1.0
        authority = min(max(signal.authority_tier, 0.0), 1.0)
        corroboration_mult = min(1.30, 0.75 + 0.20 * max(1, signal.corroborating_sources_count))
        attachment_mult = 1.0 + 0.05 * len(packet.attachments)  # 3 clean attachments boost judge parse confidence

        # Surprise / non-priced-in factor: confirming a 96% market yields tiny shift; reversing or resolving 50% yields large shift
        alignment_gap = (1.0 - p_before) if direction > 0 else p_before
        surprise_mult = 0.65 + 0.70 * alignment_gap

        delta_log_odds = (
            direction
            * self.base_log_odds_impulse
            * (authority ** 1.4)
            * corroboration_mult
            * attachment_mult
            * surprise_mult
        )
        prior_log_odds = math.log(p_before / (1.0 - p_before))
        post_log_odds = prior_log_odds + delta_log_odds
        p_after = 1.0 / (1.0 + math.exp(-post_log_odds))
        delta_p = p_after - p_before
        abs_delta_p = abs(delta_p)

        beta_dyn = dynamic_liquidity_beta(
            market.liquidity_beta_base,
            market.accumulated_evidence_quality,
        )
        expected_payoff = beta_dyn * lmsr_kl_information_gain(p_before, p_after)

        if abs_delta_p < self.min_abs_delta_p:
            return ShadowJudgeDecision(
                allow_fire=False,
                p_before=round(p_before, 6),
                p_after=round(p_after, 6),
                delta_p=round(delta_p, 6),
                abs_delta_p=round(abs_delta_p, 6),
                expected_lmsr_payoff=round(expected_payoff, 4),
                is_novel_fact=True,
                cite_check_passed=True,
                remaining_bullets_before=remaining_before,
                recommended_slot=slot_label,
                rejection_reason=(
                    f"INSUFFICIENT_BELIEF_SHIFT:|Δp|={abs_delta_p:.4f}<{self.min_abs_delta_p:.4f}"
                ),
            )

        return ShadowJudgeDecision(
            allow_fire=True,
            p_before=round(p_before, 6),
            p_after=round(p_after, 6),
            delta_p=round(delta_p, 6),
            abs_delta_p=round(abs_delta_p, 6),
            expected_lmsr_payoff=round(expected_payoff, 4),
            is_novel_fact=True,
            cite_check_passed=True,
            remaining_bullets_before=remaining_before,
            recommended_slot=slot_label,
            rejection_reason=None,
        )
