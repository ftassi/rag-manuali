from pathlib import Path

from manuali_rag.config import Settings
from manuali_rag.embeddings import HashEmbedder
from manuali_rag.retrieval import (
    AnswerService,
    Retriever,
    _relevant_excerpt,
    _required_identifier,
    _select_answer_sources,
)
from manuali_rag.store import ChunkInput, SearchHit, Store


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
        retrieval_semantic_weight=1.0,
        retrieval_lexical_weight=1.0,
        retrieval_rrf_k=60,
        answer_ambiguity_margin=0.02,
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


def test_lexical_retrieval_ignores_generic_question_words(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    store = Store(settings.database_path)
    embedder = HashEmbedder(64)
    chunks = [
        ChunkInput(page=1, section="Ricambi", content="Il kit compatibile è KX-17B."),
        ChunkInput(page=2, section="Errori", content="Il codice A7 segnala lo scarico ostruito."),
    ]
    store.replace_document(
        document_id="doc1",
        checksum="lexical",
        source_name="manuale.md",
        title="Manuale sintetico",
        markdown_path="",
        page_count=2,
        warnings=[],
        chunks=chunks,
        embeddings=embedder.embed([chunk.content for chunk in chunks]),
        embedding_model=embedder.model_name,
    )

    assert store.lexical_candidates("Qual è il codice del pezzo sostitutivo?", 5) == []
    exact = store.lexical_candidates("Cosa segnala il codice A7?", 5)
    assert len(exact) == 1


def _hit(chunk_id: int, semantic_score: float) -> SearchHit:
    return SearchHit(
        chunk_id=chunk_id,
        document_id=f"doc{chunk_id}",
        manual_title="Test",
        page=chunk_id,
        section="Test",
        content="Test",
        image_path=None,
        visual_summary=None,
        score=1.0,
        semantic_score=semantic_score,
    )


def test_answer_sources_keep_only_clear_winner() -> None:
    hits = [_hit(1, 0.50), _hit(2, 0.30), _hit(3, 0.29)]
    assert _select_answer_sources(hits, 0.02) == hits[:1]


def test_answer_sources_keep_two_when_semantically_ambiguous() -> None:
    hits = [_hit(1, 0.2437), _hit(2, 0.2384), _hit(3, 0.18)]
    assert _select_answer_sources(hits, 0.02) == hits[:2]


def test_relevant_excerpt_preserves_negation_and_opposite_state() -> None:
    content = """Associazione dell'agenda

Selezionare il reparto richiedente.

Attivare l'agenda dal menu principale.

Per apportare modifiche a un'agenda già attivata, procedere come segue.

Riportare temporaneamente l'agenda in stato Inattivo.

Effettuare le modifiche necessarie.

Un'agenda in stato Attivo non può essere modificata."""

    excerpt = _relevant_excerpt(
        content, "In quale stato deve essere un'agenda per poterla modificare?"
    )

    assert "stato Inattivo" in excerpt
    assert "stato Attivo non può essere modificata" in excerpt
    assert "Selezionare il reparto" not in excerpt


def test_required_identifier_detects_truncated_code() -> None:
    hit = _hit(1, 0.5)
    hit.content = "Il kit compatibile è KX-17B."

    assert _required_identifier("Qual è il codice del kit?", [hit], "Il codice è 17B [S1].") == (
        "KX-17B"
    )
    assert (
        _required_identifier("Qual è il codice del kit?", [hit], "Il codice è KX-17B [S1].") is None
    )
    assert _required_identifier("Quale kit è compatibile?", [hit], "Il kit è 17B [S1].") is None


class RecordingLLM:
    def __init__(self) -> None:
        self.user_text = ""

    def complete(self, *, user_text: str, image_paths: list[Path], max_tokens: int) -> str:
        self.user_text = user_text
        self.max_tokens = max_tokens
        return "La pressione è insufficiente [S1]."


def test_answer_prompt_requires_supported_concise_answer(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    store = Store(settings.database_path)
    embedder = HashEmbedder(64)
    chunk = ChunkInput(
        page=7,
        section="Codici errore",
        content="L'errore E104 indica una pressione insufficiente nel circuito.",
    )
    store.replace_document(
        document_id="doc1",
        checksum="abc",
        source_name="manuale.pdf",
        title="Manuale caldaia",
        markdown_path="documents/doc1/document.md",
        page_count=20,
        warnings=[],
        chunks=[chunk],
        embeddings=embedder.embed([chunk.content]),
        embedding_model=embedder.model_name,
    )
    llm = RecordingLLM()

    answer = AnswerService(Retriever(store, embedder, settings), llm, settings).answer(
        "Cosa significa E104?", top_k=1
    )

    assert answer.text == "La pressione è insufficiente [S1]."
    assert "Ometti gli argomenti vicini ma non pertinenti" in llm.user_text
    assert "Non aggiungere spiegazioni, motivazioni" in llm.user_text
    assert "uno stato per cui la fonte dice 'non può' deve essere escluso" in llm.user_text
    assert "non trasformare 'non può' in 'può'" in llm.user_text
    assert "Termina ogni frase o punto" in llm.user_text
    assert "[S1] Manuale: Manuale caldaia; pagina 7" in llm.user_text
    assert llm.max_tokens == 160
