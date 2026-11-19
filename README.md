# ReachMiner-Sniper (`Qidianyan/reachminer-sniper-delphi`)

**Dual-Stack (TypeScript `@gensyn-ai/gensyn-delphi-sdk@2.1.0` + Python) Primary-Source Evidence Mining Agent for Gensyn × Delphi Evidence Markets (`arXiv:2606.07434`)**

Built for **Agent Arena Competition: Evidence Mining (Gensyn × Delphi on DoraHacks)** — engineered around the mechanism design of Safwan Hossain, Gabriel Passamani Andrade, Chengqi Zang, and Yiling Chen (*"Evidence Markets"*, `arXiv:2606.07434`).

---

## Core Architecture & Anti-Disqualification Guardrails

1. **Single-Wallet Identity Lock (`ts_gateway/src/singleWalletGuard.ts` & `reach_miner/wallet_guard.py`)**
   - Enforces strict EIP-55 checksum verification (`viem` in TypeScript + zero-dependency Ethereum `Keccak-256` in Python) and guarantees `DELPHI_WALLET_ADDRESS == DELPHI_API_BOUND_WALLET == DORAHACKS_BUIDL_WALLET`.
   - Writes an immutable SQLite singleton record (`wallet_identity_lock`) that aborts immediately if a mismatched wallet is ever supplied, preventing Sybil disqualification.

2. **Official Delphi SDK v2.1.0 TypeScript Protocol Gateway (`ts_gateway/`)**
   - Directly integrates `@gensyn-ai/gensyn-delphi-sdk@2.1.0` (`DelphiClient`, `Market`, Chain ID `685685` / `685689`), injecting `X-Delphi-Mode: competition` and `X-API-Key` headers, computing canonical `Keccak-256` packet commitments, and enforcing the hard `<= 3` supporting attachment limit.

3. **Resolution-Cutoff & Shannon-Entropy Market Funnel (`reach_miner/market_selector.py`)**
   - Filters strictly for `resolution_time <= 2026-12-10T00:00:00Z` (leaving `>= 41 hours` before the `2026-12-11 17:00 UTC` leaderboard cutoff for Gensyn REE oracle finality to capture Stage-2 settlement payoffs).
   - Ranks candidate markets by Shannon entropy sweet spot (`0.30 <= p <= 0.70`) and Definition 5 dynamic liquidity parameter `beta(Q_E)` expected KL belief-shift gain.

4. **Deterministic `CiteCheck` + Log-Odds `ShadowJudge` + 5-Gate Pre-Flight Filter (`reach_miner/evidence_packager.py`, `shadow_judge.py`, `quota_sniper.py`)**
   - **Zero-Inducement Formatting**: Rejects prompt-injection or judge-manipulation language (`JudgeInducementViolationError`) and generates 3 SHA-256 verified clean attachments (`01_primary_source_snapshot.md`, `02_structured_diff_extract.json`, `03_sha256_provenance_manifest.json`).
   - **Character-Offset `CiteCheck`**: Verifies verbatim primary-source quote offsets and numeric/version tokens 100% against raw primary source snapshots.
   - **SQLite 3-Bullet Hard State Machine**: Enforces `CHECK (bullets_used >= 0 AND bullets_used <= 3)` and `UNIQUE(market_id, bullet_slot)` at the database constraint layer.

5. **Zero-Mock Real-Time Tactical Console (`reach_miner/server.py` & `web/`)**
   - Reads directly from SQLite (`data/miner_ledger.db`) to visualize 3-bullet market magazines, LMSR information-gain payoff curves, verified 3-attachment evidence packets, and pre-flight blocked attempts.

---

## Verified Backtest & Dual-Stack Test Metrics

| Metric | Verified Result |
| :--- | :--- |
| **TypeScript SDK Gateway (`tsc --noEmit` + `node --test`)** | `5 / 5 PASS` (`@gensyn-ai/gensyn-delphi-sdk@2.1.0`) |
| **Python Full Test Suite (`pytest tests -v`)** | `21 / 21 PASS` |
| **Qualifying Submissions (`<= 3` bullets/market)** | `12` accepted submissions across `5` eligible markets (`100.0%` acceptance) |
| **Pre-Flight Blocked Low-Value / Unsafe Attempts** | `5` intercepted (`CiteCheck`, duplicate fact, low belief shift, judge inducement, 4th-bullet overflow) |
| **ShadowJudge Calibration Error (`MAE`)** | `0.0064` (mean belief shift `|Δp| = 17.96%`) |
| **Two-Stage Backtest Payoff** | `$222.79 USDC` (`$74.84` Stage-1 + `$147.95` Stage-2) |
| **Live GitHub Release Primary Sensor Probe** | `astral-sh/uv` verified via `CiteCheck` (`passed=True`, exact quote offset) |

---

## Quickstart & Verification

```bash
# 1. Install & run TypeScript SDK v2.1.0 gateway typecheck + tests
npm --prefix ts_gateway install
npm --prefix ts_gateway run typecheck && npm --prefix ts_gateway test

# 2. Run Python full unit tests, backtest & UI/anti-fraud audit
PYTHONPATH=. python3 -m pytest tests -v

# 3. Export telemetry report & launch local Tactical Console (http://127.0.0.1:8765)
cp .env.example .env  # fill runtime credentials via environment variables (never commit .env!)
PYTHONPATH=. python3 -m reach_miner.server --port 8765
```

See [docs/Delphi_Evidence_Markets_API_Telemetry_Report.md](docs/Delphi_Evidence_Markets_API_Telemetry_Report.md) for the full `@gensyn-ai/gensyn-delphi-sdk@2.1.0` source audit and latency telemetry report.

## License

Apache License 2.0 — see [LICENSE](LICENSE).
