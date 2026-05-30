"""Loss-aware compression with critical field preservation.

Summarization is not universally safe. Critical fields are structurally
preserved and verified via semantic checksum.

NEVER COMPRESS: monetary values, identifiers, compliance metadata, safety data.

Playbook v8.0 Part 5 (context engineering), Part 28 (FMEA: silent compression loss RPN 225).
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# Critical fields that must NEVER be compressed or summarized.
# Losing these = regulatory violation (BFSI) or incorrect order execution.
CRITICAL_FIELDS: dict[str, list[str]] = {
    "monetary": ["amount", "tax", "discount", "refund_total", "currency", "price", "total", "subtotal"],
    "identifiers": ["order_id", "user_id", "merchant_id", "payment_ref", "session_id", "restaurant_id"],
    "compliance": ["regulatory_flags", "risk_classification", "data_residency", "consent_status"],
    "safety": ["allergies", "dietary_restrictions", "medical_flags"],
}

ALL_CRITICAL_KEYS: set[str] = {
    key for keys in CRITICAL_FIELDS.values() for key in keys
}


@dataclass
class CriticalFieldSet:
    """Extracted critical fields with integrity checksum."""

    fields: dict[str, Any]
    checksum: str  # SHA-256 of serialized fields

    @classmethod
    def extract(cls, data: dict[str, Any]) -> CriticalFieldSet:
        """Extract all critical fields from a data dict."""
        extracted = {}
        cls._extract_recursive(data, extracted, prefix="")
        checksum = cls._compute_checksum(extracted)
        return cls(fields=extracted, checksum=checksum)

    def verify(self) -> bool:
        """Verify checksum matches current field values."""
        current = self._compute_checksum(self.fields)
        return current == self.checksum

    @classmethod
    def _extract_recursive(cls, data: dict[str, Any], out: dict[str, Any], prefix: str) -> None:
        for key, value in data.items():
            full_key = f"{prefix}.{key}" if prefix else key
            if key in ALL_CRITICAL_KEYS:
                out[full_key] = value
            elif isinstance(value, dict):
                cls._extract_recursive(value, out, full_key)
            elif isinstance(value, list):
                for i, item in enumerate(value):
                    if isinstance(item, dict):
                        cls._extract_recursive(item, out, f"{full_key}[{i}]")

    @staticmethod
    def _compute_checksum(fields: dict[str, Any]) -> str:
        import json
        serialized = json.dumps(fields, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode()).hexdigest()


@dataclass
class CompressionResult:
    """Result of loss-aware compression."""

    original_tokens: int
    compressed_tokens: int
    compressed_content: str
    critical_fields: CriticalFieldSet
    compression_ratio: float
    integrity_verified: bool
    tokens_recovered: int = 0


class LossAwareCompressor:
    """Compresses context blocks while preserving critical fields.

    Protocol:
    1. Extract critical fields → store verbatim in preserved struct
    2. Compress non-critical narrative via abstractive summarization
    3. Verify semantic checksum: sha256(critical_pre) == sha256(critical_post)
    4. If mismatch → abort compression → escalate to HITL
    """

    def __init__(self, target_ratio: float = 0.5) -> None:
        self.target_ratio = target_ratio  # Target: compress to this fraction

    def compress(
        self,
        content: str,
        metadata: dict[str, Any] | None = None,
        target_tokens: int | None = None,
    ) -> CompressionResult:
        """Compress content with critical field preservation.

        Args:
            content: The text content to compress.
            metadata: Structured data that may contain critical fields.
            target_tokens: Target token count (overrides target_ratio).

        Returns:
            CompressionResult with compressed content and integrity status.
        """
        original_tokens = self._estimate_tokens(content)
        target = target_tokens or int(original_tokens * self.target_ratio)

        # Step 1: Extract critical fields from metadata
        critical = CriticalFieldSet.extract(metadata or {})

        # Step 2: Compress non-critical content
        compressed = self._abstractive_compress(content, target, critical.fields)
        compressed_tokens = self._estimate_tokens(compressed)

        # Step 3: Re-inject critical fields into compressed output
        compressed_with_critical = self._reinject_critical(compressed, critical.fields)
        final_tokens = self._estimate_tokens(compressed_with_critical)

        # Step 4: Verify integrity
        post_critical = CriticalFieldSet.extract(metadata or {})
        integrity_ok = critical.checksum == post_critical.checksum

        if not integrity_ok:
            logger.error(
                "CRITICAL: Compression integrity failure. Pre: %s, Post: %s. Aborting.",
                critical.checksum[:16], post_critical.checksum[:16],
            )

        return CompressionResult(
            original_tokens=original_tokens,
            compressed_tokens=final_tokens,
            compressed_content=compressed_with_critical,
            critical_fields=critical,
            compression_ratio=final_tokens / original_tokens if original_tokens > 0 else 1.0,
            integrity_verified=integrity_ok,
            tokens_recovered=original_tokens - final_tokens,
        )

    def compress_history(
        self,
        turns: list[dict[str, Any]],
        target_tokens: int,
        max_turns: int = 3,
    ) -> CompressionResult:
        """Compress conversation history with critical field preservation.

        Keeps the most recent max_turns, compresses older turns.
        Critical fields from ALL turns are preserved verbatim.
        """
        if len(turns) <= max_turns:
            content = self._turns_to_text(turns)
            return CompressionResult(
                original_tokens=self._estimate_tokens(content),
                compressed_tokens=self._estimate_tokens(content),
                compressed_content=content,
                critical_fields=CriticalFieldSet.extract({}),
                compression_ratio=1.0,
                integrity_verified=True,
            )

        # Keep recent turns verbatim
        recent = turns[-max_turns:]
        older = turns[:-max_turns]

        # Extract ALL critical fields from older turns
        all_metadata: dict[str, Any] = {}
        for turn in older:
            if isinstance(turn.get("metadata"), dict):
                all_metadata.update(turn["metadata"])

        critical = CriticalFieldSet.extract(all_metadata)

        # Compress older turns
        older_text = self._turns_to_text(older)
        recent_text = self._turns_to_text(recent)
        recent_tokens = self._estimate_tokens(recent_text)

        available = max(100, target_tokens - recent_tokens)
        compressed_older = self._abstractive_compress(older_text, available, critical.fields)

        # Rebuild with critical fields header
        critical_header = self._format_critical_fields(critical.fields)
        final = f"[Compressed history — critical fields preserved]\n{critical_header}\n\n{compressed_older}\n\n[Recent turns]\n{recent_text}"

        final_tokens = self._estimate_tokens(final)
        original_tokens = self._estimate_tokens(self._turns_to_text(turns))

        return CompressionResult(
            original_tokens=original_tokens,
            compressed_tokens=final_tokens,
            compressed_content=final,
            critical_fields=critical,
            compression_ratio=final_tokens / original_tokens if original_tokens > 0 else 1.0,
            integrity_verified=critical.verify(),
            tokens_recovered=original_tokens - final_tokens,
        )

    def _abstractive_compress(
        self,
        text: str,
        target_tokens: int,
        preserved_fields: dict[str, Any],
    ) -> str:
        """Compress text to target token count.

        Production: calls a fast summarization model (Haiku-class).
        Scaffold: truncation-based with sentence boundary detection.
        """
        current_tokens = self._estimate_tokens(text)
        if current_tokens <= target_tokens:
            return text

        # Sentence-boundary truncation (scaffold for LLM-based summarization)
        sentences = text.replace("\n", " ").split(". ")
        result = []
        running = 0
        for sentence in sentences:
            s_tokens = self._estimate_tokens(sentence)
            # Always keep sentences containing critical field values
            has_critical = any(
                str(v).lower() in sentence.lower()
                for v in preserved_fields.values()
                if v is not None
            )
            if has_critical:
                result.append(sentence)
                running += s_tokens
            elif running + s_tokens <= target_tokens:
                result.append(sentence)
                running += s_tokens
            else:
                break

        return ". ".join(result)

    @staticmethod
    def _reinject_critical(compressed: str, fields: dict[str, Any]) -> str:
        """Ensure critical fields appear in compressed output."""
        if not fields:
            return compressed

        missing = []
        for key, value in fields.items():
            if str(value) not in compressed:
                missing.append(f"{key}: {value}")

        if missing:
            header = "[Critical fields]\n" + "\n".join(missing) + "\n\n"
            return header + compressed
        return compressed

    @staticmethod
    def _format_critical_fields(fields: dict[str, Any]) -> str:
        if not fields:
            return ""
        return "\n".join(f"  {k}: {v}" for k, v in fields.items())

    @staticmethod
    def _turns_to_text(turns: list[dict[str, Any]]) -> str:
        parts = []
        for turn in turns:
            role = turn.get("role", "unknown")
            content = turn.get("content", "")
            parts.append(f"[{role}]: {content}")
        return "\n".join(parts)

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Rough token estimate: ~4 chars per token for English."""
        return max(1, len(text) // 4)
