import json
from dataclasses import replace
from pathlib import Path

import pytest

from manuali_rag.config import Settings
from manuali_rag.embeddings import HashEmbedder
from manuali_rag.retrieval import (
    AnswerService,
    Retriever,
    _candidate_indices,
    _complete_list_selection,
    _complete_paragraph_selection,
    _credential_value_supported,
    _grounded_answer,
    _needs_clarification,
    _page_context,
    _selected_quotes,
    _procedure_selection,
    _relevant_excerpt,
    _required_identifier,
    _select_answer_sources,
    _semantic_selection,
    _source_sentences,
    _strong_lexical_match,
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


class FixedEmbedder:
    model_name = "fixed"

    def embed(self, texts) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


def test_precise_lexical_winner_survives_wrong_semantic_ranking(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    store = Store(settings.database_path)
    chunks = [
        ChunkInput(
            page=11,
            section="Login",
            content="Dopo un'autenticazione riuscita selezionare il reparto abilitato.",
        ),
        ChunkInput(
            page=190,
            section="Privacy",
            content="L'operatore accede allo storico del reparto.",
        ),
    ]
    store.replace_document(
        document_id="long-manual",
        checksum="long-manual",
        source_name="manuale.pdf",
        title="Manuale lungo",
        markdown_path="",
        page_count=200,
        warnings=[],
        chunks=chunks,
        embeddings=[[0.0, 1.0], [1.0, 0.0]],
        embedding_model="fixed",
    )

    hits = Retriever(store, FixedEmbedder(), settings).search(
        "Cosa selezionare dopo un'autenticazione riuscita?", top_k=2
    )

    assert [hit.page for hit in hits] == [11, 190]


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


def test_lexical_match_requires_more_than_a_shared_generic_verb() -> None:
    assert not _strong_lexical_match(
        "Quale forza di rotazione va applicata al fissaggio?",
        "Applicare grasso al silicone sulle guarnizioni una volta all'anno.",
    )
    assert _strong_lexical_match(
        "Cosa selezionare dopo un'autenticazione riuscita?",
        "Dopo un'autenticazione riuscita selezionare il reparto abilitato.",
    )
    assert _strong_lexical_match("Cosa significa e104?", "Il codice E104 indica bassa pressione.")
    assert _strong_lexical_match("Filtro", "Pulire il filtro ogni sei mesi.")


def test_answer_sources_keep_two_when_semantically_ambiguous() -> None:
    hits = [_hit(1, 0.2437), _hit(2, 0.2384), _hit(3, 0.18)]
    assert _select_answer_sources(hits, 0.02) == hits[:2]


def test_answer_sources_respect_clear_hybrid_winner() -> None:
    hits = [_hit(1, 0.33), _hit(2, 0.34)]
    hits[0].score = 0.045
    hits[1].score = 0.030
    assert _select_answer_sources(hits, 0.02) == hits[:1]


def test_answer_sources_do_not_treat_reversed_semantic_gap_as_tie() -> None:
    hits = [_hit(1, 0.20), _hit(2, 0.50)]
    assert _select_answer_sources(hits, 0.02) == hits[:1]


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

    def complete(self, *, user_text: str, image_paths: list[Path], max_tokens: int,
                 system_prompt: str, response_schema: dict) -> str:
        self.user_text = user_text
        self.max_tokens = max_tokens
        return json.dumps({"extracts": [1]})


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

    assert answer.text == "L'errore E104 indica una pressione insufficiente nel circuito. [S1]"
    assert answer.sources[0].page == 7


def test_grounded_answer_rejects_invented_procedure_and_invalid_citation() -> None:
    excerpts = [(1, "Cliccare su Accesso temporaneo.")]
    invented = {"quotes": [{"source": 1, "text": "Selezionare il reparto desiderato."}]}
    assert _grounded_answer(json.dumps(invented), excerpts) is None
    wrong_source = {"extracts": [2]}
    assert _grounded_answer(json.dumps(wrong_source), excerpts) is None
    assert _grounded_answer('{"extracts": [true]}', excerpts) is None
    assert _grounded_answer('{"extracts": ["Selezionare il reparto"]}', excerpts) is None


def test_source_sentences_exclude_caption_without_losing_short_instructions() -> None:
    assert _source_sentences(
        "Figura 1-2 Selezione Reparto\n\nPremere Accedi.\nSelezionare il reparto abilitato."
    ) == ["Premere Accedi.", "Selezionare il reparto abilitato."]


def test_source_sentences_separate_controls_from_section_heading() -> None:
    assert _source_sentences(
        "2.1 Controlli\n\nSono disponibili:\n• Avvia il processo.\n• Annulla le modifiche."
    ) == ["Sono disponibili:", "• Avvia il processo.", "• Annulla le modifiche."]


def test_cross_reference_does_not_become_a_standalone_answer() -> None:
    text = "• Elementi archiviati negli ultimi giorni (Rif. Par. 2.3 Elementi archiviati)."
    assert _source_sentences(text) == [text]
    assert _source_sentences("2.3 Elementi archiviati ............. 40") == []


def test_numbered_procedure_keeps_all_steps() -> None:
    text = "1. Inserire identificativo e credenziale.\n2. Premere Entra."
    assert _source_sentences(text) == ["1. Inserire identificativo e credenziale. 2. Premere Entra."]


@pytest.mark.parametrize("question", [
    "Come posso fare il login?",
    "come faccio il login?",
    "Come faccio a fare il login?",
    "Come facciamo il login?",
    "Come devo fare il login?",
    "Come dovrei effettuare il login?",
    "Come effettuo il login?",
    "Come eseguo il login?",
])
def test_conversational_query_finds_procedure_and_instructions(question: str) -> None:
    content = (
        "Introduzione.\n\n2.1 Login\n\nUsare le credenziali assegnate.\n\n"
        "1. Inserire identificativo e credenziale.\n2. Premere Entra.\n\n"
        "Figura 2-1 Accesso\n\nSelezionare il contesto autorizzato.\n\n2.2 Altre funzioni"
    )
    assert _strong_lexical_match(question, content)
    excerpt = _relevant_excerpt(content, question)
    assert "Premere Entra" in excerpt
    assert "Selezionare il contesto" in excerpt
    assert "Altre funzioni" not in excerpt


@pytest.mark.parametrize("question", [
    "Come posso fare il login?", "come faccio il login?", "Come effettuo il login?",
])
def test_named_procedure_uses_all_steps_without_semantic_threshold(question: str) -> None:
    hit = _hit(1, 0.3)
    hit.content = "2.1 Login\n\n1. Inserire credenziale.\n2. Premere Entra."
    excerpts = [(1, "Inserire credenziale."), (1, "Premere Entra.")]
    assert _procedure_selection(question, [hit], excerpts) == [1, 2]
    assert _procedure_selection("Come firmare il documento?", [hit], excerpts) is None
    assert _procedure_selection("Come faccio la firma dopo il login?", [hit], excerpts) is None


def test_menu_selection_keeps_instruction_without_other_menu_items() -> None:
    excerpts = [(1, "In base alla configurazione è possibile accedere a diverse liste:"),
                (1, "◼ Elementi aperti"), (1, "◼ Elementi archiviati")]
    assert _complete_list_selection([3], excerpts) == [1, 3]


def test_questions_without_a_subject_need_clarification() -> None:
    assert _needs_clarification("Come lo apro?")
    assert _needs_clarification("Dove devo cliccare?")
    assert not _needs_clarification("Dove clicco per aprire il diario?")
    assert not _needs_clarification("Come faccio il login?")
    assert not _credential_value_supported(
        "Qual è la mia password personale?", [(1, "Inserire la password assegnata.")]
    )
    assert _credential_value_supported(
        "Come inserisco la mia password?", [(1, "Inserire la password assegnata.")]
    )


def test_context_uses_real_section_titles_without_table_of_contents() -> None:
    content = (
        "1.1 Archivio ........ 12\n\n3.2 Archivio operativo\n\n"
        "Premere X.\n\nFigura 3-7 Archivio_Dettaglio pannello"
    )
    assert _page_context(content) == "Archivio operativo / Archivio Dettaglio pannello"


def test_quote_selection_rejects_added_words_and_inverted_negation() -> None:
    excerpts = [(1, "In stato Chiuso non è possibile modificare il documento.")]
    assert _selected_quotes(json.dumps({"quotes": [excerpts[0][1]]}), excerpts) == [1]
    assert _selected_quotes('{"quotes": []}', excerpts) == []
    assert _selected_quotes('{"quotes": ["È possibile modificare il documento."]}', excerpts) is None
    assert _selected_quotes('{"quotes": [1]}', excerpts) is None


def test_paragraph_completion_keeps_conditions_but_not_other_controls() -> None:
    hit = _hit(1, 0.5)
    hit.content = (
        "Le opzioni dipendono dal profilo. Il revisore vede solo i propri documenti.\n\n"
        "Sono disponibili: • Apri il dettaglio. • Ripristina la versione precedente."
    )
    excerpts = [(1, text) for text in _source_sentences(hit.content)]
    assert _complete_paragraph_selection([2], excerpts, [hit]) == [1, 2]
    last = len(excerpts)
    assert _complete_paragraph_selection([last], excerpts, [hit]) == [last]


def test_visible_selection_numbers_map_to_sparse_original_passages(tmp_path: Path) -> None:
    hit = _hit(1, 0.5)
    hit.content = "Dati generici non pertinenti. " * 19 + "Il codice ZR-9 indica la condizione di prova."

    class StaticRetriever:
        def search(self, *args, **kwargs):
            return [hit]

    class SelectingLLM:
        def complete(self, *, user_text, **kwargs):
            assert "[F8] Il codice ZR-9" in user_text
            assert "[F20]" not in user_text
            return '{"extracts": [8]}'

    answer = AnswerService(StaticRetriever(), SelectingLLM(), settings_for(tmp_path)).answer(
        "Che cosa indica ZR-9?"
    )
    assert answer.text == "Il codice ZR-9 indica la condizione di prova. [S1]"


def test_passage_ranking_recovers_short_answer_and_invalidates_changed_text(tmp_path: Path) -> None:
    class PassageEmbedder:
        model_name = "test-passages"

        def __init__(self):
            self.inputs = []

        def embed(self, texts):
            self.inputs.extend(texts)
            return [[1.0, 0.0] if "Archivia" in text else [0.0, 1.0] for text in texts]

    settings = replace(settings_for(tmp_path), embedding_provider="openai")
    store = Store(settings.database_path)
    embedder = PassageEmbedder()
    retriever = Retriever(store, embedder, settings)
    wrong, correct = _hit(1, 0.8), _hit(2, 0.2)
    wrong.content = "Impostazioni generali."
    correct.content = "Testo non pertinente.\n\nPremere Archivia."
    assert retriever.passage_ranked("Archivia", [wrong, correct])[0].chunk_id == 2
    first_count = len(embedder.inputs)
    retriever.passage_ranked("Archivia", [wrong, correct])
    assert len(embedder.inputs) == first_count + 1  # solo la domanda
    correct.content = "Premere Ripristina."
    retriever.passage_ranked("Archivia", [wrong, correct])
    assert "Premere Ripristina." in embedder.inputs[first_count + 1:]
    embedder.model_name = "test-new-model"
    previous = len(embedder.inputs)
    retriever.passage_ranked("Archivia", [wrong, correct])
    assert "Impostazioni generali." in embedder.inputs[previous:]


def test_configurable_list_preserves_both_options_and_context() -> None:
    excerpts = [
        (1, "In base alla configurazione il sistema può:"),
        (1, "• Conservare la sessione."),
        (1, "• Non conservare la sessione."),
        (1, "Inviare una notifica al termine."),
    ]
    assert _complete_list_selection([2], excerpts) == [1, 2, 3]
    assert _complete_list_selection([], excerpts) == []
    assert _complete_list_selection([4], excerpts) == [4]


def test_list_completion_does_not_cross_source_boundary() -> None:
    excerpts = [(1, "In base alla configurazione:"), (2, "• Azione diversa.")]
    assert _complete_list_selection([1], excerpts) == [1]


def test_default_filter_does_not_support_default_credential() -> None:
    assert not _credential_value_supported(
        "Qual è la password predefinita?", [(1, "Il filtro predefinito mostra tutte le voci.")]
    )
    assert _credential_value_supported(
        "Qual è la password iniziale?", [(1, "La password predefinita è DEMO-ONLY.")]
    )
    assert _credential_value_supported("Come cambio la password?", [(1, "Premere Salva.")])


def test_candidate_shortlist_keeps_relevant_fact_among_menu_labels() -> None:
    excerpts = [(1, f"• Sezione numero {index}") for index in range(20)]
    excerpts.append((1, "Le note sono modificabili per un periodo configurabile."))
    selected = _candidate_indices("Per quale periodo sono modificabili le note?", excerpts)
    assert len(selected) == 8
    assert 21 in selected


def test_semantic_selection_uses_only_the_clear_answer() -> None:
    excerpts = [(1, "Solo gli utenti autorizzati vedono il comando."), (1, "Premere Conferma.")]
    assert _semantic_selection("Chi vede il comando?", excerpts, [0.85, 0.65], 0.5) == [1]


def test_semantic_selection_keeps_multiple_requested_facts() -> None:
    excerpts = [(1, "Selezionare il profilo."), (1, "Le opzioni sono nelle impostazioni.")]
    assert _semantic_selection(
        "Quale profilo selezionare e dove sono le opzioni?", excerpts, [0.75, 0.70], 0.5
    ) == [1, 2]


def test_required_fields_do_not_select_the_upload_procedure() -> None:
    excerpts = [
        (1, "Caricare il file con il pulsante Sfoglia."),
        (1, "I campi obbligatori sono:"),
        (1, "• Nome."),
        (1, "• Categoria."),
    ]
    selected = _semantic_selection(
        "Quali campi sono obbligatori per il caricamento?", excerpts, [0.8, 0.4, 0.3, 0.3], 0.5
    )
    assert _complete_list_selection(selected, excerpts) == [2, 3, 4]


def test_uncertain_semantics_defers_and_unrelated_semantics_abstains() -> None:
    excerpts = [(1, "Una frase tecnica.")]
    assert _semantic_selection("Domanda parafrasata?", excerpts, [0.3], 0.5) is None
    assert _semantic_selection("Domanda su altro argomento?", excerpts, [0.1], 0.5) == []


def test_state_question_keeps_positive_instruction_when_negative_is_top_ranked() -> None:
    excerpts = [(1, "In stato Aperto non può essere archiviato."),
                (1, "Per archiviare portare il registro in stato Chiuso.")]
    assert _semantic_selection(
        "In quale stato può essere archiviato?", excerpts, [0.7, 0.6], 0.5
    ) == [1, 2]


def test_grounded_answer_preserves_permission_limits_and_source_mapping() -> None:
    excerpt = "Nell’elenco vengono proposti i soli reparti a cui l’utente è abilitato."
    payload = {"extracts": [2]}
    excerpts = [(2, "Premere Accedi."), (1, excerpt)]
    assert _grounded_answer(json.dumps(payload), excerpts) == (
        "Nell’elenco vengono proposti i soli reparti a cui l’utente è abilitato. [S1]"
    )
    assert _grounded_answer('{"extracts": []}', excerpts) == (
        "Le fonti fornite non contengono questa informazione."
    )
    assert _grounded_answer('```json\n{"extracts": [2]}\n```', excerpts) == (
        f"{excerpt} [S1]"
    )


def test_answer_service_never_displays_unverified_model_output(tmp_path: Path) -> None:
    hit = _hit(1, 0.5)
    hit.content = "Premere il pulsante di accesso."

    class StaticRetriever:
        def search(self, *args, **kwargs):
            return [hit]

    class InventingLLM:
        calls = 0

        def complete(self, **kwargs):
            self.calls += 1
            return json.dumps({"quotes": [{"source": 1, "text": "Disattivare i controlli."}]})

    llm = InventingLLM()
    answer = AnswerService(StaticRetriever(), llm, settings_for(tmp_path)).answer("Come accedo?")
    assert llm.calls == 2
    assert "Disattivare" not in answer.text
    assert "Non riesco" in answer.text
    assert answer.sources == [hit]


def test_answer_service_omits_unused_source_and_renumbers_citation(tmp_path: Path) -> None:
    first = _hit(1, 0.50)
    first.content = "Applicare grasso sulle guarnizioni."
    second = _hit(2, 0.49)
    second.content = "Serrare il dado a 12 Nm."

    class StaticRetriever:
        def search(self, *args, **kwargs):
            return [first, second]

    class SelectingLLM:
        def complete(self, **kwargs):
            return '{"extracts": [2]}'

    answer = AnswerService(StaticRetriever(), SelectingLLM(), settings_for(tmp_path)).answer(
        "Quale coppia di serraggio va applicata?"
    )
    assert answer.text == "Serrare il dado a 12 Nm. [S1]"
    assert answer.sources == [second]


def test_abstention_does_not_show_unrelated_sources(tmp_path: Path) -> None:
    hit = _hit(1, 0.5)
    hit.content = "Il filtro predefinito mostra tutte le voci."

    class StaticRetriever:
        def search(self, *args, **kwargs):
            return [hit]

    class AbstainingLLM:
        def complete(self, **kwargs):
            return '{"requested_info": "credenziale iniziale", "extracts": []}'

    answer = AnswerService(StaticRetriever(), AbstainingLLM(), settings_for(tmp_path)).answer(
        "Qual è la credenziale iniziale?"
    )
    assert answer.text == "Le fonti fornite non contengono questa informazione."
    assert answer.sources == []
