"""Centralized handle generation for provenance references.

Generates unique REF_xxx handles with collision avoidance.
Each handle is ~2 tokens in context (vs ~80 tokens for inline metadata).

Playbook v8.0 Part 26.
"""

from __future__ import annotations

import hashlib
import time
import threading
from typing import Any


class HandleGenerator:
    """Thread-safe generator for provenance reference handles.

    Handles are short, unique, and deterministic when given the same inputs.
    Format: REF_{counter:04d} for sequential, REF_{hash:8} for content-addressed.
    """

    def __init__(self, mode: str = "sequential") -> None:
        """
        Args:
            mode: "sequential" for REF_0001, REF_0002, ...
                  "content" for REF_{hash} based on input content
        """
        self.mode = mode
        self._counter = 0
        self._lock = threading.Lock()
        self._issued: set[str] = set()

    def generate(self, content: str | None = None, source_type: str = "unknown") -> str:
        """Generate a unique reference handle.

        Args:
            content: Optional content for content-addressed handles.
            source_type: Type of source (for audit, not part of handle).

        Returns:
            A unique REF_xxx string.
        """
        with self._lock:
            if self.mode == "content" and content:
                handle = self._content_handle(content)
            else:
                handle = self._sequential_handle()

            self._issued.add(handle)
            return handle

    def is_valid(self, handle: str) -> bool:
        """Check if a handle was issued by this generator."""
        return handle in self._issued

    @property
    def total_issued(self) -> int:
        return len(self._issued)

    def _sequential_handle(self) -> str:
        self._counter += 1
        return f"REF_{self._counter:04d}"

    def _content_handle(self, content: str) -> str:
        """Content-addressed handle: same content → same handle."""
        h = hashlib.sha256(content.encode()).hexdigest()[:8]
        handle = f"REF_{h}"
        # Handle collision (unlikely but possible with 8-char hash)
        suffix = 0
        while handle in self._issued:
            suffix += 1
            handle = f"REF_{h}_{suffix}"
        return handle
