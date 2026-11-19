"""CLI entry point for ReachMiner-Sniper (`python3 -m reach_miner`)."""

from __future__ import annotations

import json

from .pipeline import run_backtest_and_export_artifacts


def main() -> None:
    summary = run_backtest_and_export_artifacts()
    print(json.dumps(summary, default=str, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
