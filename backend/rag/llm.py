import os
import json
import re
import urllib.request
from typing import List, Dict, Any, Optional, Tuple

from dotenv import load_dotenv
load_dotenv()  # populate os.environ from a .env file if one exists (previously never called)

from backend.database import get_setting

SYSTEM_PROMPT = """You are CampusBot, a friendly and knowledgeable assistant for IIIT Kottayam \
(Indian Institute of Information Technology Kottayam). You talk like a helpful human staff \
member, not a search engine.

You will be given some context pulled from the official college website, plus the user's \
question. Guidelines:

1. Answer naturally and conversationally, the way a helpful person would. It's fine to greet
   people back, make small talk, or ask a quick clarifying question if the request is unclear.
2. Base every factual claim (numbers, names, dates, fees, eligibility, etc.) ONLY on the
   provided context. Never invent or guess a specific fact that isn't in the context.
3. If the context does not contain the answer, say so plainly (e.g. "I don't see that on the
   college site, but you can check <suggest where>") instead of making something up.
4. Use bold text, short bullet points, or a small table when it makes numbers/lists easier to
   scan - but don't force structure onto a simple conversational reply.
5. Keep answers focused and not overly long unless the question calls for detail.
"""

CHITCHAT_SYSTEM_NOTE = (
    "The retrieved context below may or may not be relevant - only use it if it actually "
    "helps answer what the user said. If the user is just greeting you, thanking you, or "
    "making small talk, simply respond in kind; do not dump unrelated college information."
)


NO_MODEL_NOTE = (
    "Basic mode - no AI model is configured, so this is a direct excerpt rather than a "
    "written answer. Add a free Groq or Gemini API key in Settings for natural, more "
    "accurate responses."
)


def generate_local_extractive_answer(query: str, chunks: List[Dict[str, Any]],
                                     note: str = NO_MODEL_NOTE) -> str:
    """
    Fallback used only when no LLM API key is configured (provider == 'local').
    This is intentionally conservative: it never invents specific facts (like
    hardcoded CTC figures or program lists) that aren't in the retrieved text,
    since baked-in numbers would silently go stale or wrong the moment the
    real website content differs from whatever was hardcoded here. It just
    surfaces the most relevant retrieved sentences, cleanly deduplicated.
    """
    if not chunks:
        return (
            "I couldn't find anything relevant to that in the college website records. "
            "You can check the official portal at https://iiitkottayam.ac.in/#!/home.\n\n"
            f"_({note})_"
        )

    top_chunk = chunks[0]
    source_url = top_chunk["source_url"]
    source_title = top_chunk["title"]

    # Words that appear in almost every single page on this site and so add
    # no discriminative signal (every page says "IIIT Kottayam" somewhere).
    # Without filtering these, a completely unrelated page that merely
    # mentions "Kottayam" can tie with - and, being processed later in the
    # sort, even crowd out - the one line that actually answers the question.
    GENERIC_WORDS = {
        "the", "and", "for", "are", "was", "were", "you", "your", "tell", "me",
        "about", "please", "list", "all", "give", "show", "does", "what", "who",
        "which", "when", "where", "why", "how", "can",
        "iiit", "iiitk", "kottayam", "college", "institute",
    }
    all_tokens = [w for w in re.findall(r"\b[a-zA-Z0-9_]+\b", query.lower()) if len(w) > 2]
    q_tokens = [w for w in all_tokens if w not in GENERIC_WORDS]
    if not q_tokens:
        # Query was ENTIRELY generic terms (e.g. "tell me about IIIT
        # Kottayam") - fall back to unfiltered tokens rather than matching
        # nothing at all.
        q_tokens = all_tokens

    def best_matching_lines(chunk_text: str):
        # Chunks are built by joining ~250 words with spaces (see chunker.py),
        # so they contain no internal newlines - splitting on sentence
        # boundaries instead of lines is what actually gives sentence-level
        # (rather than whole-250-word-blob-level) relevance matching.
        sentences = re.split(r'(?<=[.!?])\s+', chunk_text.strip())
        found = []
        for sentence in sentences:
            sentence_clean = sentence.strip()
            if len(sentence_clean) <= 20:
                continue
            sentence_lower = sentence_clean.lower()
            matches = sum(1 for tok in q_tokens if tok in sentence_lower)
            if matches > 0:
                found.append((matches, sentence_clean))
        found.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in found]

    # Walk chunks in retrieval-rank order and exhaust each one's own matching
    # lines before ever moving to the next - so the top-ranked (most
    # relevant) chunk's content always wins over a lower-ranked chunk's,
    # regardless of raw keyword-count ties.
    chosen = []
    seen_prefixes = set()
    for c in chunks[:4]:
        for line_clean in best_matching_lines(c["text"]):
            prefix = line_clean[:40]
            if prefix in seen_prefixes:
                continue
            seen_prefixes.add(prefix)
            chosen.append(line_clean)
            if len(chosen) >= 5:
                break
        if len(chosen) >= 5:
            break

    if not chosen:
        # No line matched the question's words closely enough - fall back to
        # a short excerpt of the single best-ranked chunk instead of guessing.
        chosen = [top_chunk["text"][:400].strip() + ("..." if len(top_chunk["text"]) > 400 else "")]

    bullets = "\n".join(f"- {l}" for l in chosen)
    return (
        f"Here's what I found on **{source_title}**:\n\n{bullets}\n\n"
        f"*Source: [{source_title}]({source_url})*\n\n"
        f"_({note})_"
    )


PROVIDER_ORDER = ["groq", "gemini", "openai"]

# Groq retired llama-3.3-70b-versatile on 2026-08-16; gpt-oss-120b is its
# recommended replacement. All model names can be overridden from .env.
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
# gemini-1.5-flash was shut down in late 2025. If Google deprecates this one
# too, check https://ai.google.dev/gemini-api/docs/models
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")


def _get_key(provider: str) -> Optional[str]:
    if provider == "groq":
        return get_setting("groq_api_key") or os.environ.get("GROQ_API_KEY")
    if provider == "gemini":
        return get_setting("gemini_api_key") or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if provider == "openai":
        return get_setting("openai_api_key") or os.environ.get("OPENAI_API_KEY")
    return None


class LLMProvider:
    def __init__(self):
        pass

    def _candidate_providers(self) -> List[str]:
        """
        Providers to try, in order. An explicit choice in Settings goes first
        (and "local" means: never call a remote model). Any other provider with
        a key is kept as a fallback in case the chosen one errors out.
        """
        chosen = get_setting("llm_provider")
        if chosen == "local":
            return []
        keyed = [p for p in PROVIDER_ORDER if _get_key(p)]
        if chosen in keyed:
            keyed.remove(chosen)
            keyed.insert(0, chosen)
        return keyed

    def get_active_provider(self) -> str:
        candidates = self._candidate_providers()
        return candidates[0] if candidates else "local"

    def _messages(self, system_prompt: str, context_str: str, query: str,
                  history: Optional[List[Dict[str, str]]]) -> List[Dict[str, str]]:
        messages = [{"role": "system", "content": system_prompt}]
        if history:
            for h in history[-6:]:
                messages.append({"role": h["role"], "content": h["content"]})
        messages.append({
            "role": "user",
            "content": f"College Website Context:\n{context_str}\n\nUser Question: {query}",
        })
        return messages

    def _call_groq(self, key: str, messages: List[Dict[str, str]]) -> str:
        from groq import Groq
        client = Groq(api_key=key, timeout=30)
        kwargs: Dict[str, Any] = {"messages": messages, "model": GROQ_MODEL, "temperature": 0.3}
        if "gpt-oss" in GROQ_MODEL:
            # Reasoning model: its hidden reasoning counts against the token
            # limit, so keep reasoning short and leave room for the answer.
            kwargs["reasoning_effort"] = "low"
            kwargs["max_completion_tokens"] = 2048
        else:
            kwargs["max_completion_tokens"] = 800
        chat_completion = client.chat.completions.create(**kwargs)
        return chat_completion.choices[0].message.content or ""

    def _call_gemini(self, key: str, system_prompt: str, context_str: str, query: str,
                     history: Optional[List[Dict[str, str]]]) -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
        contents = []
        if history:
            for h in history[-6:]:
                role = "user" if h["role"] == "user" else "model"
                contents.append({"role": role, "parts": [{"text": h["content"]}]})
        contents.append({
            "role": "user",
            "parts": [{"text": f"College Website Context:\n{context_str}\n\nUser Question: {query}"}],
        })
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": contents,
            "generationConfig": {"temperature": 0.3, "maxOutputTokens": 2048},
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            # Key goes in a header, not the URL, so it never lands in proxy/server logs.
            headers={"Content-Type": "application/json", "x-goog-api-key": key},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            res_data = json.loads(resp.read().decode("utf-8"))
        parts = res_data["candidates"][0]["content"].get("parts", [])
        return "".join(p.get("text", "") for p in parts)

    def _call_openai(self, key: str, messages: List[Dict[str, str]]) -> str:
        payload = {"model": OPENAI_MODEL, "messages": messages, "temperature": 0.3, "max_tokens": 800}
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            res_data = json.loads(resp.read().decode("utf-8"))
        return res_data["choices"][0]["message"]["content"] or ""

    def generate(self, query: str, chunks: List[Dict[str, Any]],
                 history: Optional[List[Dict[str, str]]] = None) -> Tuple[str, str]:
        """Returns (answer, provider that actually produced it)."""
        context_parts = []
        for i, c in enumerate(chunks[:4]):
            context_parts.append(
                f"[Document {i+1}: {c['title']} | URL: {c['source_url']}]\n{c['text']}\n"
            )
        context_str = "\n".join(context_parts) if context_parts else "(No relevant documents were retrieved for this message.)"
        system_prompt = f"{SYSTEM_PROMPT}\n\n{CHITCHAT_SYSTEM_NOTE}"
        messages = self._messages(system_prompt, context_str, query, history)

        errors = []
        for provider in self._candidate_providers():
            key = _get_key(provider)
            try:
                if provider == "groq":
                    answer = self._call_groq(key, messages)
                elif provider == "gemini":
                    answer = self._call_gemini(key, system_prompt, context_str, query, history)
                else:
                    answer = self._call_openai(key, messages)
                if answer and answer.strip():
                    return answer, provider
                print(f"{provider} returned an empty answer; trying next provider.")
                errors.append(f"{provider}: empty response")
            except Exception as e:
                print(f"{provider} error: {e}")
                errors.append(f"{provider}: {str(e)[:200]}")

        # Local fallback (no API key configured, "local" chosen, or every provider failed).
        # Say which of those it was, so a broken key is not mistaken for "no key".
        if errors:
            note = (
                "Basic mode - the AI model request failed (" + "; ".join(errors) + "), so this is "
                "a direct excerpt instead. Check the API key in Settings and the server console."
            )
        elif get_setting("llm_provider") == "local" and any(_get_key(p) for p in PROVIDER_ORDER):
            note = (
                "Basic mode - Settings is set to 'Local', so the saved API key is not used. "
                "Choose Groq, Gemini or OpenAI in Settings to get written answers."
            )
        else:
            note = NO_MODEL_NOTE
        return generate_local_extractive_answer(query, chunks, note), "local"

    def generate_response(self, query: str, chunks: List[Dict[str, Any]],
                          history: Optional[List[Dict[str, str]]] = None) -> str:
        return self.generate(query, chunks, history)[0]
