"""NerdCore API. Run: uvicorn nerdcore.api:app --reload  (then open http://localhost:8000)"""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .answer import answer
from .config import get_settings
from .history import History
from .library import BOOKS, Library

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("nerdcore")
settings = get_settings()
state: dict = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    t = time.perf_counter()
    state["lib"] = Library(settings.corpus_path)
    state["history"] = History(settings.db_path)
    state["load_s"] = round(time.perf_counter() - t, 2)
    log.info("Indexed %d passages from %d books in %.1fs", len(state["lib"].passages), len(BOOKS), state["load_s"])
    yield


app = FastAPI(title="NerdCore", version=__version__, lifespan=lifespan,
              description="Ask seven classic books anything. Every answer cites the page it came from.")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins.split(","), allow_methods=["*"], allow_headers=["*"])


def lib() -> Library:
    return state["lib"]


def hist() -> History:
    return state["history"]


def owner(x_reader_id: str | None) -> str:
    if not x_reader_id or not (8 <= len(x_reader_id) <= 64):
        raise HTTPException(400, "Missing X-Reader-Id header")
    return x_reader_id


@app.get("/api/health")
def health():
    L = state.get("lib")
    ok = bool(L and L.passages)
    return {"status": "ok" if ok else "loading", "version": __version__, "books": len(BOOKS),
            "pages": sum(L.page_counts.values()) if L else 0, "passages": len(L.passages) if L else 0,
            "index_load_seconds": state.get("load_s"), "llm": bool(settings.groq_api_key)}


@app.get("/api/books")
def books():
    L = lib()
    return [{"slug": k, **v, "pages": L.page_counts.get(k, 0)} for k, v in BOOKS.items()]


@app.get("/api/books/{slug}/pages/{page}")
def read_page(slug: str, page: int):
    text = lib().page(slug, page)
    if text is None:
        raise HTTPException(404, "Page not found")
    return {"book": slug, **BOOKS[slug], "page": page, "text": text,
            "prev": page - 1 if lib().page(slug, page - 1) else None, "next": page + 1 if lib().page(slug, page + 1) else None}


class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    mode: Literal["library", "book", "thinkers"] = "library"
    book: str | None = None
    conversation_id: str | None = None


@app.post("/api/ask")
def ask(body: AskIn, x_reader_id: str | None = Header(None)):
    me = owner(x_reader_id)
    H = hist()
    if body.conversation_id:
        conv = H.get(me, body.conversation_id)
        if not conv:
            raise HTTPException(404, "Conversation not found")
        cid, prior = conv["id"], H.messages(conv["id"])
    else:
        cid, prior = H.create(me, body.question, body.mode, body.book), []
    try:
        r = answer(lib(), body.question, body.mode, body.book,
                   history=[{"role": m["role"], "content": m["content"]} for m in prior])
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    H.add(cid, "user", body.question)
    H.add(cid, "assistant", r["answer"], r["sources"])
    return {**r, "conversation_id": cid}


@app.get("/api/conversations")
def conversations(q: str | None = None, x_reader_id: str | None = Header(None)):
    return hist().list(owner(x_reader_id), q)


@app.get("/api/conversations/{cid}")
def conversation(cid: str, x_reader_id: str | None = Header(None)):
    me = owner(x_reader_id)
    conv = hist().get(me, cid)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    return {**dict(conv), "messages": hist().messages(cid)}


class Rename(BaseModel):
    title: str = Field(min_length=1, max_length=80)


@app.patch("/api/conversations/{cid}")
def rename(cid: str, body: Rename, x_reader_id: str | None = Header(None)):
    if not hist().rename(owner(x_reader_id), cid, body.title):
        raise HTTPException(404, "Conversation not found")
    return {"ok": True}


@app.delete("/api/conversations/{cid}", status_code=204)
def delete(cid: str, x_reader_id: str | None = Header(None)):
    if not hist().delete(owner(x_reader_id), cid):
        raise HTTPException(404, "Conversation not found")


if settings.frontend_dir.exists():
    app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True), name="frontend")
