from pathlib import Path

from manuali_rag.config import Settings
from manuali_rag.embeddings import HashEmbedder
from manuali_rag.retrieval import Retriever
from manuali_rag.store import ChunkInput, Store


def settings_for(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "test.sqlite3",
        llm_base_url="http://127.0.0.1:8080/v1",
        llm_model="test",
        llm_timeout=1,
        embedding_provider="hash",
        embedding_base_url="http://127.0.0.1:8081/v1",
        embedding_model="hash-dev",
        embedding_timeout=1,
        hash_embedding_dimensions=64,
        render_dpi=72,
        ocr_enabled=False,
        ocr_languages="ita",
        ocr_min_chars=80,
        caption_mode="off",
        max_images_per_question=2,
        chunk_chars=500,
        chunk_overlap_chars=50,
        retrieval_candidates=10,
        default_top_k=3,
    )


def test_hybrid_retrieval_finds_exact_error_code(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    store = Store(settings.database_path)
    embedder = HashEmbedder(64)
    chunks = [
        ChunkInput(
            page=7,
            section="Codici errore",
            content="L'errore E104 indica una pressione insufficiente nel circuito.",
        ),
        ChunkInput(
            page=12,
            section="Manutenzione",
            content="Pulire il filtro una volta ogni sei mesi.",
        ),
    ]
    store.replace_document(
        document_id="doc1",
        checksum="abc",
        source_name="manuale.pdf",
        title="Manuale caldaia",
        markdown_path="documents/doc1/document.md",
        page_count=20,
        warnings=[],
        chunks=chunks,
        embeddings=embedder.embed([chunk.content for chunk in chunks]),
        embedding_model=embedder.model_name,
    )
    hits = Retriever(store, embedder, settings).search("Cosa significa E104?", top_k=1)
    assert len(hits) == 1
    assert hits[0].page == 7
    assert "E104" in hits[0].content
