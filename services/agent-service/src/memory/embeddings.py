"""Small deterministic embeddings for ChromaDB without runtime downloads."""

from __future__ import annotations

import hashlib
import math
import re

EMBEDDING_DIMENSIONS = 384
_TOKEN_PATTERN = re.compile(r"[a-z0-9_]+")


def embed_text(text: str) -> list[float]:
    """Create a normalized hashed bag-of-words embedding."""
    vector = [0.0] * EMBEDDING_DIMENSIONS

    for token in _TOKEN_PATTERN.findall(text.lower()):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "big") % EMBEDDING_DIMENSIONS
        vector[index] += 1.0 if digest[4] & 1 else -1.0

    norm = math.sqrt(sum(value * value for value in vector))
    if norm:
        return [value / norm for value in vector]
    return vector
