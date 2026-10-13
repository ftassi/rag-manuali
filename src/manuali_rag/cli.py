from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import uvicorn

from .config import Settings
from .embeddings import build_embedder
from .ingest import Ingestor
from .llm import LLMClient
from .retrieval import AnswerService, Retriever
from .store import Store


def _components(settings: Settings) -> tuple[Store, object, LLMClient]:
    settings.ensure_directories()
    return Store(settings.database_path), build_embedder(settings), LLMClient(settings)


def main() -> None:
    parser = argparse.ArgumentParser(prog="manuali-rag")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser("ingest", help="Indicizza un PDF o Markdown")
    ingest_parser.add_argument("path", type=Path)
    ingest_parser.add_argument("--force", action="store_true")

    ask_parser = subparsers.add_parser("ask", help="Fai una domanda ai manuali")
    ask_parser.add_argument("question")
    ask_parser.add_argument("--top-k", type=int, default=5)
    ask_parser.add_argument("--document-id")
    ask_parser.add_argument("--no-images", action="store_true")

    search_parser = subparsers.add_parser("search", help="Mostra solo le fonti recuperate")
    search_parser.add_argument("question")
    search_parser.add_argument("--top-k", type=int, default=5)

    subparsers.add_parser("documents", help="Elenca i manuali indicizzati")
    subparsers.add_parser("reembed", help="Ricalcola i vettori locali senza reimportare i manuali")

    serve_parser = subparsers.add_parser("serve", help="Avvia API e interfaccia web")
    serve_parser.add_argument("--host", default="0.0.0.0")
    serve_parser.add_argument("--port", type=int, default=8000)

    args = parser.parse_args()
    settings = Settings.from_env()

    if args.command == "serve":
        uvicorn.run("manuali_rag.api:app", host=args.host, port=args.port, reload=False)
        return

    store, embedder, llm = _components(settings)
    retriever = Retriever(store, embedder, settings)  # type: ignore[arg-type]

    if args.command == "reembed":
        import sqlite3
        from datetime import UTC, datetime

        with store.connect() as connection:
            chunks = connection.execute("SELECT id, content FROM chunks ORDER BY id").fetchall()
        vectors = []
        for start in range(0, len(chunks), 16):
            vectors.extend(embedder.embed([row["content"] for row in chunks[start:start + 16]]))
        backup = settings.data_dir / "backups" / (
            "before-reembed-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + ".sqlite3"
        )
        backup.parent.mkdir(parents=True, exist_ok=True)
        with store.connect() as connection, sqlite3.connect(backup) as destination:
            connection.backup(destination)
        from .embeddings import vector_to_blob

        with store.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute("SELECT id, content FROM chunks ORDER BY id").fetchall()
            if [tuple(row) for row in current] != [tuple(row) for row in chunks]:
                raise RuntimeError("Indice modificato durante il calcolo: ripetere reembed")
            connection.executemany(
                "UPDATE embeddings SET model=?, dimensions=?, vector=? WHERE chunk_id=?",
                [(embedder.model_name, len(vector), vector_to_blob(vector), row["id"])
                 for row, vector in zip(chunks, vectors, strict=True)],
            )
        print(json.dumps({"chunks": len(chunks), "backup": str(backup)}))
    elif args.command == "ingest":
        result = Ingestor(settings, store, embedder, llm).ingest(  # type: ignore[arg-type]
            args.path, force=args.force
        )
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    elif args.command == "ask":
        answer = AnswerService(retriever, llm, settings).answer(
            args.question,
            top_k=args.top_k,
            document_id=args.document_id,
            include_images=not args.no_images,
        )
        print(answer.text)
        for index, source in enumerate(answer.sources, start=1):
            print(f"[S{index}] {source.manual_title}, pagina {source.page}: {source.section}")
    elif args.command == "search":
        hits = retriever.search(args.question, top_k=args.top_k)
        print(json.dumps([hit.to_dict() for hit in hits], ensure_ascii=False, indent=2))
    elif args.command == "documents":
        print(json.dumps(store.list_documents(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
