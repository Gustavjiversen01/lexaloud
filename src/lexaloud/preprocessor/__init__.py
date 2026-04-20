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
from .markdown_strip import markdown_to_tts_prose
from .mathjax_dedupe import dedupe_mathjax_selection
from .numbers import normalize_numbers
from .pdf_cleanup import clean_pdf_paste
from .segmenter import split_sentences
from .symbols import normalize_math_symbols, normalize_urls_emails


@dataclass
class PreprocessorConfig:
    dedupe_mathjax_selection: bool = True
    strip_markdown: bool = True
    sre_latex_enabled: bool = False
    sre_latex_timeout_s: float = 10.0
    sre_latex_domain: str = "clearspeak"
    sre_latex_style: str = ""
    strip_numeric_bracket_citations: bool = True
    strip_parenthetical_citations: bool = False
    expand_latin_abbreviations: bool = True
    expand_academic_abbreviations: bool = True
    normalize_numbers: bool = True
    normalize_urls: bool = True
    normalize_math_symbols: bool = True
    pdf_cleanup: bool = True


def preprocess(text: str, config: PreprocessorConfig | None = None) -> list[str]:
    """Run the full pipeline and return a list of sentences."""
    cfg = config or PreprocessorConfig()

    # MathJax dedupe must run before any whitespace-collapsing stage —
    # it needs the raw newline structure to detect stacked blocks.
    if cfg.dedupe_mathjax_selection:
        text = dedupe_mathjax_selection(text)
    # Markdown next — needs structural markers intact before character
    # substitutions mangle them.
    if cfg.strip_markdown:
        text = markdown_to_tts_prose(text)
    # SRE LaTeX → speech (opt-in; Node + speech-rule-engine required).
    # Runs BEFORE normalize_math_symbols so SRE handles everything inside
    # $...$ spans and the Unicode stage handles bare glyphs outside.
    if cfg.sre_latex_enabled:
        from .sre_latex import latex_to_speech

        text = latex_to_speech(
            text,
            timeout_s=cfg.sre_latex_timeout_s,
            domain=cfg.sre_latex_domain,
            style=cfg.sre_latex_style or None,
        )
    # Math symbols next (before PDF cleanup's NFKC flattens superscripts)
    if cfg.normalize_math_symbols:
        text = normalize_math_symbols(text)
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
    if cfg.normalize_urls:
        text = normalize_urls_emails(text)
    if cfg.normalize_numbers:
        text = normalize_numbers(text)

    sentences = split_sentences(text)
    # Drop empty/whitespace-only remnants.
    return [s.strip() for s in sentences if s.strip()]


async def preprocess_with_llm(
    text: str,
    config: PreprocessorConfig | None = None,
    normalizer: object | None = None,
) -> list[str]:
    """Run the full pipeline including optional LLM normalization.

    The ``normalizer`` argument is an ``LlmNormalizer`` instance (or None).
    Typed as ``object`` to avoid importing the optional llama-cpp-python
    dependency at module level.
    """
    cfg = config or PreprocessorConfig()

    # Rule-based stages (same order as preprocess())
    if cfg.dedupe_mathjax_selection:
        text = dedupe_mathjax_selection(text)
    if cfg.strip_markdown:
        text = markdown_to_tts_prose(text)
    if cfg.sre_latex_enabled:
        from .sre_latex import latex_to_speech

        text = latex_to_speech(
            text,
            timeout_s=cfg.sre_latex_timeout_s,
            domain=cfg.sre_latex_domain,
            style=cfg.sre_latex_style or None,
        )
    if cfg.normalize_math_symbols:
        text = normalize_math_symbols(text)
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
    if cfg.normalize_urls:
        text = normalize_urls_emails(text)
    if cfg.normalize_numbers:
        text = normalize_numbers(text)

    # LLM normalization: AFTER rules, BEFORE sentence splitting.
    # The LLM sees full paragraphs for acronym context.
    if normalizer is not None:
        text = await normalizer.normalize(text)  # type: ignore[attr-defined]

    sentences = split_sentences(text)
    return [s.strip() for s in sentences if s.strip()]


__all__ = [
    "PreprocessorConfig",
    "preprocess",
    "preprocess_with_llm",
    "clean_pdf_paste",
    "dedupe_mathjax_selection",
    "expand_academic_abbreviations",
    "expand_latin_abbreviations",
    "markdown_to_tts_prose",
    "normalize_math_symbols",
    "normalize_numbers",
    "normalize_urls_emails",
    "strip_numeric_bracket_citations",
    "strip_parenthetical_citations",
    "split_sentences",
]
