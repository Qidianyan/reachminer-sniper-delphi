"""End-to-end backtest across real public GitHub Release propositions, TS bridge, and HTTP API."""

from __future__ import annotations

import json
from pathlib import Path
import threading
import urllib.request

from reach_miner.pipeline import run_backtest_and_export_artifacts
from reach_miner.server import create_tactical_server


def test_full_e2e_backtest_ts_bridge_and_tactical_server() -> None:
    code_dir = Path(__file__).resolve().parent.parent
    summary = run_backtest_and_export_artifacts(base_code_dir=code_dir)

    qual = summary["qualification"]
    assert qual.is_qualified is True
    assert qual.distinct_judged_markets == 5  # >= 3 required
    assert qual.total_judged_submissions == 12  # >= 10 required
    assert summary["committed_count"] == 12
    assert summary["blocked_count"] == 5

    # Verify exported snapshot file and $250 Developer Feedback Report
    snap_path = Path(summary["snapshot_js_path"])
    report_path = Path(summary["feedback_report_path"])
    db_path = Path(summary["db_path"])
    assert snap_path.is_file()
    assert report_path.is_file()
    assert db_path.is_file()

    report_md = report_path.read_text(encoding="utf-8")
    assert "arXiv:2606.07434" in report_md
    assert "@gensyn-ai/gensyn-delphi-sdk@2.1.0" in report_md
    assert "$250 USDC" in report_md

    # Spin up live Tactical HTTP server on ephemeral port 0 and test real SQLite endpoints
    srv = create_tactical_server(
        host="127.0.0.1",
        port=0,
        db_path=db_path,
        web_dir=code_dir / "web",
        canonical_wallet="0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed",
    )
    port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=5) as r_health:
            health = json.loads(r_health.read().decode("utf-8"))
            assert health == {"status": "ok", "ledger_exists": True}

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/dashboard", timeout=5) as r_dash:
            dash = json.loads(r_dash.read().decode("utf-8"))
            assert dash["qualification"]["is_qualified"] is True
            assert len(dash["submissions"]) == 12
            assert all(m["bullets_used"] <= 3 for m in dash["markets"])
            assert len(dash["market_rankings"]) == 7
            assert sum(1 for r in dash["market_rankings"] if not r["eligible"]) == 2
            assert len(dash["lmsr_curve"]) == 39

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/index.html", timeout=5) as r_html:
            html_text = r_html.read().decode("utf-8")
            assert "ReachMiner-Sniper" in html_text
    finally:
        srv.shutdown()
        srv.server_close()
