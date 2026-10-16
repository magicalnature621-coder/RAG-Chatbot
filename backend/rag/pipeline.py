import re
from typing import List, Dict, Any, Optional
from backend.rag.vector_store import VectorStore
from backend.rag.llm import LLMProvider
from backend.rag.structured import (
    detect_structured_intent,
    structured_context_chunk,
    load_structured,
    faculty_markdown_table,
    FACULTY_URL,
)

# Pure small-talk gets answered directly, with NO document retrieval at all.
# Anchored to the whole (trimmed) message so it never fires on a real question
# that merely starts with "hi" (e.g. "hi, what are the hostel fees?").
_GREETING_RE = re.compile(
    r"^\s*(hi+|hey+|hello+|yo|sup|hola|greetings|good\s*(morning|afternoon|evening|night))\s*[!.?]*\s*$",
    re.IGNORECASE,
)
_THANKS_RE = re.compile(r"^\s*(thanks?|thank\s*you|thx|ty|appreciate\s*it)\s*[!.?]*\s*$", re.IGNORECASE)
_BYE_RE = re.compile(r"^\s*(bye|goodbye|see\s*you|see\s*ya|cya|take\s*care)\s*[!.?]*\s*$", re.IGNORECASE)
_HOWAREYOU_RE = re.compile(r"^\s*how\s*(are|r)\s*(you|u)\s*[?.!]*\s*$", re.IGNORECASE)

_GREETING_REPLY = (
    "Hi there! I'm CampusBot, your assistant for IIIT Kottayam. "
    "Ask me about admissions, courses, placements, hostels, clubs, or anything else about the college!"
)
_THANKS_REPLY = "You're welcome! Let me know if there's anything else you'd like to know about IIIT Kottayam."
_BYE_REPLY = "Take care! Come back anytime you have a question about IIIT Kottayam."
_HOWAREYOU_REPLY = "I'm doing well, thanks for asking! How can I help you with IIIT Kottayam today?"


def _chitchat_reply(user_question: str) -> Optional[str]:
    text = user_question.strip()
    if _GREETING_RE.match(text):
        return _GREETING_REPLY
    if _THANKS_RE.match(text):
        return _THANKS_REPLY
    if _BYE_RE.match(text):
        return _BYE_REPLY
    if _HOWAREYOU_RE.match(text):
        return _HOWAREYOU_REPLY
    return None


class RAGPipeline:
    def __init__(self, vector_store: Optional[VectorStore] = None):
        self.vector_store = vector_store or VectorStore()
        self.llm = LLMProvider()

    def query(self, user_question: str, history: Optional[List[Dict[str, str]]] = None, top_k: int = 5) -> Dict[str, Any]:
        # 0. Small talk (greetings/thanks/goodbyes) is answered directly -
        # no point retrieving college documents for "hi" or "thanks".
        chitchat = _chitchat_reply(user_question)
        if chitchat is not None:
            return {
                "answer": chitchat,
                "sources": [],
                "provider": "chitchat",
                "chunks_retrieved": 0
            }

        # 1. Conversational Query Expansion for follow-ups
        search_query = user_question
        if history and len(user_question.split()) <= 6:
            # Check previous user queries to carry over context (e.g. 'placements', 'fees')
            prev_user_queries = [h["content"] for h in history if h.get("role") == "user"]
            if prev_user_queries:
                search_query = f"{user_question} {prev_user_queries[-1]}"

        # 2. Retrieve top matching chunks using upgraded BM25 + Vector Intent Search
        retrieved_chunks = self.vector_store.search(search_query, top_k=top_k)

        # 2b. Faculty / placement questions need the COMPLETE record set, not
        # the top-k fragments. The structured chunk goes first so it always
        # reaches the LLM (llm.py only reads the first 4 chunks).
        intent = detect_structured_intent(search_query)
        structured_chunk = structured_context_chunk(intent) if intent else None
        if structured_chunk:
            retrieved_chunks = [structured_chunk] + [
                c for c in retrieved_chunks if c["source_url"] != structured_chunk["source_url"]
            ][:3]

        # 3. Extract unique source citations
        sources_seen = set()
        sources = []
        for c in retrieved_chunks:
            url = c["source_url"]
            if url not in sources_seen:
                sources_seen.add(url)
                sources.append({
                    "title": c["title"],
                    "url": url,
                    "score": c["score"],
                    "snippet": c["text"][:160] + "..."
                })

        # 4. Generate grounded, accurate response
        provider = self.llm.get_active_provider()
        if structured_chunk and intent == "faculty" and provider == "local":
            # No LLM configured: print the complete directory instead of
            # relying on a 5-line extractive excerpt.
            records = load_structured().get("faculty", [])
            answer = (
                f"Here is the full faculty directory I have ({len(records)} members):\n\n"
                + faculty_markdown_table(records)
                + f"\n\n*Source: [Faculty Directory]({FACULTY_URL})*"
            )
        else:
            answer, provider = self.llm.generate(user_question, retrieved_chunks, history=history)

        return {
            "answer": answer,
            "sources": sources,
            "provider": provider,
            "chunks_retrieved": len(retrieved_chunks)
        }

# Global singleton
_pipeline_instance: Optional[RAGPipeline] = None

def get_rag_pipeline() -> RAGPipeline:
    global _pipeline_instance
    if _pipeline_instance is None:
        _pipeline_instance = RAGPipeline()
    return _pipeline_instance
