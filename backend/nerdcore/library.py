"""The book collection: metadata, page-aware chunks and BM25 search."""
from __future__ import annotations

import gzip
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

BOOKS = {
    "meditations": {"text_pages": (4, 126), "title": "Meditations", "author": "Marcus Aurelius", "year": "c. 170 AD", "tradition": "Stoicism", "color": "#c08552"},
    "enchiridion": {"text_pages": (4, 98), "title": "Enchiridion", "author": "Epictetus", "year": "c. 125 AD", "tradition": "Stoicism", "color": "#8c6a4f"},
    "nicomachean_ethics": {"text_pages": (8, 271), "title": "Nicomachean Ethics", "author": "Aristotle", "year": "c. 340 BC", "tradition": "Greek ethics", "color": "#5b7c99"},
    "tao_te_ching": {"text_pages": (45, 128), "title": "Tao Te Ching", "author": "Laozi", "year": "c. 400 BC", "tradition": "Taoism", "color": "#6b8f71"},
    "art_of_war": {"text_pages": (49, 92), "title": "The Art of War", "author": "Sun Tzu", "year": "c. 500 BC", "tradition": "Strategy", "color": "#a14d4d"},
    "theory_of_moral_sentiments": {"text_pages": (9, 463), "title": "The Theory of Moral Sentiments", "author": "Adam Smith", "year": "1759", "tradition": "Moral philosophy", "color": "#7a6aa8"},
    "wealth_of_nations": {"text_pages": (43, 1078), "title": "The Wealth of Nations", "author": "Adam Smith", "year": "1776", "tradition": "Economics", "color": "#b8963e"},
}

_TOK = re.compile(r"[a-z]+")
_STOP = set("""a an the of to in on for and or is are was were be been by with as at from that this these those it its
he she they them his her their we our you your i me my not no but if so than then there what which who whom whose
how when where why do does did can could would should shall will may might must have has had into upon unto also
any all such very more most other some one only own same too just about against between through during before after
above below up down out off over under again further once here both each few nor ye thee thou thy hath doth
make makes made let say said get got thing things way like much many well even yet still""".split())


def stem(t: str) -> str:
    for suf in ("ings", "ing", "edly", "ed", "ies", "es", "s", "ly"):
        if len(t) > len(suf) + 3 and t.endswith(suf):
            return t[: -len(suf)] + ("y" if suf == "ies" else "")
    return t


def tokenize(text: str) -> list[str]:
    return [stem(t) for t in _TOK.findall(text.lower()) if t not in _STOP and len(t) > 2]


# Modern words people type -> the vocabulary these translations actually use.
# Lexical search can't bridge "stay calm" to "tranquillity" on its own; this does, transparently.
THESAURUS = {
    "calm": "tranquil tranquillity undisturbed perturbation equanimity composure serene",
    "stress": "perturbation disturbed trouble anxiety", "anxiety": "fear perturbation disturbed trouble",
    "anger": "anger angry wrath passion resentment", "angry": "anger wrath passion resentment",
    "happy": "happiness happy blessed felicity eudaemonia", "happiness": "felicity blessed eudaemonia flourishing",
    "friend": "friendship friends affection", "friends": "friendship affection",
    "leader": "ruler sovereign prince general king governor", "leadership": "ruler sovereign general govern",
    "boss": "ruler master", "money": "wealth riches money stock capital", "rich": "wealth riches opulence",
    "work": "labour industry employment", "job": "labour employment trade", "salary": "wages",
    "death": "death die dying mortal", "die": "death dying", "fear": "fear afraid dread",
    "wrong": "misfortune adversity evil", "failure": "misfortune adversity defeat", "problem": "misfortune difficulty",
    "win": "victory conquer", "fight": "battle war fighting", "enemy": "enemy foe adversary",
    "good": "virtue good", "moral": "virtue moral ethics", "kind": "kindness benevolence",
    "control": "power within our power", "change": "change transformation", "simple": "simplicity",
    "trade": "commerce trade exchange", "price": "price value", "market": "market exchange",
}


def expand(query: str) -> list[tuple[str, float]]:
    """Query tokens with weights: the user's own words count fully, thesaurus additions count half."""
    base = tokenize(query)
    out = {t: 1.0 for t in base}
    for word in re.findall(r"[a-z]+", query.lower()):
        for extra in tokenize(THESAURUS.get(word, "")):
            out.setdefault(extra, 0.5)
    return list(out.items())


_CJK = re.compile(r"[\u2e80-\u9fff]")


def is_editorial(text: str) -> bool:
    """Footnote blocks and Chinese commentary that slipped inside the main-text range."""
    return text.count("↩") >= 2 or len(_CJK.findall(text)) > 6


@dataclass
class Passage:
    id: int
    book: str
    page: int
    text: str


def split_passages(pages: list[dict], size: int = 900) -> list[Passage]:
    """Paragraph-aware chunks that never cross a page, so every citation has one page number."""
    out: list[Passage] = []
    for p in pages:
        # Small-caps headings extract as letter soup ("T E HE ND I"); drop runs of lone capitals.
        text = re.sub(r"\b(?:[A-Z][,.]? ){3,}(?:[A-Z]\b)?", " ", p["text"])
        paras = [re.sub(r"\s*\n\s*", " ", x).strip() for x in re.split(r"\n\s*\n|(?<=[.!?\"”])\n(?=[A-Z“\"IVXL])", text)]
        buf = ""
        for para in filter(None, paras):
            if buf and len(buf) + len(para) > size:
                out.append(Passage(len(out), p["book"], p["page"], buf))
                buf = ""
            buf = f"{buf} {para}".strip()
            while len(buf) > size * 1.6:  # very long paragraph: cut at a sentence boundary
                cut = buf.rfind(". ", 0, size) + 1 or size
                out.append(Passage(len(out), p["book"], p["page"], buf[:cut].strip()))
                buf = buf[cut:].strip()
        if len(buf) > 60:
            out.append(Passage(len(out), p["book"], p["page"], buf))
    return out


class Library:
    def __init__(self, corpus: Path, k1: float = 1.3, b: float = 0.7):
        pages = []
        with gzip.open(corpus, "rt", encoding="utf-8") as fh:
            for line in fh:
                row = json.loads(line)
                if row["book"] in BOOKS:
                    pages.append(row)
        self.pages = {(p["book"], p["page"]): p["text"] for p in pages}
        self.page_counts = Counter(p["book"] for p in pages)
        # Search only the author's own text: skip introductions, editors' notes and endnotes.
        body = [p for p in pages if BOOKS[p["book"]]["text_pages"][0] <= p["page"] <= BOOKS[p["book"]]["text_pages"][1]]
        self.passages = [p for p in split_passages(body) if not is_editorial(p.text)]
        for i, p in enumerate(self.passages):
            p.id = i
        self.k1, self.b = k1, b
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        self.lengths: list[int] = []
        for psg in self.passages:
            tf = Counter(tokenize(psg.text))
            self.lengths.append(sum(tf.values()))
            for term, f in tf.items():
                self.postings[term].append((psg.id, f))
        self.avg = sum(self.lengths) / max(1, len(self.lengths))

    def search(self, query: str, books: list[str] | None = None, k: int = 6, per_book: int | None = None) -> list[tuple[Passage, float]]:
        n = len(self.passages)
        scores: dict[int, float] = defaultdict(float)
        allowed = set(books) if books else None
        weighted = expand(query)
        q = [t for t, w in weighted if w == 1.0]
        for term, weight in weighted:
            plist = self.postings.get(term)
            if not plist:
                continue
            idf = math.log(1 + (n - len(plist) + 0.5) / (len(plist) + 0.5))
            for pid, f in plist:
                if allowed and self.passages[pid].book not in allowed:
                    continue
                dl = self.lengths[pid]
                scores[pid] += weight * idf * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self.avg))
        # Re-rank the top candidates: reward covering more of the user's words,
        # and reward exact phrases ("division of labour") appearing as written.
        bigrams = set(zip(q, q[1:]))
        for pid, _ in sorted(scores.items(), key=lambda x: -x[1])[:300]:
            seq = tokenize(self.passages[pid].text)
            toks = set(seq)
            bonus = 0.3 * sum(t in toks for t in q) / max(1, len(q))
            if bigrams:
                bonus += 0.6 * len(bigrams & set(zip(seq, seq[1:]))) / len(bigrams)
            scores[pid] *= 1 + bonus
        ranked = sorted(scores.items(), key=lambda x: -x[1])
        out, seen = [], Counter()
        for pid, s in ranked:
            p = self.passages[pid]
            if per_book and seen[p.book] >= per_book:
                continue
            seen[p.book] += 1
            out.append((p, s))
            if len(out) >= k:
                break
        return out

    def page(self, book: str, page: int) -> str | None:
        return self.pages.get((book, page))
