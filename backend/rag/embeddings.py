import re
import math
import hashlib
import numpy as np
from typing import List, Dict, Any

def _stable_hash(token: str) -> int:
    """
    Deterministic replacement for Python's built-in hash().
    IMPORTANT: Python randomizes str hash() per-process (PYTHONHASHSEED) for
    security reasons, unless explicitly disabled. That means the same token
    would map to a different vector index/sign every time the server
    restarts, silently corrupting every stored embedding the moment a new
    process starts. hashlib digests are stable across processes and
    machines, so we use that instead.
    """
    digest = hashlib.md5(token.encode("utf-8")).hexdigest()
    return int(digest, 16)

class EmbeddingEngine:
    def __init__(self, dimension: int = 256):
        self.dim = dimension
        self.doc_count = 0
        self.term_doc_freq: Dict[str, int] = {}

    def _tokenize(self, text: str) -> List[str]:
        # Lowercase and extract alphanumeric words
        tokens = re.findall(r'\b\w+\b', text.lower())
        # Add character trigrams for robust technical/college abbreviations (like "iiitk", "cse", "lpa")
        trigrams = []
        for t in tokens:
            if len(t) >= 3:
                for i in range(len(t) - 2):
                    trigrams.append(t[i:i+3])
        return tokens + trigrams

    def fit(self, texts: List[str]):
        self.doc_count = len(texts)
        self.term_doc_freq = {}
        for t in texts:
            unique_tokens = set(self._tokenize(t))
            for tok in unique_tokens:
                self.term_doc_freq[tok] = self.term_doc_freq.get(tok, 0) + 1

    def embed_text(self, text: str) -> List[float]:
        vec = np.zeros(self.dim, dtype=np.float32)
        tokens = self._tokenize(text)
        if not tokens:
            return vec.tolist()

        # Term frequency
        tf: Dict[str, int] = {}
        for tok in tokens:
            tf[tok] = tf.get(tok, 0) + 1

        for tok, count in tf.items():
            # Hash token into dimension index (stable across process restarts)
            idx = _stable_hash(tok) % self.dim
            # Sign hash for Random Projection / SimHash behavior
            sign = 1.0 if (_stable_hash(tok + "_sign") % 2 == 0) else -1.0
            
            # IDF weighting
            df = self.term_doc_freq.get(tok, 1)
            idf = math.log((self.doc_count + 1.0) / (df + 0.5)) + 1.0
            weight = (1.0 + math.log(count)) * idf * sign
            vec[idx] += weight

        # Normalize to unit length
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm

        return vec.tolist()

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        return [self.embed_text(t) for t in texts]
