import re
from typing import List, Dict, Any

class DocumentChunker:
    def __init__(self, chunk_size_words: int = 250, chunk_overlap_words: int = 50):
        self.chunk_size = chunk_size_words
        self.overlap = chunk_overlap_words

    def chunk_document(self, doc_id: str, title: str, text: str, source_url: str) -> List[Dict[str, Any]]:
        # Split text into paragraphs or sentences
        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
        words_all = []
        for p in paragraphs:
            words_all.extend(p.split())

        if not words_all:
            return []

        chunks: List[Dict[str, Any]] = []
        start_idx = 0
        chunk_idx = 0

        while start_idx < len(words_all):
            end_idx = min(start_idx + self.chunk_size, len(words_all))
            chunk_words = words_all[start_idx:end_idx]
            chunk_text = " ".join(chunk_words)

            if len(chunk_text.strip()) > 20:
                chunks.append({
                    "chunk_id": f"{doc_id}_chunk_{chunk_idx}",
                    "doc_id": doc_id,
                    "title": title,
                    "source_url": source_url,
                    "chunk_index": chunk_idx,
                    "text": chunk_text
                })
                chunk_idx += 1

            if end_idx == len(words_all):
                break

            start_idx += (self.chunk_size - self.overlap)

        return chunks
