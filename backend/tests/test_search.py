from nerdcore.answer import answer
from nerdcore.library import BOOKS, expand, split_passages


def top_books(lib, q, k=3, **kw):
    return [p.book for p, _ in lib.search(q, k=k, **kw)]


def test_all_books_indexed(lib):
    assert set(lib.page_counts) == set(BOOKS)
    assert len(lib.passages) > 5000


def test_classic_questions_find_the_right_author(lib):
    assert top_books(lib, "the Tao that can be named")[0] == "tao_te_ching"
    assert top_books(lib, "division of labour pin manufacture")[0] == "wealth_of_nations"
    assert "art_of_war" in top_books(lib, "know the enemy and know yourself")
    assert top_books(lib, "things in our power and not in our power")[0] in {"enchiridion", "meditations"}


def test_editorial_matter_is_not_searched(lib):
    # Endnotes and introductions sit outside each book's text_pages range.
    for p in lib.passages:
        lo, hi = BOOKS[p.book]["text_pages"]
        assert lo <= p.page <= hi
        assert p.text.count("↩") < 2


def test_thesaurus_bridges_modern_words():
    terms = dict(expand("how do I stay calm"))
    assert terms["calm"] == 1.0 and terms.get("tranquil") == 0.5


def test_book_filter(lib):
    assert set(top_books(lib, "virtue and happiness", k=5, books=["meditations"])) == {"meditations"}


def test_thinkers_mode_returns_one_passage_per_author(lib):
    r = answer(lib, "What makes a good friend?", mode="thinkers")
    books = [s["book"] for s in r["sources"]]
    assert len(books) == len(set(books)) >= 4


def test_irrelevant_question_is_refused(lib):
    r = answer(lib, "zxqv blorp", mode="library")
    assert r["mode"] == "none" and r["sources"] == []


def test_passages_keep_single_page():
    pages = [{"book": "meditations", "page": 7, "text": "First idea here.\n\nSecond idea. " * 80}]
    out = split_passages(pages, size=300)
    assert len(out) > 3 and all(p.page == 7 for p in out) and max(len(p.text) for p in out) < 300 * 1.7
