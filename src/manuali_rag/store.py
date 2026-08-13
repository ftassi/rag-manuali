from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .embeddings import blob_to_vector, vector_to_blob


@dataclass(slots=True)
class ChunkInput:
    page: int | None
    section: str
    content: str
    image_path: str | None = None
    visual_summary: str | None = None


@dataclass(slots=True)
class SearchHit:
    chunk_id: int
    document_id: str
    manual_title: str
    page: int | None
    section: str
    content: str
    image_path: str | None
    visual_summary: str | None
    score: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Store:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    checksum TEXT NOT NULL UNIQUE,
                    source_name TEXT NOT NULL,
                    title TEXT NOT NULL,
                    markdown_path TEXT,
                    page_count INTEGER NOT NULL DEFAULT 0,
                    warnings_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    page INTEGER,
                    section TEXT NOT NULL,
                    content TEXT NOT NULL,
                    image_path TEXT,
                    visual_summary TEXT
                );

                CREATE TABLE IF NOT EXISTS embeddings (
                    chunk_id INTEGER PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
                    model TEXT NOT NULL,
                    dimensions INTEGER NOT NULL,
                    vector BLOB NOT NULL
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                    chunk_id UNINDEXED,
                    manual_title,
                    section,
                    content,
                    tokenize='unicode61 remove_diacritics 2'
                );
                """
            )

    def document_by_checksum(self, checksum: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT d.*, COUNT(c.id) AS chunk_count
                FROM documents d
                LEFT JOIN chunks c ON c.document_id = d.id
                WHERE d.checksum = ?
                GROUP BY d.id
                """,
                (checksum,),
            ).fetchone()
        return self._document_dict(row) if row else None

    def document(self, document_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM documents WHERE id = ?", (document_id,)
            ).fetchone()
        return self._document_dict(row) if row else None

    def list_documents(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT d.*, COUNT(c.id) AS chunk_count
                FROM documents d
                LEFT JOIN chunks c ON c.document_id = d.id
                GROUP BY d.id
                ORDER BY d.created_at DESC
                """
            ).fetchall()
        return [self._document_dict(row) for row in rows]

    @staticmethod
    def _document_dict(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["warnings"] = json.loads(result.pop("warnings_json", "[]"))
        return result

    def replace_document(
        self,
        *,
        document_id: str,
        checksum: str,
        source_name: str,
        title: str,
        markdown_path: str,
        page_count: int,
        warnings: list[str],
        chunks: list[ChunkInput],
        embeddings: list[list[float]],
        embedding_model: str,
    ) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("Il numero di chunk e embedding non coincide")

        with self.connect() as connection:
            old_ids = connection.execute(
                "SELECT id FROM chunks WHERE document_id = ?", (document_id,)
            ).fetchall()
            if old_ids:
                placeholders = ",".join("?" for _ in old_ids)
                connection.execute(
                    f"DELETE FROM chunks_fts WHERE chunk_id IN ({placeholders})",
                    tuple(row["id"] for row in old_ids),
                )
            connection.execute("DELETE FROM documents WHERE id = ?", (document_id,))
            connection.execute(
                """
                INSERT INTO documents(
                    id, checksum, source_name, title, markdown_path,
                    page_count, warnings_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    checksum,
                    source_name,
                    title,
                    markdown_path,
                    page_count,
                    json.dumps(warnings, ensure_ascii=False),
                    datetime.now(UTC).isoformat(),
                ),
            )

            for chunk, vector in zip(chunks, embeddings, strict=True):
                cursor = connection.execute(
                    """
                    INSERT INTO chunks(
                        document_id, page, section, content, image_path, visual_summary
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document_id,
                        chunk.page,
                        chunk.section,
                        chunk.content,
                        chunk.image_path,
                        chunk.visual_summary,
                    ),
                )
                chunk_id = int(cursor.lastrowid)
                connection.execute(
                    "INSERT INTO chunks_fts(chunk_id, manual_title, section, content) VALUES (?, ?, ?, ?)",
                    (chunk_id, title, chunk.section, chunk.content),
                )
                connection.execute(
                    "INSERT INTO embeddings(chunk_id, model, dimensions, vector) VALUES (?, ?, ?, ?)",
                    (chunk_id, embedding_model, len(vector), vector_to_blob(vector)),
                )

    def lexical_candidates(
        self, query: str, limit: int, document_id: str | None = None
    ) -> list[int]:
        terms = [part.replace('"', "") for part in query.casefold().split() if part.strip()]
        terms = [term for term in terms if any(character.isalnum() for character in term)]
        if not terms:
            return []
        expression = " OR ".join(f'"{term}"*' for term in terms[:20])
        params: list[Any] = [expression]
        document_filter = ""
        if document_id:
            document_filter = " AND c.document_id = ?"
            params.append(document_id)
        params.append(limit)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT c.id
                FROM chunks_fts f
                JOIN chunks c ON c.id = f.chunk_id
                WHERE chunks_fts MATCH ? {document_filter}
                ORDER BY bm25(chunks_fts)
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [int(row["id"]) for row in rows]

    def vector_candidates(
        self,
        query_vector: list[float],
        limit: int,
        document_id: str | None = None,
    ) -> list[int]:
        params: list[Any] = []
        where = ""
        if document_id:
            where = "WHERE c.document_id = ?"
            params.append(document_id)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT e.chunk_id, e.vector, e.dimensions
                FROM embeddings e
                JOIN chunks c ON c.id = e.chunk_id
                {where}
                """,
                params,
            ).fetchall()

        scored: list[tuple[float, int]] = []
        for row in rows:
            if row["dimensions"] != len(query_vector):
                continue
            vector = blob_to_vector(row["vector"])
            score = sum(a * b for a, b in zip(query_vector, vector, strict=True))
            scored.append((score, int(row["chunk_id"])))
        scored.sort(reverse=True)
        return [chunk_id for _, chunk_id in scored[:limit]]

    def get_hits(self, ranked: list[tuple[int, float]]) -> list[SearchHit]:
        if not ranked:
            return []
        ids = [chunk_id for chunk_id, _ in ranked]
        placeholders = ",".join("?" for _ in ids)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT c.*, d.title AS manual_title
                FROM chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE c.id IN ({placeholders})
                """,
                ids,
            ).fetchall()
        by_id = {int(row["id"]): row for row in rows}
        return [
            SearchHit(
                chunk_id=chunk_id,
                document_id=by_id[chunk_id]["document_id"],
                manual_title=by_id[chunk_id]["manual_title"],
                page=by_id[chunk_id]["page"],
                section=by_id[chunk_id]["section"],
                content=by_id[chunk_id]["content"],
                image_path=by_id[chunk_id]["image_path"],
                visual_summary=by_id[chunk_id]["visual_summary"],
                score=score,
            )
            for chunk_id, score in ranked
            if chunk_id in by_id
        ]

    def counts(self) -> dict[str, int]:
        with self.connect() as connection:
            documents = connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            chunks = connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        return {"documents": int(documents), "chunks": int(chunks)}
