import json
import sqlite3

from manuali_rag import cli
from manuali_rag.config import Settings
from manuali_rag.embeddings import HashEmbedder, blob_to_vector
from manuali_rag.store import ChunkInput, Store


def test_reembed_preserves_sources_and_backups_previous_vectors(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MANUALI_DATA_DIR", str(tmp_path))
    settings = Settings.from_env()
    store = Store(settings.database_path)
    embedder = HashEmbedder(32)
    chunk = ChunkInput(page=8, section="Archivio", content="Premere Archivia.", image_path="p8.jpg")
    store.replace_document(
        document_id="synthetic", checksum="checksum", source_name="manuale.pdf", title="Esempio",
        markdown_path="manuale.md", page_count=8, warnings=[], chunks=[chunk],
        embeddings=[[1.0, 0.0]], embedding_model="previous-model",
    )
    with store.connect() as connection:
        before = tuple(connection.execute("SELECT * FROM chunks").fetchone())
    monkeypatch.setattr(cli, "_components", lambda _: (store, embedder, None))
    monkeypatch.setattr(cli.Settings, "from_env", lambda: settings)
    monkeypatch.setattr("sys.argv", ["manuali-rag", "reembed"])
    cli.main()
    result = json.loads(capsys.readouterr().out)
    assert result["chunks"] == 1
    with store.connect() as connection:
        assert tuple(connection.execute("SELECT * FROM chunks").fetchone()) == before
        vector = connection.execute("SELECT model,vector FROM embeddings").fetchone()
        assert vector["model"] == "hash-dev"
        assert len(blob_to_vector(vector["vector"])) == 32
    with sqlite3.connect(result["backup"]) as connection:
        assert connection.execute("SELECT model FROM embeddings").fetchone()[0] == "previous-model"
