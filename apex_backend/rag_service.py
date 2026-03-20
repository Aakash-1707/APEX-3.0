"""
APEX RAG Service — Historical Strategy Knowledge Base
=====================================================
ChromaDB-backed vector store for historical F1 strategy data.
Provides context retrieval for the LLM strategy assistant.

Usage:
    rag = RAGService()
    rag.ingest_from_file("strategy_data/historical_strategies.json")
    context = rag.query("What tyre strategy works best at Monaco?", n=5)
"""

import os
import json
from typing import Optional

_CHROMA_AVAILABLE = False
try:
    import chromadb
    from chromadb.config import Settings
    _CHROMA_AVAILABLE = True
except ImportError:
    pass

PERSIST_DIR = os.path.join(os.path.dirname(__file__), "strategy_data", "chroma_db")
COLLECTION_NAME = "f1_strategies"


class RAGService:
    """Manages the F1 strategy knowledge base with ChromaDB."""

    def __init__(self):
        self.client = None
        self.collection = None
        if _CHROMA_AVAILABLE:
            try:
                self.client = chromadb.Client(Settings(
                    persist_directory=PERSIST_DIR,
                    anonymized_telemetry=False,
                    is_persistent=True,
                ))
                self.collection = self.client.get_or_create_collection(
                    name=COLLECTION_NAME,
                    metadata={"hnsw:space": "cosine"},
                )
            except Exception as e:
                print(f"RAG: ChromaDB init failed ({e}), running without vector store")

    @property
    def available(self) -> bool:
        return self.collection is not None

    def ingest_from_file(self, filepath: str) -> int:
        """Ingest historical strategies from a JSON file. Returns count ingested."""
        if not self.available:
            return 0
        if not os.path.exists(filepath):
            return 0

        with open(filepath) as f:
            data = json.load(f)

        entries = data if isinstance(data, list) else data.get("strategies", [])
        if not entries:
            return 0

        ids, documents, metadatas = [], [], []
        for i, entry in enumerate(entries):
            doc_id = entry.get("id", f"strat_{i}")
            text = self._entry_to_text(entry)
            meta = {
                "circuit": entry.get("circuit", ""),
                "year": str(entry.get("year", "")),
                "type": entry.get("type", "race_strategy"),
                "source": entry.get("source", "historical"),
            }
            ids.append(doc_id)
            documents.append(text)
            metadatas.append(meta)

        existing = set(self.collection.get()["ids"])
        new_ids, new_docs, new_metas = [], [], []
        for id_, doc, meta in zip(ids, documents, metadatas):
            if id_ not in existing:
                new_ids.append(id_)
                new_docs.append(doc)
                new_metas.append(meta)

        if new_ids:
            self.collection.add(ids=new_ids, documents=new_docs, metadatas=new_metas)

        return len(new_ids)

    def ingest_race_result(self, circuit: str, year: int, driver: str,
                           strategy: list[dict], position: int,
                           conditions: str = "dry", notes: str = "") -> bool:
        """Ingest a single race result into the knowledge base."""
        if not self.available:
            return False

        stints_str = " → ".join(
            f"{s['compound']}({s.get('laps', '?')} laps)" for s in strategy)
        text = (f"{year} {circuit}: {driver} finished P{position} using {stints_str}. "
                f"Conditions: {conditions}. {notes}")

        doc_id = f"result_{year}_{circuit}_{driver}".replace(" ", "_").lower()
        existing = set(self.collection.get()["ids"])
        if doc_id in existing:
            return False

        self.collection.add(
            ids=[doc_id],
            documents=[text],
            metadatas=[{
                "circuit": circuit,
                "year": str(year),
                "type": "race_result",
                "driver": driver,
                "position": str(position),
            }],
        )
        return True

    def query(self, question: str, n: int = 5,
              circuit_filter: Optional[str] = None) -> list[dict]:
        """Retrieve relevant strategy context for a query."""
        if not self.available:
            return []

        where = None
        if circuit_filter:
            where = {"circuit": circuit_filter}

        try:
            results = self.collection.query(
                query_texts=[question],
                n_results=min(n, self.collection.count() or 1),
                where=where if where else None,
            )
        except Exception:
            try:
                results = self.collection.query(
                    query_texts=[question],
                    n_results=min(n, self.collection.count() or 1),
                )
            except Exception:
                return []

        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        context = []
        for doc, meta, dist in zip(docs, metas, distances):
            context.append({
                "text": doc,
                "metadata": meta,
                "relevance": round(1 - dist, 3) if dist < 2 else 0,
            })
        return context

    def get_stats(self) -> dict:
        if not self.available:
            return {"available": False, "count": 0}
        return {
            "available": True,
            "count": self.collection.count(),
            "persist_dir": PERSIST_DIR,
        }

    def _entry_to_text(self, entry: dict) -> str:
        """Convert a strategy entry dict to searchable text."""
        parts = []
        if entry.get("circuit"):
            parts.append(f"Circuit: {entry['circuit']}.")
        if entry.get("year"):
            parts.append(f"Year: {entry['year']}.")
        if entry.get("description"):
            parts.append(entry["description"])
        if entry.get("typical_strategy"):
            parts.append(f"Typical strategy: {entry['typical_strategy']}.")
        if entry.get("key_factors"):
            parts.append(f"Key factors: {', '.join(entry['key_factors'])}.")
        if entry.get("notes"):
            parts.append(entry["notes"])
        if entry.get("winner"):
            parts.append(f"Winner: {entry['winner']}.")
        if entry.get("winning_strategy"):
            parts.append(f"Winning strategy: {entry['winning_strategy']}.")
        return " ".join(parts)


_rag_instance: Optional[RAGService] = None


def get_rag() -> RAGService:
    """Singleton accessor for the RAG service."""
    global _rag_instance
    if _rag_instance is None:
        _rag_instance = RAGService()
        seed_path = os.path.join(
            os.path.dirname(__file__), "strategy_data", "historical_strategies.json")
        if os.path.exists(seed_path):
            count = _rag_instance.ingest_from_file(seed_path)
            if count > 0:
                print(f"RAG: Ingested {count} historical strategy entries")
    return _rag_instance
