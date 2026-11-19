"""Strict UI Color Redline (0 Blue/Teal/Cyan/Purple) & Anti-Fraud Codebase Scanner."""

from __future__ import annotations

import colorsys
from pathlib import Path
import re

CODE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = CODE_DIR / "web"

HEX_COLOR_RE = re.compile(r"#([0-9a-fA-F]{3,8})\b")
RGB_FUNC_RE = re.compile(
    r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})(?:\s*,\s*[0-9.]+)?\s*\)"
)
HSL_FUNC_RE = re.compile(
    r"hsla?\(\s*([0-9.]+)(?:deg)?\s*,\s*([0-9.]+)%\s*,\s*([0-9.]+)%(?:\s*,\s*[0-9.]+)?\s*\)"
)
FORBIDDEN_NAMED_COLORS_RE = re.compile(
    r"\b(blue|cyan|teal|aqua|indigo|violet|purple|magenta|navy|royalblue|"
    r"dodgerblue|steelblue|slateblue|turquoise|darkcyan|darkslateblue|blueviolet)\b",
    re.IGNORECASE,
)


def _assert_warm_palette_rgb(r: int, g: int, b: int, source_ref: str) -> None:
    """Assert RGB value has zero cool-blue, cyan, teal, or purple dominance."""
    rn, gn, bn = r / 255.0, g / 255.0, b / 255.0
    hue_turn, lightness, saturation = colorsys.rgb_to_hls(rn, gn, bn)
    hue_deg = hue_turn * 360.0

    # Blue channel must NEVER exceed max(Red, Green) on any surface, text, or accent color
    assert b <= max(r, g), (
        f"Forbidden cool/blue/purple RGB channel dominance in {source_ref}: rgb({r},{g},{b})"
    )

    # For any chromatic color (saturation > 8% and non-black/white), forbid [165 deg, 320 deg]
    if saturation > 0.08 and 0.04 < lightness < 0.96:
        assert not (165.0 <= hue_deg <= 320.0), (
            f"Forbidden cyan/teal/blue/purple hue {hue_deg:.1f} deg in {source_ref}: rgb({r},{g},{b})"
        )


def test_web_console_zero_blue_cyan_teal_purple_colors() -> None:
    web_files = [
        WEB_DIR / "styles.css",
        WEB_DIR / "index.html",
        WEB_DIR / "app.js",
    ]
    found_hex_lower: set[str] = set()

    for fpath in web_files:
        assert fpath.is_file(), f"Missing web asset: {fpath}"
        content = fpath.read_text(encoding="utf-8")

        named_match = FORBIDDEN_NAMED_COLORS_RE.search(content)
        assert named_match is None, (
            f"Forbidden named cool/purple color {named_match.group(0)!r} in {fpath.name}"
        )

        for hex_match in HEX_COLOR_RE.finditer(content):
            raw_hex = hex_match.group(1)
            found_hex_lower.add(f"#{raw_hex.lower()}")
            if len(raw_hex) == 3:
                r = int(raw_hex[0] * 2, 16)
                g = int(raw_hex[1] * 2, 16)
                b = int(raw_hex[2] * 2, 16)
            elif len(raw_hex) in (6, 8):
                r = int(raw_hex[0:2], 16)
                g = int(raw_hex[2:4], 16)
                b = int(raw_hex[4:6], 16)
            else:
                continue
            _assert_warm_palette_rgb(r, g, b, f"{fpath.name}:#{raw_hex}")

        for rgb_match in RGB_FUNC_RE.finditer(content):
            r, g, b = (int(rgb_match.group(i)) for i in (1, 2, 3))
            _assert_warm_palette_rgb(r, g, b, f"{fpath.name}:{rgb_match.group(0)}")

        for hsl_match in HSL_FUNC_RE.finditer(content):
            hue_deg = float(hsl_match.group(1)) % 360.0
            sat_pct = float(hsl_match.group(2))
            if sat_pct > 8.0:
                assert not (165.0 <= hue_deg <= 320.0), (
                    f"Forbidden HSL hue {hue_deg} deg in {fpath.name}:{hsl_match.group(0)}"
                )

    # Confirm required signature Night Hunter palette tokens are actively applied
    assert "#141413" in found_hex_lower, "Missing Night Hunter Ink Black #141413"
    assert "#d97706" in found_hex_lower, "Missing Amber Crosshair Gold #D97706"
    assert "#16a34a" in found_hex_lower, "Missing Signal Green #16A34A"


def test_zero_forbidden_markers_and_zero_hardcoded_private_keys() -> None:
    # Build patterns dynamically so this test file itself never contains raw forbidden tokens
    banned_tokens = [
        "TO" + "DO",
        "FIX" + "ME",
        "[T" + "BD]",
        "【待" + "核实】",
        "SIMULATED_" + "OK",
        "mock_" + "tx",
    ]
    privkey_re = re.compile(r"0x[0-9a-fA-F]{64}\b")

    source_roots = [
        CODE_DIR / "reach_miner",
        CODE_DIR / "ts_gateway" / "src",
        CODE_DIR / "web",
    ]
    scanned_count = 0
    for root in source_roots:
        for path in root.rglob("*"):
            if not path.is_file() or path.name == "latest_ledger_snapshot.js":
                continue
            if path.suffix not in {".py", ".ts", ".js", ".css", ".html", ".json"}:
                continue
            scanned_count += 1
            text = path.read_text(encoding="utf-8")
            for tok in banned_tokens:
                assert tok not in text, f"Forbidden marker {tok!r} found in {path}"
            # Ensure no 32-byte raw private keys are hardcoded (exclude sha256Hex field labels)
            for m in privkey_re.finditer(text):
                raise AssertionError(f"Potential 32-byte hex secret {m.group(0)[:12]}... in {path}")

    assert scanned_count >= 14
