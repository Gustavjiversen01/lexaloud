"""Sentence segmentation using pysbd.

Wraps pysbd so callers get a plain list[str] without pulling pysbd into the
rest of the codebase. pysbd's `Segmenter` maintains mutable instance state
during `segment()`, so it is NOT safe to share across threads. The daemon
may serve concurrent `/speak` requests (FastAPI's thread pool for sync
endpoints, asyncio executor for async ones), so we protect access with a
module-level lock.
"""

from __future__ import annotations

import threading
from functools import lru_cache


_SEGMENT_LOCK = threading.Lock()


@lru_cache(maxsize=1)
def _segmenter():
    import pysbd  # deferred import

    return pysbd.Segmenter(language="en", clean=False)


def split_sentences(text: str) -> list[str]:
    if not text:
        return []
    with _SEGMENT_LOCK:
        return list(_segmenter().segment(text))
