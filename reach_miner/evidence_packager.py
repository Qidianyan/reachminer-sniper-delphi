"""EvidencePackager: Zero Judge-Inducement Formatter & <=3 Attachments Packager."""

from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import urlparse

from .models import AttachmentFile, CandidateSignal, CiteCheckReport, EvidencePacket
from .shadow_judge import CiteCheckVerifier
from .wallet_guard import to_checksum_address

MAX_SUPPORTING_ATTACHMENTS = 3

# Strict anti-prompt-injection & anti-judge-inducement patterns
_FORBIDDEN_INDUCEMENT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "DIRECT_JUDGE_OR_SYSTEM_OVERRIDE",
        re.compile(
            r"\b(system\s+judge|llm\s+judge|dear\s+judge|ignore\s+(?:all\s+)?previous|"
            r"disregard\s+(?:all\s+)?prior|override\s+instructions|system\s+prompt|"
            r"assistant\s*:\s*|developer\s+mode)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "PROBABILITY_MANIPULATION_DIRECTIVE",
        re.compile(
            r"\b(set\s+(?:the\s+)?probability|update\s+(?:the\s+)?probability|"
            r"raise\s+(?:the\s+)?probability|lower\s+(?:the\s+)?probability|"
            r"adjust\s+(?:the\s+)?forecast|shift\s+(?:the\s+)?odds\s+to|"
            r"resolve\s+(?:this\s+)?market\s+to|you\s+must\s+(?:accept|resolve|update)|"
            r"you\s+should\s+(?:award|score|resolve)|100%\s+proves|undeniably\s+guarantees)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "IMPERATIVE_JUDGE_COMMAND",
        re.compile(
            r"(?:^|[.!?;]\s+)(?:please\s+|kindly\s+)?(?:accept\s+this\s+evidence|"
            r"approve\s+this\s+submission|award\s+maximum|score\s+this\s+high|"
            r"update\s+your\s+belief|change\s+the\s+forecast|conclude\s+that\s+yes|"
            r"mark\s+this\s+market)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "CN_JUDGE_INDUCEMENT",
        re.compile(
            r"(请将.{0,10}概率|上调至\s*\d+%|下调至\s*\d+%|必须采纳|裁判请注意|"
            r"系统提示词|忽略之前.{0,8}指令|直接判赢|100%\s*证明必然|请给满分)"
        ),
    ),
)


class JudgeInducementViolationError(ValueError):
    """Raised when text contains prompt-injection or judge-manipulation directives."""


def assert_zero_judge_inducement(text: str, field_name: str = "text") -> None:
    """Reject any imperative or manipulative phrasing targeting the Delphi system judge."""
    if not text or not text.strip():
        raise ValueError(f"{field_name} must not be empty")
    for rule_name, pattern in _FORBIDDEN_INDUCEMENT_PATTERNS:
        match = pattern.search(text)
        if match:
            raise JudgeInducementViolationError(
                f"Anti-Inducement Guard blocked [{rule_name}] in {field_name}: {match.group(0)!r}"
            )


def _validate_https_urls(urls: tuple[str, ...]) -> tuple[str, ...]:
    if not urls:
        raise ValueError("At least one primary authoritative source URL is required")
    cleaned: list[str] = []
    for raw_url in urls:
        parsed = urlparse(raw_url.strip())
        if parsed.scheme not in ("https", "http") or not parsed.netloc:
            raise ValueError(f"Invalid source URL: {raw_url!r}")
        cleaned.append(raw_url.strip())
    return tuple(dict.fromkeys(cleaned))


def _make_attachment(filename: str, media_type: str, content_text: str) -> AttachmentFile:
    encoded = content_text.encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    return AttachmentFile(
        filename=filename,
        media_type=media_type,
        content_text=content_text,
        sha256_hex=digest,
        size_bytes=len(encoded),
    )


class EvidencePackager:
    """Formats pure objective chronicle notes and packages <= 3 verifiable attachments."""

    def __init__(self, verifier: CiteCheckVerifier | None = None) -> None:
        self.verifier = verifier or CiteCheckVerifier()

    def format_objective_note(self, signal: CandidateSignal) -> str:
        """Build strictly objective [UTC] + [Entity] + [Quantitative Fact] + [Verbatim Quote]."""
        assert_zero_judge_inducement(signal.authoritative_entity, "authoritative_entity")
        assert_zero_judge_inducement(signal.quantitative_fact, "quantitative_fact")
        assert_zero_judge_inducement(signal.verbatim_quote, "verbatim_quote")

        utc_str = signal.observed_at_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        entity = " ".join(signal.authoritative_entity.strip().split())
        fact = " ".join(signal.quantitative_fact.strip().split())
        quote = " ".join(signal.verbatim_quote.strip().split())

        note = (
            f"[{utc_str}] [{entity}] {fact} | "
            f'Verbatim Primary Excerpt: "{quote}"'
        )
        assert_zero_judge_inducement(note, "explanatory_note")
        return note

    def compute_fact_fingerprint(self, signal: CandidateSignal) -> str:
        """Compute canonical SHA-256 fingerprint of normalized entity + fact + quote."""
        canonical = "|".join(
            [
                signal.market_id.strip().lower(),
                " ".join(signal.authoritative_entity.lower().split()),
                " ".join(signal.quantitative_fact.lower().split()),
                " ".join(signal.verbatim_quote.lower().split()),
            ]
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def build_supporting_attachments(
        self,
        signal: CandidateSignal,
        wallet_address: str,
        cite_report: CiteCheckReport,
        fact_fingerprint: str,
    ) -> tuple[AttachmentFile, ...]:
        """Create the 3 clean supporting files for Delphi LLM-as-a-Judge ingestion."""
        utc_str = signal.observed_at_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        urls_md = "\n".join(f"- {u}" for u in signal.source_urls)

        snapshot_md = (
            f"# Primary Source Verifiable Snapshot\n\n"
            f"- **Market ID**: `{signal.market_id}`\n"
            f"- **Observed UTC**: `{utc_str}`\n"
            f"- **Authoritative Entity**: {signal.authoritative_entity}\n"
            f"- **Raw Byte Stream SHA-256**: `{cite_report.raw_source_sha256}`\n"
            f"- **CiteCheck Character Offset**: `{cite_report.quote_char_offset}`\n\n"
            f"## Canonical Source URLs\n{urls_md}\n\n"
            f"## Verified Primary Text Capture\n```text\n{signal.raw_source_text.strip()}\n```\n"
        )

        diff_extract_obj = {
            "schema_version": "reachminer.diff_extract.v1",
            "market_id": signal.market_id,
            "observed_at_utc": utc_str,
            "authoritative_entity": signal.authoritative_entity,
            "quantitative_fact": signal.quantitative_fact,
            "corroborating_sources_count": signal.corroborating_sources_count,
            "source_urls": list(signal.source_urls),
            "structured_diff": signal.structured_diff_payload,
        }
        diff_extract_json = json.dumps(diff_extract_obj, indent=2, sort_keys=True, ensure_ascii=False)

        manifest_obj = {
            "schema_version": "reachminer.provenance_manifest.v1",
            "market_id": signal.market_id,
            "submitter_wallet_eip55": wallet_address,
            "fact_fingerprint_sha256": fact_fingerprint,
            "raw_source_sha256": cite_report.raw_source_sha256,
            "cite_check": {
                "passed": cite_report.passed,
                "quote_verified": cite_report.quote_verified,
                "quote_char_offset": cite_report.quote_char_offset,
                "quantitative_tokens_verified": cite_report.quantitative_tokens_verified,
            },
            "attachment_digests": {
                "01_primary_source_snapshot.md": hashlib.sha256(
                    snapshot_md.encode("utf-8")
                ).hexdigest(),
                "02_structured_diff_extract.json": hashlib.sha256(
                    diff_extract_json.encode("utf-8")
                ).hexdigest(),
            },
        }
        manifest_json = json.dumps(manifest_obj, indent=2, sort_keys=True, ensure_ascii=False)

        attachments = (
            _make_attachment("01_primary_source_snapshot.md", "text/markdown", snapshot_md),
            _make_attachment("02_structured_diff_extract.json", "application/json", diff_extract_json),
            _make_attachment("03_sha256_provenance_manifest.json", "application/json", manifest_json),
        )
        self.validate_attachment_budget(attachments)
        return attachments

    @staticmethod
    def validate_attachment_budget(attachments: tuple[AttachmentFile, ...]) -> None:
        if len(attachments) > MAX_SUPPORTING_ATTACHMENTS:
            raise ValueError(
                f"Delphi protocol permits at most {MAX_SUPPORTING_ATTACHMENTS} supporting files, "
                f"got {len(attachments)}"
            )

    def package(self, signal: CandidateSignal, wallet_address: str) -> EvidencePacket:
        """Verify, format, and bundle a CandidateSignal into an immutable EvidencePacket."""
        checksum_wallet = to_checksum_address(wallet_address)
        valid_urls = _validate_https_urls(signal.source_urls)
        note = self.format_objective_note(signal)
        cite_report = self.verifier.verify(signal)
        fact_fp = self.compute_fact_fingerprint(signal)
        attachments = self.build_supporting_attachments(
            signal=signal,
            wallet_address=checksum_wallet,
            cite_report=cite_report,
            fact_fingerprint=fact_fp,
        )
        packet_id = f"pkt_{signal.market_id}_{fact_fp[:12]}"
        return EvidencePacket(
            packet_id=packet_id,
            market_id=signal.market_id,
            wallet_address=checksum_wallet,
            explanatory_note=note,
            source_links=valid_urls,
            attachments=attachments,
            fact_fingerprint_sha256=fact_fp,
            created_at_utc=signal.observed_at_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            cite_check=cite_report,
        )
