"""Shared privacy-safe text identifiers.

Lexaloud never logs raw user selection text. Places that need to refer
to a sentence (debug logs, state dumps, error messages) use a
fingerprint — SHA-1[:8] + length — which is enough to correlate
occurrences across the journal without disclosing content.
"""

from __future__ import annotations

import hashlib


def sentence_token(sentence: str) -> str:
    """Return ``<sha1[:8]> (<N>ch)`` as a privacy-safe sentence ID."""
    digest = hashlib.sha1(sentence.encode("utf-8")).hexdigest()[:8]
    return f"{digest} ({len(sentence)}ch)"


__all__ = ["sentence_token"]
