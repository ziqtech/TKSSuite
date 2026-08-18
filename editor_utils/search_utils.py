"""Shared text search helpers for editor list filters."""

import zhconv
from functools import lru_cache


def normalize_search_text(value) -> str:
    """Lowercase text and remove all whitespace for fuzzy matching."""
    return "".join(str(value or "").casefold().split())


@lru_cache(maxsize=8192)
def _search_variants(value: str) -> frozenset[str]:
    normalized = normalize_search_text(value)
    if not normalized:
        return frozenset()
    return frozenset({
        normalized,
        normalize_search_text(zhconv.convert(normalized, "zh-tw")),
        normalize_search_text(zhconv.convert(normalized, "zh-cn")),
    })


def search_match(query, *values) -> bool:
    """Return whether query occurs in any value in simplified/traditional form."""
    query_variants = _search_variants(str(query or ""))
    if not query_variants:
        return True

    for value in values:
        value_variants = _search_variants(str(value or ""))
        if any(q in candidate for q in query_variants for candidate in value_variants if q):
            return True
    return False
