"""Text preprocessing pipeline for Lexaloud.

Input: raw captured text (possibly pasted from a PDF with broken line wraps,
inline citations, Latin abbreviations, etc.). Output: a list of clean,
synthesis-ready sentences.
"""

from __future__ import annotations

from dataclasses import dataclass

from .abbreviations import expand_latin_abbreviations
from .academic_abbreviations import expand_academic_abbreviations
from .citations import strip_numeric_bracket_citations, strip_parenthetical_citations
from .pdf_cleanup import clean_pdf_paste
from .segmenter import split_sentences


@dataclass
class PreprocessorConfig:
    strip_numeric_bracket_citations: bool = True
    strip_parenthetical_citations: bool = False
    expand_latin_abbreviations: bool = True
    expand_academic_abbreviations: bool = True
    pdf_cleanup: bool = True


def preprocess(text: str, config: PreprocessorConfig | None = None) -> list[str]:
    """Run the full pipeline and return a list of sentences."""
    cfg = config or PreprocessorConfig()

    if cfg.pdf_cleanup:
        text = clean_pdf_paste(text)
    if cfg.strip_numeric_bracket_citations:
        text = strip_numeric_bracket_citations(text)
    if cfg.strip_parenthetical_citations:
        text = strip_parenthetical_citations(text)
    if cfg.expand_latin_abbreviations:
        text = expand_latin_abbreviations(text)
    if cfg.expand_academic_abbreviations:
        text = expand_academic_abbreviations(text)

    sentences = split_sentences(text)
    # Drop empty/whitespace-only remnants.
    return [s.strip() for s in sentences if s.strip()]


__all__ = [
    "PreprocessorConfig",
    "preprocess",
    "clean_pdf_paste",
    "expand_academic_abbreviations",
    "expand_latin_abbreviations",
    "strip_numeric_bracket_citations",
    "strip_parenthetical_citations",
    "split_sentences",
]
