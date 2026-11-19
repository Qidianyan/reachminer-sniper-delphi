"""MarketSelector: Actuarial Market Funnel based on arXiv:2606.07434 (Evidence Markets)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Iterable

from .models import DelphiMarket, MarketRankEntry

DEFAULT_RESOLUTION_CUTOFF_UTC = datetime(2026, 12, 10, 0, 0, 0, tzinfo=timezone.utc)

# Primary sensor verifiability weights: machine-verifiable primary sources beat media aggregators
SENSOR_VERIFIABILITY_WEIGHTS: dict[str, float] = {
    "github_release": 1.25,
    "regulatory_filing": 1.22,
    "onchain_governance": 1.20,
    "official_benchmark_json": 1.18,
    "livestream_transcript": 1.12,
    "general_web": 0.75,
}

CATEGORY_LONG_TAIL_WEIGHTS: dict[str, float] = {
    "open_source_release": 1.20,
    "ai_model_benchmark": 1.18,
    "crypto_protocol": 1.15,
    "macro_policy": 1.12,
    "tech_milestone": 1.15,
    "general": 0.90,
}


def shannon_entropy_bits(probability: float) -> float:
    """Compute binary Shannon entropy H(p) in [0.0, 1.0] bits."""
    p = min(max(probability, 1e-9), 1.0 - 1e-9)
    return -(p * math.log2(p) + (1.0 - p) * math.log2(1.0 - p))


def dynamic_liquidity_beta(beta_base: float, accumulated_quality: float, gamma: float = 0.35) -> float:
    """Compute dynamic liquidity parameter beta(Q_E) per arXiv:2606.07434."""
    q = max(0.0, accumulated_quality)
    return beta_base * (1.0 + gamma * math.log1p(q))


def lmsr_kl_information_gain(p_prior: float, p_posterior: float) -> float:
    """Compute expected sequential LMSR log-payoff normalized by beta: KL(p_posterior || p_prior)."""
    p0 = min(max(p_prior, 1e-6), 1.0 - 1e-6)
    p1 = min(max(p_posterior, 1e-6), 1.0 - 1e-6)
    return p1 * math.log(p1 / p0) + (1.0 - p1) * math.log((1.0 - p1) / (1.0 - p0))


def lmsr_sequential_payoff(
    p_prior: float,
    p_submitted: float,
    realized_outcome: int,
    beta: float,
) -> float:
    """Exact Definition 5 sequential LMSR payoff from Hossain et al. (arXiv:2606.07434)."""
    p0 = min(max(p_prior, 1e-6), 1.0 - 1e-6)
    p1 = min(max(p_submitted, 1e-6), 1.0 - 1e-6)
    if realized_outcome == 1:
        return beta * (math.log(p1) - math.log(p0))
    if realized_outcome == 0:
        return beta * (math.log(1.0 - p1) - math.log(1.0 - p0))
    raise ValueError(f"realized_outcome must be 0 or 1, got {realized_outcome}")


@dataclass(frozen=True)
class MarketSelectionConfig:
    """Configuration for filtering and ranking Delphi markets."""

    resolution_cutoff_utc: datetime = DEFAULT_RESOLUTION_CUTOFF_UTC
    sweet_spot_min_p: float = 0.30
    sweet_spot_max_p: float = 0.70
    min_actionable_p: float = 0.05
    max_actionable_p: float = 0.95
    reference_belief_shift: float = 0.15
    gamma_liquidity: float = 0.35


class MarketSelector:
    """Filters markets by settlement deadline <= 2026-12-10T00:00:00Z and ranks by LMSR entropy EV."""

    def __init__(self, config: MarketSelectionConfig | None = None) -> None:
        self.config = config or MarketSelectionConfig()

    def evaluate_market(self, market: DelphiMarket, as_of_utc: datetime) -> MarketRankEntry:
        """Evaluate a single market's eligibility, LMSR entropy, and expected two-stage value."""
        if as_of_utc.tzinfo is None:
            as_of_utc = as_of_utc.replace(tzinfo=timezone.utc)
        res_utc = (
            market.resolution_time
            if market.resolution_time.tzinfo is not None
            else market.resolution_time.replace(tzinfo=timezone.utc)
        )

        p = market.current_probability
        entropy = shannon_entropy_bits(p)
        in_sweet_spot = self.config.sweet_spot_min_p <= p <= self.config.sweet_spot_max_p
        beta_dyn = dynamic_liquidity_beta(
            market.liquidity_beta_base,
            market.accumulated_evidence_quality,
            gamma=self.config.gamma_liquidity,
        )

        # Estimate symmetric expected KL gain for a high-conviction primary signal shifting |Δp|
        shift = self.config.reference_belief_shift
        p_up = min(0.99, p + shift)
        p_down = max(0.01, p - shift)
        expected_kl = 0.5 * (
            lmsr_kl_information_gain(p, p_up) + lmsr_kl_information_gain(p, p_down)
        )

        if market.last_evidence_updated_at is not None:
            last_upd = (
                market.last_evidence_updated_at
                if market.last_evidence_updated_at.tzinfo is not None
                else market.last_evidence_updated_at.replace(tzinfo=timezone.utc)
            )
            staleness_hours = max(0.0, (as_of_utc - last_upd).total_seconds() / 3600.0)
        else:
            staleness_hours = 48.0

        # Eligibility checks
        rejection_reason: str | None = None
        if market.status.upper() != "OPEN":
            rejection_reason = f"MARKET_NOT_OPEN:{market.status}"
        elif res_utc <= as_of_utc:
            rejection_reason = "MARKET_ALREADY_EXPIRED"
        elif res_utc > self.config.resolution_cutoff_utc:
            rejection_reason = (
                f"RESOLUTION_AFTER_CUTOFF:{res_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}"
                f">{self.config.resolution_cutoff_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}"
            )
        elif not (self.config.min_actionable_p <= p <= self.config.max_actionable_p):
            rejection_reason = f"EXTREME_CERTAINTY_LOW_MARGINAL_GAIN:p={p:.3f}"

        eligible = rejection_reason is None
        days_to_res = max(0.25, (res_utc - as_of_utc).total_seconds() / 86400.0)
        settlement_velocity_bonus = 1.0 + min(0.35, 3.0 / (days_to_res + 2.0))
        staleness_multiplier = 1.0 + min(0.40, math.log1p(staleness_hours) / 10.0)
        sensor_weight = SENSOR_VERIFIABILITY_WEIGHTS.get(market.primary_sensor_type, 0.85)
        category_weight = CATEGORY_LONG_TAIL_WEIGHTS.get(market.category, 0.95)
        sweet_spot_multiplier = 1.45 if in_sweet_spot else 0.75

        # Stage 1 immediate shift EV + Stage 2 REE terminal settlement EV
        two_stage_ev = beta_dyn * expected_kl * settlement_velocity_bonus
        priority_score = (
            two_stage_ev
            * entropy
            * sweet_spot_multiplier
            * staleness_multiplier
            * sensor_weight
            * category_weight
            if eligible
            else 0.0
        )

        return MarketRankEntry(
            market=market,
            eligible=eligible,
            rejection_reason=rejection_reason,
            shannon_entropy_bits=round(entropy, 6),
            in_entropy_sweet_spot=in_sweet_spot,
            dynamic_beta=round(beta_dyn, 4),
            expected_kl_gain=round(expected_kl, 6),
            two_stage_ev_usdc=round(two_stage_ev, 4),
            staleness_hours=round(staleness_hours, 2),
            priority_score=round(priority_score, 4),
        )

    def select_and_rank(
        self,
        markets: Iterable[DelphiMarket],
        as_of_utc: datetime,
        only_eligible: bool = True,
    ) -> list[MarketRankEntry]:
        """Filter and rank markets in descending order of sweet-spot tier and priority score."""
        evaluated = [self.evaluate_market(m, as_of_utc=as_of_utc) for m in markets]
        if only_eligible:
            evaluated = [entry for entry in evaluated if entry.eligible]
        evaluated.sort(
            key=lambda e: (
                1 if e.eligible else 0,
                1 if e.in_entropy_sweet_spot else 0,
                e.priority_score,
                e.shannon_entropy_bits,
            ),
            reverse=True,
        )
        return evaluated

    def generate_lmsr_curve_points(
        self,
        beta_base: float = 100.0,
        accumulated_quality: float = 2.0,
        delta_p: float = 0.15,
        steps: int = 39,
    ) -> list[dict[str, float | bool]]:
        """Generate exact LMSR entropy & information gain curve points across p in [0.05, 0.95]."""
        beta_dyn = dynamic_liquidity_beta(beta_base, accumulated_quality, self.config.gamma_liquidity)
        points: list[dict[str, float | bool]] = []
        for idx in range(steps):
            p = round(0.05 + idx * (0.90 / (steps - 1)), 4)
            entropy = shannon_entropy_bits(p)
            p_post = min(0.99, p + delta_p) if p <= 0.5 else max(0.01, p - delta_p)
            kl_gain = lmsr_kl_information_gain(p, p_post)
            expected_payoff = beta_dyn * kl_gain * entropy
            points.append(
                {
                    "p": p,
                    "entropy_bits": round(entropy, 4),
                    "kl_gain": round(kl_gain, 5),
                    "expected_payoff_usdc": round(expected_payoff, 4),
                    "in_sweet_spot": self.config.sweet_spot_min_p <= p <= self.config.sweet_spot_max_p,
                }
            )
        return points
