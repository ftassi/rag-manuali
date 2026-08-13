from pathlib import Path

from test_retrieval import settings_for

from manuali_rag.embeddings import HashEmbedder
from manuali_rag.ingest import Ingestor
from manuali_rag.store import Store


def test_ingests_markdown_with_page_metadata(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    settings.ensure_directories()
    source = tmp_path / "manuale-pompa.md"
    source.write_text(
        """# Manuale pompa

<!-- pagina: 3 -->
## Avvio
Aprire la valvola principale prima dell'avvio.

<!-- pagina: 9 -->
## Allarmi
Il codice A12 indica una temperatura elevata.
""",
        encoding="utf-8",
    )
    store = Store(settings.database_path)
    embedder = HashEmbedder(64)
    result = Ingestor(settings, store, embedder).ingest(source)
    assert result.page_count == 3
    assert result.chunk_count >= 2
    documents = store.list_documents()
    assert documents[0]["title"] == "Manuale Pompa"
    assert (tmp_path / documents[0]["markdown_path"]).is_file()
    repeated = Ingestor(settings, store, embedder).ingest(source)
    assert repeated.already_indexed is True


def test_ingests_and_renders_pdf(tmp_path: Path) -> None:
    import pymupdf

    settings = settings_for(tmp_path)
    settings.ensure_directories()
    source = tmp_path / "manuale-valvola.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Valvola principale E104")
    document.save(source)
    document.close()

    store = Store(settings.database_path)
    embedder = HashEmbedder(64)
    result = Ingestor(settings, store, embedder).ingest(source)

    assert result.page_count == 1
    assert result.chunk_count == 1
    page_image = tmp_path / "documents" / result.document_id / "pages" / "page-0001.jpg"
    assert page_image.is_file()
