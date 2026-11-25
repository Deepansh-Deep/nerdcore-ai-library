from conftest import H


def test_health_is_real(client):
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["books"] == 7 and h["passages"] > 5000 and h["llm"] is False


def test_ask_creates_conversation_with_history(client):
    r = client.post("/api/ask", json={"question": "What is happiness?"}, headers=H).json()
    assert r["sources"] and r["conversation_id"]
    r2 = client.post("/api/ask", json={"question": "And friendship?", "conversation_id": r["conversation_id"]}, headers=H).json()
    assert r2["conversation_id"] == r["conversation_id"]
    conv = client.get(f"/api/conversations/{r['conversation_id']}", headers=H).json()
    assert [m["role"] for m in conv["messages"]] == ["user", "assistant", "user", "assistant"]
    assert conv["messages"][1]["sources"][0]["page"]


def test_conversations_are_private(client):
    cid = client.post("/api/ask", json={"question": "What is virtue?"}, headers=H).json()["conversation_id"]
    other = {"X-Reader-Id": "someone-else-999"}
    assert client.get(f"/api/conversations/{cid}", headers=other).status_code == 404
    assert client.get("/api/conversations", headers=other).json() == []


def test_history_search_rename_delete(client):
    cid = client.post("/api/ask", json={"question": "What is courage?"}, headers=H).json()["conversation_id"]
    assert client.get("/api/conversations?q=courage", headers=H).json()[0]["id"] == cid
    assert client.patch(f"/api/conversations/{cid}", json={"title": "Courage"}, headers=H).status_code == 200
    assert client.delete(f"/api/conversations/{cid}", headers=H).status_code == 204
    assert client.get(f"/api/conversations/{cid}", headers=H).status_code == 404


def test_book_mode_validation(client):
    assert client.post("/api/ask", json={"question": "war", "mode": "book", "book": "nope"}, headers=H).status_code == 422
    r = client.post("/api/ask", json={"question": "deception in war", "mode": "book", "book": "art_of_war"}, headers=H).json()
    assert {s["book"] for s in r["sources"]} == {"art_of_war"}


def test_reader_and_header_required(client):
    assert client.post("/api/ask", json={"question": "virtue"}).status_code == 400
    p = client.get("/api/books/meditations/pages/10").json()
    assert p["prev"] == 9 and p["text"]
    assert client.get("/api/books/meditations/pages/9999").status_code == 404
