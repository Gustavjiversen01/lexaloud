"""Lexaloud — universal Linux text-to-speech tool for academic reading-along."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("lexaloud")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"
