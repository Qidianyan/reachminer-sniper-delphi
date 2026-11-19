"""Local Zero-Mock Tactical Monitoring HTTP Server reading directly from miner_ledger.db."""

from __future__ import annotations

import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import urlparse

from .feedback_exporter import FeedbackTelemetryExporter
from .market_selector import MarketSelector
from .quota_sniper import QuotaSniper
from .wallet_guard import SingleWalletGuard


def create_tactical_server(
    host: str,
    port: int,
    db_path: Path,
    web_dir: Path,
    canonical_wallet: str,
) -> ThreadingHTTPServer:
    """Create a ThreadingHTTPServer serving code/web/ and live SQLite JSON endpoints."""
    selector = MarketSelector()

    class TacticalRequestHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(web_dir), **kwargs)

        def _send_json(self, status_code: int, payload: dict) -> None:
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/api/health":
                self._send_json(200, {"status": "ok", "ledger_exists": db_path.is_file()})
                return
            if parsed.path == "/api/dashboard":
                guard = SingleWalletGuard.verify_and_lock(
                    canonical_wallet, canonical_wallet, canonical_wallet
                )
                sniper = QuotaSniper(db_path=db_path, wallet_guard=guard)
                try:
                    snap = sniper.export_dashboard_snapshot()
                    snap["lmsr_curve"] = selector.generate_lmsr_curve_points()
                    self._send_json(200, snap)
                finally:
                    sniper.close()
                return
            if parsed.path == "/api/feedback-metrics":
                guard = SingleWalletGuard.verify_and_lock(
                    canonical_wallet, canonical_wallet, canonical_wallet
                )
                sniper = QuotaSniper(db_path=db_path, wallet_guard=guard)
                try:
                    metrics = FeedbackTelemetryExporter(sniper.conn).compute_metrics()
                    self._send_json(200, metrics)
                finally:
                    sniper.close()
                return
            super().do_GET()

        def log_message(self, fmt: str, *args) -> None:
            return

    return ThreadingHTTPServer((host, port), TacticalRequestHandler)


def main() -> None:
    parser = argparse.ArgumentParser(description="ReachMiner-Sniper Tactical Console Server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--db",
        default=str(Path(__file__).resolve().parent.parent / "data" / "miner_ledger.db"),
    )
    parser.add_argument(
        "--wallet",
        default="0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed",
    )
    args = parser.parse_args()
    web_dir = Path(__file__).resolve().parent.parent / "web"
    srv = create_tactical_server(
        host=args.host,
        port=args.port,
        db_path=Path(args.db),
        web_dir=web_dir,
        canonical_wallet=args.wallet,
    )
    print(f"ReachMiner-Sniper Console live at http://{args.host}:{args.port}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
