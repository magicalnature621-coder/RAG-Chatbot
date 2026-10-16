import os
import json
import re
import math
import threading
import numpy as np
from typing import List, Dict, Any, Optional

from backend.rag.chunker import DocumentChunker
from backend.rag.embeddings import EmbeddingEngine

INDEX_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "vector_index.json")

# Domain & General Stopwords
STOPWORDS = {
    'what', 'is', 'are', 'was', 'were', 'the', 'a', 'an', 'and', 'or', 'for', 
    'in', 'on', 'at', 'to', 'from', 'of', 'with', 'by', 'iiit', 'kottayam', 
    'college', 'institute', 'i', 'u', 'you', 'me', 'my', 'we', 'our', 'about', 
    'not', 'no', 'right', 'answer', 'giving', 'tell', 'can', 'please', 'know', 
    'how', 'much', 'many', 'good', 'some', 'any', 'which', 'who', 'where', 'when',
    'there', 'their', 'this', 'that', 'these', 'those', 'as', 'it', 'its', 'be',
    'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'asked', 'give'
}

# Domain Intent Mappings (Keyword intent -> URL keywords to boost)
INTENT_BOOSTS = {
    ("ctc", "placement", "placements", "salary", "package", "lpa", "placed", "companies", "recruiter", "recruiters", "internship"): [
        "placement", "training"
    ],
    # Branch/programme questions boost ONLY the actual B.Tech branch pages.
    # This used to be bundled with "admission" below, but "admission" as a
    # target substring also matches "PhD Admissions" / "M.Tech Admissions"
    # titles, which wrongly outranked the real B.Tech branch pages for a
    # plain "what branches does btech offer" question.
    ("btech", "b.tech", "branch", "branches", "specialization", "specializations", "degree", "degrees"): [
        "btech"
    ],
    # Generic admission-process questions (eligibility/cutoff/how to apply).
    ("admission", "admissions", "course", "courses", "programme", "programmes", "program", "programs", "eligibility", "cutoff", "josaa", "csab", "seat", "jee", "apply"): [
        "admission", "btech"
    ],
    # NOTE: deliberately no "home" target here - this site names EVERY
    # programme page's route "..._home" (btech_cs_home, mtech_home,
    # phd_home, etc.), so "home" as a substring boost matched 7 unrelated
    # pages instead of just the actual homepage, drowning out the one page
    # that actually covers hostels (Campus Facilities, url "#!/campus").
    ("hostel", "hostels", "mess", "curfew", "food", "room", "rooms", "warden", "accommodation", "dormitory"): [
        "campus", "hostel"
    ],
    # NOTE: deliberately does NOT include "btech" - the 5 individual B.Tech
    # programme pages each contain several chunks that mention "fee"/
    # "scholarship" in passing, and boosting all of them let their raw
    # keyword frequency bury the one page that actually covers hostel/mess
    # fees (Campus Facilities).
    ("fee", "fees", "tuition", "cost", "scholarship", "dues", "payment"): [
        "admission", "campus"
    ],
    ("faculty", "professor", "professors", "teacher", "teachers", "hod", "dean", "director"): [
        "faculty", "dept_head", "adminstaff"
    ],
    ("club", "clubs", "cultural", "wildbeats", "trendles", "technical", "fest", "fests", "activities", "student activities", "extracurricular", "societies", "society"): [
        "culturalclub", "socialclub", "technical", "club"
    ],
    ("ragging", "antiragging", "harassment", "grievance", "rules"): [
        "antiragging"
    ]
}

def tokenize_cleaned(text: str) -> List[str]:
    # Extract alphanumeric words and lowercase
    words = re.findall(r'\b[a-zA-Z0-9_]+\b', text.lower())
    return [w for w in words if w not in STOPWORDS]

class VectorStore:
    def __init__(self, index_path: str = INDEX_PATH):
        self.index_path = index_path
        self.chunker = DocumentChunker(chunk_size_words=220, chunk_overlap_words=45)
        self.embedder = EmbeddingEngine(dimension=256)
        
        self.chunks: List[Dict[str, Any]] = []
        self.embeddings: List[List[float]] = []
        
        # Inverted index for BM25
        self.df: Dict[str, int] = {}
        self.chunk_tokens: List[List[str]] = []

        # The crawler thread mutates the index while request threads search it;
        # without this, a search can pair chunk i with another chunk's embedding.
        self._lock = threading.RLock()
        
        self.load()

    def _rebuild_bm25_index(self):
        self.df = {}
        self.chunk_tokens = []
        for c in self.chunks:
            tokens = tokenize_cleaned(c["text"] + " " + c.get("title", ""))
            self.chunk_tokens.append(tokens)
            for t in set(tokens):
                self.df[t] = self.df.get(t, 0) + 1

    def load(self):
        if os.path.exists(self.index_path):
            try:
                with open(self.index_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.chunks = data.get("chunks", [])
                    self.embeddings = data.get("embeddings", [])
                
                if self.chunks:
                    texts = [c["text"] for c in self.chunks]
                    self.embedder.fit(texts)
                    self._rebuild_bm25_index()
            except Exception as e:
                print(f"Failed to load vector index: {e}")
                self.chunks = []
                self.embeddings = []

    def save(self):
        with self._lock:
            self._save_locked()

    def _save_locked(self):
        os.makedirs(os.path.dirname(self.index_path), exist_ok=True)
        tmp_path = self.index_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump({
                "chunks": self.chunks,
                "embeddings": self.embeddings,
                "total_chunks": len(self.chunks)
            }, f, ensure_ascii=False, indent=2)
        # Atomic replace so a crash mid-write never leaves a truncated index.
        os.replace(tmp_path, self.index_path)

    def delete_document(self, doc_id: str):
        with self._lock:
            self._delete_locked(doc_id)

    def _delete_locked(self, doc_id: str):
        keep_indices = [i for i, c in enumerate(self.chunks) if c["doc_id"] != doc_id]
        self.chunks = [self.chunks[i] for i in keep_indices]
        self.embeddings = [self.embeddings[i] for i in keep_indices]
        self._rebuild_bm25_index()

    def upsert_document(self, doc_id: str, title: str, text: str, source_url: str) -> int:
        new_chunks = self.chunker.chunk_document(doc_id, title, text, source_url)
        new_embeddings = [self.embedder.embed_text(c["text"]) for c in new_chunks]
        with self._lock:
            self._delete_locked(doc_id)
            self.chunks.extend(new_chunks)
            self.embeddings.extend(new_embeddings)
            self._rebuild_bm25_index()
            self._save_locked()
        return len(new_chunks)

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        with self._lock:
            return self._search_locked(query, top_k)

    def _search_locked(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        if not self.chunks or not self.embeddings:
            return []

        N = len(self.chunks)
        q_tokens = tokenize_cleaned(query)
        if not q_tokens:
            # Fallback if all words were stopwords
            q_tokens = re.findall(r'\b[a-zA-Z0-9_]+\b', query.lower())

        # Determine domain intent boosts
        intent_targets = []
        for trigger_words, targets in INTENT_BOOSTS.items():
            if any(tw in q_tokens or tw in query.lower() for tw in trigger_words):
                intent_targets.extend(targets)

        # 1. Cosine similarity
        query_vec = np.array(self.embedder.embed_text(query), dtype=np.float32)
        emb_matrix = np.array(self.embeddings, dtype=np.float32)
        cosine_scores = np.dot(emb_matrix, query_vec)

        # 2. BM25 calculation
        results = []
        avg_len = sum(len(t) for t in self.chunk_tokens) / max(1, len(self.chunk_tokens))

        for i, chunk in enumerate(self.chunks):
            tokens = self.chunk_tokens[i] if i < len(self.chunk_tokens) else tokenize_cleaned(chunk["text"])
            title_tokens = set(tokenize_cleaned(chunk.get("title", "")))
            url_lower = chunk.get("source_url", "").lower()
            title_lower = chunk.get("title", "").lower()

            # BM25 score
            bm25_score = 0.0
            doc_len = len(tokens)
            for t in q_tokens:
                doc_freq = self.df.get(t, 1)
                idf = math.log((N - doc_freq + 0.5) / (doc_freq + 0.5) + 1.0)
                tf = tokens.count(t)
                
                # Standard BM25 term frequency
                k1 = 1.5
                b = 0.75
                denom = tf + k1 * (1.0 - b + b * (doc_len / (avg_len or 1)))
                term_score = idf * ((tf * (k1 + 1.0)) / (denom or 1.0))
                
                # Boost if in title
                if t in title_tokens:
                    term_score += idf * 2.5

                bm25_score += term_score

            # Intent boost
            if intent_targets:
                for target in intent_targets:
                    if target in url_lower or target in title_lower:
                        bm25_score += 25.0  # Reliable boost for the right page, without drowning out everything else

            cos_score = float(cosine_scores[i])
            # Combined final score
            final_score = (0.7 * bm25_score) + (0.3 * cos_score * 10.0)

            results.append({
                "chunk_id": chunk["chunk_id"],
                "doc_id": chunk["doc_id"],
                "title": chunk["title"],
                "source_url": chunk["source_url"],
                "text": chunk["text"],
                "score": round(float(final_score), 4),
                "bm25_score": round(float(bm25_score), 4),
                "cosine_score": round(float(cos_score), 4)
            })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            chunks = list(self.chunks)
        unique_docs = len(set(c["doc_id"] for c in chunks))
        return {
            "total_chunks": len(chunks),
            "total_documents": unique_docs,
            "index_path": self.index_path
        }
