"""Unit tests for CiteCheckVerifier, ShadowJudge (|Δp| >= 5%), and QuotaSniper (<=3 bullets)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import pytest

from reach_miner.evidence_packager import EvidencePackager
from reach_miner.models import CandidateSignal, DelphiMarket
from reach_miner.quota_sniper import QuotaExceededError, QuotaSniper
from reach_miner.shadow_judge import ShadowJudge
from reach_miner.wallet_guard import SingleWalletGuard

WALLET = "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed"


def _make_market(prob: float = 0.48) -> DelphiMarket:
    return DelphiMarket(
        market_id="mkt_quota_test",
        question="Will repo X tag v2.0.0 before 2026-12-07 UTC?",
        category="open_source_release",
        current_probability=prob,
        resolution_time=datetime(2026, 12, 7, 0, 0, 0, tzinfo=timezone.utc),
    )


def _make_signal(
    sig_id: str,
    fact: str,
    quote: str,
    raw: str,
    authority: float = 0.96,
) -> CandidateSignal:
    return CandidateSignal(
        signal_id=sig_id,
        market_id="mkt_quota_test",
        observed_at_utc=datetime(2026, 11, 26, 12, 0, 0, tzinfo=timezone.utc),
        authoritative_entity="Repo X Maintainers",
        quantitative_fact=fact,
        verbatim_quote=quote,
        source_urls=("https://github.com/org/repo/releases",),
        raw_source_text=raw,
        structured_diff_payload={"id": sig_id},
        direction=1,
        authority_tier=authority,
        corroborating_sources_count=2,
    )


def test_citecheck_blocks_hallucinated_numbers_and_shadow_judge_blocks_low_shift() -> None:
    packager = EvidencePackager()
    judge = ShadowJudge(min_abs_delta_p=0.05)
    mkt = _make_market(0.50)

    # 1. Hallucinated metric (fact claims 95%, source says 60%)
    hallucinated = _make_signal(
        "sig_bad_num",
        fact="Passed 95% of integration benchmarks on 2026-11-26",
        quote="Passed 60% of integration benchmarks on 2026-11-26.",
        raw="CI Report: Passed 60% of integration benchmarks on 2026-11-26.",
    )
    pkt_bad = packager.package(hallucinated, WALLET)
    assert pkt_bad.cite_check.passed is False
    dec_bad = judge.evaluate(mkt, hallucinated, pkt_bad, bullets_used=0, existing_fingerprints=[])
    assert dec_bad.allow_fire is False
    assert dec_bad.rejection_reason is not None
    assert "CITECHECK_FAILED" in dec_bad.rejection_reason

    # 2. Weak rumor with |Δp| < 5%
    weak_sig = _make_signal(
        "sig_weak",
        fact="Opened 1 draft discussion on 2026-11-26",
        quote="Opened 1 draft discussion on 2026-11-26",
        raw="Forum log: Opened 1 draft discussion on 2026-11-26.",
        authority=0.15,
    )
    pkt_weak = packager.package(weak_sig, WALLET)
    dec_weak = judge.evaluate(mkt, weak_sig, pkt_weak, bullets_used=0, existing_fingerprints=[])
    assert dec_weak.allow_fire is False
    assert dec_weak.abs_delta_p < 0.05
    assert "INSUFFICIENT_BELIEF_SHIFT" in (dec_weak.rejection_reason or "")


def test_three_bullet_cap_and_duplicate_fact_guard(tmp_path: Path) -> None:
    db_file = tmp_path / "quota_test.db"
    guard = SingleWalletGuard.verify_and_lock(WALLET, WALLET, WALLET)
    sniper = QuotaSniper(db_path=db_file, wallet_guard=guard)
    packager = EvidencePackager()
    judge = ShadowJudge(min_abs_delta_p=0.05)
    mkt = _make_market(0.45)

    try:
        for i in range(1, 4):
            sig = _make_signal(
                f"sig_valid_{i}",
                fact=f"Published milestone artifact #{i} passing {80 + i}% suite checks",
                quote=f"Published milestone artifact #{i} passing {80 + i}% suite checks.",
                raw=f"Release log: Published milestone artifact #{i} passing {80 + i}% suite checks.",
            )
            pkt = packager.package(sig, WALLET)
            fps, notes = sniper.get_market_history(mkt.market_id)
            dec = judge.evaluate(
                mkt,
                sig,
                pkt,
                bullets_used=sniper.get_bullets_used(mkt.market_id),
                existing_fingerprints=fps,
                existing_notes=notes,
            )
            assert dec.allow_fire is True
            assert dec.abs_delta_p >= 0.05

            # Duplicate check right after Bullet #1
            if i == 1:
                sniper.commit_submission(
                    market=mkt,
                    packet=pkt,
                    decision=dec,
                    submission_id=f"sub_{i}",
                    official_p_after=dec.p_after,
                    verdict="ACCEPTED",
                    verdict_rationale="Verified",
                    stage1_reward_usdc=4.5,
                    stage2_settlement_usdc=12.0,
                    api_latency_ms=210.0,
                )
                fps_dup, notes_dup = sniper.get_market_history(mkt.market_id)
                dup_dec = judge.evaluate(
                    mkt, sig, pkt, bullets_used=1, existing_fingerprints=fps_dup, existing_notes=notes_dup
                )
                assert dup_dec.allow_fire is False
                assert dup_dec.rejection_reason == "DUPLICATE_FACT_ZERO_SCORE_GUARD"

                # Also verify paraphrased restatement of same numbers (#1, 81%) is blocked!
                paraphrased_sig = _make_signal(
                    "sig_paraphrase_1",
                    fact="Milestone artifact #1 published passing 81% suite checks",
                    quote="Published milestone artifact #1 passing 81% suite checks.",
                    raw="Release log: Published milestone artifact #1 passing 81% suite checks.",
                )
                paraphrased_pkt = packager.package(paraphrased_sig, WALLET)
                para_dec = judge.evaluate(
                    mkt,
                    paraphrased_sig,
                    paraphrased_pkt,
                    bullets_used=1,
                    existing_fingerprints=fps_dup,
                    existing_notes=notes_dup,
                )
                assert para_dec.allow_fire is False
                assert para_dec.rejection_reason == "DUPLICATE_FACT_ZERO_SCORE_GUARD"
            else:
                sniper.commit_submission(
                    market=mkt,
                    packet=pkt,
                    decision=dec,
                    submission_id=f"sub_{i}",
                    official_p_after=dec.p_after,
                    verdict="ACCEPTED",
                    verdict_rationale="Verified",
                    stage1_reward_usdc=4.5,
                    stage2_settlement_usdc=12.0,
                    api_latency_ms=210.0,
                )

        assert sniper.get_bullets_used(mkt.market_id) == 3
        assert sniper.get_remaining_bullets(mkt.market_id) == 0

        # 4th bullet MUST be rejected by both ShadowJudge AND QuotaSniper SQLite guard
        sig_4 = _make_signal(
            "sig_valid_4",
            fact="Published patch #4 passing 99% suite checks",
            quote="Published patch #4 passing 99% suite checks.",
            raw="Release log: Published patch #4 passing 99% suite checks.",
        )
        pkt_4 = packager.package(sig_4, WALLET)
        dec_4 = judge.evaluate(mkt, sig_4, pkt_4, bullets_used=3, existing_fingerprints=[])
        assert dec_4.allow_fire is False
        assert dec_4.rejection_reason == "MARKET_QUOTA_EXHAUSTED_MAX_3"

        # Even if someone bypasses ShadowJudge with a forged decision, QuotaSniper blocks >3 in SQLite
        forged_decision = dec  # allow_fire=True from earlier slot
        with pytest.raises(QuotaExceededError):
            sniper.commit_submission(
                market=mkt,
                packet=pkt_4,
                decision=forged_decision,
                submission_id="sub_4_illegal",
                official_p_after=0.90,
                verdict="ACCEPTED",
                verdict_rationale="Should never commit",
                stage1_reward_usdc=1.0,
                stage2_settlement_usdc=1.0,
                api_latency_ms=100.0,
            )
    finally:
        sniper.close()
