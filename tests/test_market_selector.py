"""Unit tests for MarketSelector (arXiv:2606.07434 LMSR entropy & settlement cutoff)."""

from __future__ import annotations

from datetime import datetime, timezone
import math

from reach_miner.market_selector import (
    MarketSelector,
    dynamic_liquidity_beta,
    lmsr_sequential_payoff,
    shannon_entropy_bits,
)
from reach_miner.models import DelphiMarket


def test_settlement_cutoff_boundary_2026_12_10() -> None:
    as_of = datetime(2026, 11, 24, 0, 0, 0, tzinfo=timezone.utc)
    selector = MarketSelector()

    exact_cutoff_mkt = DelphiMarket(
        market_id="mkt_exact_cutoff",
        question="Exact cutoff market",
        category="open_source_release",
        current_probability=0.50,
        resolution_time=datetime(2026, 12, 10, 0, 0, 0, tzinfo=timezone.utc),
    )
    one_sec_late_mkt = DelphiMarket(
        market_id="mkt_one_sec_late",
        question="One second past cutoff market",
        category="open_source_release",
        current_probability=0.50,
        resolution_time=datetime(2026, 12, 10, 0, 0, 1, tzinfo=timezone.utc),
    )

    eval_ok = selector.evaluate_market(exact_cutoff_mkt, as_of_utc=as_of)
    eval_late = selector.evaluate_market(one_sec_late_mkt, as_of_utc=as_of)

    assert eval_ok.eligible is True
    assert eval_ok.rejection_reason is None
    assert eval_late.eligible is False
    assert eval_late.rejection_reason is not None
    assert "RESOLUTION_AFTER_CUTOFF" in eval_late.rejection_reason


def test_lmsr_entropy_sweet_spot_ranking() -> None:
    as_of = datetime(2026, 11, 24, 0, 0, 0, tzinfo=timezone.utc)
    selector = MarketSelector()

    assert math.isclose(shannon_entropy_bits(0.50), 1.0, rel_tol=1e-6)
    assert shannon_entropy_bits(0.48) > shannon_entropy_bits(0.85)

    sweet_mkt = DelphiMarket(
        market_id="mkt_sweet",
        question="High uncertainty open-source release",
        category="open_source_release",
        current_probability=0.48,
        resolution_time=datetime(2026, 12, 5, 0, 0, 0, tzinfo=timezone.utc),
    )
    off_sweet_mkt = DelphiMarket(
        market_id="mkt_offsweet",
        question="Low uncertainty market",
        category="open_source_release",
        current_probability=0.84,
        resolution_time=datetime(2026, 12, 5, 0, 0, 0, tzinfo=timezone.utc),
    )
    extreme_mkt = DelphiMarket(
        market_id="mkt_extreme",
        question="Priced-in 98% market",
        category="open_source_release",
        current_probability=0.98,
        resolution_time=datetime(2026, 12, 5, 0, 0, 0, tzinfo=timezone.utc),
    )

    ranked = selector.select_and_rank(
        [off_sweet_mkt, extreme_mkt, sweet_mkt],
        as_of_utc=as_of,
        only_eligible=True,
    )
    assert [r.market.market_id for r in ranked] == ["mkt_sweet", "mkt_offsweet"]
    assert ranked[0].in_entropy_sweet_spot is True
    assert ranked[1].in_entropy_sweet_spot is False


def test_arxiv_2606_07434_definition5_lmsr_payoff() -> None:
    beta_low = dynamic_liquidity_beta(100.0, accumulated_quality=0.0)
    beta_high = dynamic_liquidity_beta(100.0, accumulated_quality=5.0)
    assert beta_high > beta_low == 100.0

    # Moving belief toward realized outcome 1 earns strictly positive payoff
    gain = lmsr_sequential_payoff(0.45, 0.72, realized_outcome=1, beta=beta_high)
    # Moving belief away from realized outcome 1 incurs negative payoff (proper scoring rule)
    loss = lmsr_sequential_payoff(0.45, 0.25, realized_outcome=1, beta=beta_high)
    assert gain > 0.0
    assert loss < 0.0
