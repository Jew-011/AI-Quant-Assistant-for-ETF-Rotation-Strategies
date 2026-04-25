"""
Pattern 14: Retrieval-Augmented Generation.

Builds a FAISS vector store from the markdown / txt files under ``docs/`` and
exposes a retrieval helper. The embedding layer uses ``langchain-openai``'s
``OpenAIEmbeddings``. Because our LLM proxy (AIHubMix) routes the embedding
endpoint to a supported model, the same API key works.

Design:
- First-time setup: ``build_or_load_rag_index`` reads every file, splits it,
  embeds it, and writes ``docs/rag_index/index.faiss`` + ``index.pkl``.
- Subsequent calls: we load from disk instantly.
- On failure (no network / no embedding model), we fall back to a keyword
  search so the tool still returns useful results in a demo.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from agent.patterns.pattern_log import log_pattern_use

DOCS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "docs")
INDEX_DIR = os.path.join(DOCS_DIR, "rag_index")
os.makedirs(INDEX_DIR, exist_ok=True)

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 200

# Preferred embedding model. AIHubMix supports text-embedding-3-small.
EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")


@dataclass
class RetrievedChunk:
    source: str
    content: str
    score: float

    def to_dict(self) -> dict:
        return {"source": self.source, "content": self.content, "score": self.score}


def _list_source_files() -> list[str]:
    files = []
    for root, _, names in os.walk(DOCS_DIR):
        if "rag_index" in root:
            continue
        for n in names:
            if n.lower().endswith((".md", ".txt")):
                files.append(os.path.join(root, n))
    return files


def _read_chunks() -> list[dict]:
    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter
    except Exception:
        # tiny fallback splitter
        class RecursiveCharacterTextSplitter:  # type: ignore
            def __init__(self, chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP):
                self.cs = chunk_size
                self.co = chunk_overlap

            def split_text(self, text: str) -> list[str]:
                result, i = [], 0
                while i < len(text):
                    result.append(text[i : i + self.cs])
                    i += self.cs - self.co
                return result

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP
    )
    out = []
    for path in _list_source_files():
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception:
            continue
        rel = os.path.relpath(path, DOCS_DIR)
        for i, chunk in enumerate(splitter.split_text(text)):
            out.append({"source": rel, "chunk_id": i, "content": chunk})
    return out


def _faiss_index_path() -> str:
    return os.path.join(INDEX_DIR, "index.faiss")


def build_or_load_rag_index():
    """Returns a FAISS vectorstore, or None if embeddings cannot be obtained."""
    try:
        from langchain_community.vectorstores import FAISS
        from langchain_openai import OpenAIEmbeddings
    except Exception:
        return None

    embeddings = OpenAIEmbeddings(model=EMBED_MODEL)

    if os.path.isfile(_faiss_index_path()):
        try:
            return FAISS.load_local(
                INDEX_DIR, embeddings, allow_dangerous_deserialization=True
            )
        except Exception:
            pass

    chunks = _read_chunks()
    if not chunks:
        return None
    texts = [c["content"] for c in chunks]
    metadatas = [{"source": c["source"], "chunk_id": c["chunk_id"]} for c in chunks]
    try:
        vs = FAISS.from_texts(texts, embedding=embeddings, metadatas=metadatas)
        vs.save_local(INDEX_DIR)
        return vs
    except Exception:
        return None


def search_research_library(
    query: str,
    k: int = 4,
    thread_id: str = "default",
) -> list[RetrievedChunk]:
    """Retrieve top-k chunks relevant to ``query``. Falls back to keyword match."""
    log_pattern_use(thread_id, 14, "RAG", "search_research_library", f"q={query[:60]} k={k}")
    vs = build_or_load_rag_index()
    if vs is not None:
        try:
            docs_and_scores = vs.similarity_search_with_score(query, k=k)
            results = []
            for doc, score in docs_and_scores:
                # FAISS returns L2 distance; lower = better. Convert roughly to similarity.
                sim = 1.0 / (1.0 + float(score))
                results.append(
                    RetrievedChunk(
                        source=doc.metadata.get("source", "?"),
                        content=doc.page_content,
                        score=round(sim, 4),
                    )
                )
            if results:
                return results
        except Exception:
            pass

    # --- Fallback: keyword scan ---
    query_lower = (query or "").lower()
    keywords = [w for w in query_lower.split() if len(w) >= 2]
    scored = []
    for c in _read_chunks():
        text_lower = c["content"].lower()
        hits = sum(1 for kw in keywords if kw in text_lower) + (1 if query_lower in text_lower else 0)
        if hits > 0:
            scored.append((hits, c))
    scored.sort(key=lambda x: -x[0])
    top = scored[:k]
    return [
        RetrievedChunk(source=c["source"], content=c["content"], score=float(hits))
        for hits, c in top
    ]


def rebuild_rag_index() -> dict:
    """Force rebuild. Useful after editing ``docs/``."""
    for fn in os.listdir(INDEX_DIR):
        try:
            os.remove(os.path.join(INDEX_DIR, fn))
        except Exception:
            pass
    vs = build_or_load_rag_index()
    chunks = _read_chunks()
    return {
        "status": "ok" if vs is not None else "fallback-keyword-only",
        "source_files": len(_list_source_files()),
        "chunks": len(chunks),
    }
