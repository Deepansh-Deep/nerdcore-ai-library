"""Turn retrieved passages into an answer. Three modes:

- library: best passages across all books, one answer.
- book: one book only.
- thinkers: the best passage from each book that addresses the question, so
  you can see how Marcus Aurelius, Laozi and Adam Smith differ on it.

With GROQ_API_KEY the model writes the answer but may only use the numbered
passages and must cite them. Citations to passages that don't exist are
stripped. Without a key, the passages themselves are the answer.
"""
from __future__ import annotations

import logging
import re

from .config import get_settings
from .library import BOOKS, Library, Passage, tokenize

log = logging.getLogger(__name__)
MIN_SCORE = 4.0

SYSTEM = """You are a patient guide to classic books. Answer using ONLY the numbered passages.
- Explain the idea in plain modern English first, then support it.
- Cite every claim with the passage number, like [2]. You may quote short phrases from passages.
- If the passages don't address the question, say: "These books don't speak to that directly." and stop.
- Never invent quotes, page numbers or ideas that aren't in the passages.
- Under 170 words."""

THINKERS = """You compare how different classic authors approach one question, using ONLY the numbered passages (one per book).
For each author with a relevant passage write one or two sentences on their view, citing the passage like [3].
Then one closing sentence on the main point of agreement or tension. Skip authors whose passage is off-topic.
Never invent quotes or ideas. Under 220 words."""


def _llm(system: str, user: str) -> str | None:
    s = get_settings()
    if not s.groq_api_key:
        return None
    try:
        from groq import Groq
        r = Groq(api_key=s.groq_api_key).chat.completions.create(
            model=s.groq_model, temperature=0.3, max_tokens=500,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
        return r.choices[0].message.content.strip()
    except Exception as exc:
        log.warning("LLM failed, falling back to passages: %s", exc)
        return None


REWRITE = """Rewrite the user's question as 6 to 12 search keywords in the vocabulary of old English translations
of Marcus Aurelius, Epictetus, Aristotle, Laozi, Sun Tzu and Adam Smith (e.g. "stay calm" -> "tranquillity
undisturbed perturbation"). Output only the keywords, space separated."""


def search_query(question: str) -> str:
    """With an LLM available, add period vocabulary to the query (the original words are always kept)."""
    extra = _llm(REWRITE, question)
    return f"{question} {extra}" if extra and len(extra) < 300 else question


def highlight_terms(question: str) -> list[str]:
    return sorted(set(tokenize(question)), key=len, reverse=True)


def _source(n: int, p: Passage, score: float, top: float) -> dict:
    b = BOOKS[p.book]
    return {"n": n, "book": p.book, "title": b["title"], "author": b["author"], "page": p.page,
            "text": p.text, "relevance": round(score / top, 2)}


def answer(lib: Library, question: str, mode: str = "library", book: str | None = None, history: list[dict] | None = None) -> dict:
    if mode == "book" and book not in BOOKS:
        raise ValueError("Unknown book")
    books = [book] if mode == "book" else None
    hits = lib.search(search_query(question), books=books, k=7 if mode == "thinkers" else 5, per_book=1 if mode == "thinkers" else 2)
    if not hits or hits[0][1] < MIN_SCORE:
        where = BOOKS[book]["title"] if book else "the library"
        return {"answer": f"I couldn't find a passage in {where} that speaks to that. Try rephrasing with the words an old book might use.",
                "sources": [], "mode": "none", "terms": []}
    top = hits[0][1]
    # Drop weak tail matches. Thinkers mode is more lenient so more voices make it in.
    hits = [h for h in hits if h[1] >= top * (0.3 if mode == "thinkers" else 0.4)]
    sources = [_source(i + 1, p, s, top) for i, (p, s) in enumerate(hits)]

    body = "\n\n".join(f"[{s['n']}] {s['author']}, {s['title']}, page {s['page']}:\n{s['text']}" for s in sources)
    convo = ""
    if history:  # short memory so follow-ups like "what about Aristotle?" make sense
        convo = "Earlier in this conversation:\n" + "\n".join(f"{m['role']}: {m['content'][:300]}" for m in history[-4:]) + "\n\n"
    text = _llm(THINKERS if mode == "thinkers" else SYSTEM, f"{convo}Passages:\n{body}\n\nQuestion: {question}")
    if text:
        valid = {str(s["n"]) for s in sources}
        text = re.sub(r"\[(\d+)\]", lambda m: m.group(0) if m.group(1) in valid else "", text)  # drop invented citations
        cited = {int(n) for n in re.findall(r"\[(\d+)\]", text)}
        if mode != "thinkers" and cited:
            sources = [s for s in sources if s["n"] in cited]
        return {"answer": text, "sources": sources, "mode": "llm", "terms": highlight_terms(question)}

    lead = ("Here is how each author touches on it:" if mode == "thinkers"
            else f"The closest passage is from {sources[0]['author']}'s {sources[0]['title']} (page {sources[0]['page']}).")
    return {"answer": lead, "sources": sources, "mode": "passages", "terms": highlight_terms(question)}
