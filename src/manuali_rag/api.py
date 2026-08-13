from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .config import Settings
from .embeddings import build_embedder
from .ingest import Ingestor
from .llm import LLMClient, LLMError
from .retrieval import AnswerService, Retriever
from .store import Store


class SearchRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=12)
    document_id: str | None = None


class QuestionRequest(SearchRequest):
    include_images: bool = True


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.ensure_directories()
    store = Store(settings.database_path)
    embedder = build_embedder(settings)
    llm = LLMClient(settings)
    retriever = Retriever(store, embedder, settings)
    answers = AnswerService(retriever, llm, settings)
    ingestor = Ingestor(settings, store, embedder, llm)

    app = FastAPI(
        title="Manuali RAG",
        version="0.1.0",
        description="Ricerca e domande in italiano su manuali locali PDF e Markdown.",
    )
    app.state.settings = settings
    app.state.store = store
    app.state.retriever = retriever

    static_dir = Path(__file__).parent / "static"

    @app.get("/", include_in_schema=False)
    def home() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    @app.get("/api/health")
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "index": store.counts(),
            "llm": {"url": settings.llm_base_url, "model": settings.llm_model},
            "embeddings": {
                "provider": settings.embedding_provider,
                "url": settings.embedding_base_url,
                "model": embedder.model_name,
            },
        }

    @app.get("/api/documents")
    def documents() -> list[dict[str, object]]:
        return store.list_documents()

    @app.post("/api/documents")
    async def upload_document(file: Annotated[UploadFile, File()]) -> dict[str, object]:
        suffix = Path(file.filename or "").suffix.casefold()
        if suffix not in {".pdf", ".md", ".markdown"}:
            raise HTTPException(415, "Sono accettati soltanto PDF e Markdown")
        safe_name = re.sub(r"[^a-zA-Z0-9._-]+", "-", Path(file.filename or "manuale").name)
        incoming = settings.data_dir / "incoming" / safe_name
        with incoming.open("wb") as destination:
            while block := await file.read(1024 * 1024):
                destination.write(block)
        try:
            result = ingestor.ingest(incoming)
            return {
                "document_id": result.document_id,
                "title": result.title,
                "pages": result.page_count,
                "chunks": result.chunk_count,
                "warnings": result.warnings,
                "already_indexed": result.already_indexed,
            }
        except (ValueError, RuntimeError, LLMError) as exc:
            raise HTTPException(422, str(exc)) from exc
        finally:
            incoming.unlink(missing_ok=True)

    @app.post("/api/search")
    def search(request: SearchRequest) -> dict[str, object]:
        try:
            hits = retriever.search(
                request.question,
                top_k=request.top_k,
                document_id=request.document_id,
            )
        except Exception as exc:
            raise HTTPException(502, f"Ricerca non disponibile: {exc}") from exc
        return {"results": [_source_payload(hit) for hit in hits]}

    @app.post("/api/questions")
    def question(request: QuestionRequest) -> dict[str, object]:
        try:
            answer = answers.answer(
                request.question,
                top_k=request.top_k,
                document_id=request.document_id,
                include_images=request.include_images,
            )
        except LLMError as exc:
            raise HTTPException(502, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(502, f"Generazione non disponibile: {exc}") from exc
        return {
            "answer": answer.text,
            "sources": [_source_payload(hit) for hit in answer.sources],
        }

    @app.get("/api/documents/{document_id}/pages/{page}")
    def page_image(document_id: str, page: int) -> FileResponse:
        document = store.document(document_id)
        if not document:
            raise HTTPException(404, "Manuale non trovato")
        candidate = (
            settings.data_dir / "documents" / document_id / "pages" / f"page-{page:04d}.jpg"
        ).resolve()
        if not candidate.is_relative_to(settings.data_dir) or not candidate.is_file():
            raise HTTPException(404, "Immagine della pagina non disponibile")
        return FileResponse(candidate, media_type="image/jpeg")

    return app


def _source_payload(hit: object) -> dict[str, object]:
    # SearchHit è mantenuto fuori dai modelli HTTP per non accoppiare storage e API.
    payload = hit.to_dict()  # type: ignore[attr-defined]
    if payload["page"]:
        payload["page_url"] = f"/api/documents/{payload['document_id']}/pages/{payload['page']}"
    else:
        payload["page_url"] = None
    return payload


app = create_app()
