from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import Settings
from .embeddings import Embedder
from .llm import LLMClient
from .store import SearchHit, Store


@dataclass(slots=True)
class Answer:
    text: str
    sources: list[SearchHit]


def _select_answer_sources(hits: list[SearchHit], ambiguity_margin: float) -> list[SearchHit]:
    if len(hits) < 2:
        return hits
    first_score = hits[0].semantic_score
    second_score = hits[1].semantic_score
    if (
        first_score is not None
        and second_score is not None
        and first_score - second_score <= ambiguity_margin
    ):
        return hits[:2]
    return hits[:1]


class Retriever:
    def __init__(self, store: Store, embedder: Embedder, settings: Settings) -> None:
        self.store = store
        self.embedder = embedder
        self.settings = settings

    def search(
        self, question: str, top_k: int | None = None, document_id: str | None = None
    ) -> list[SearchHit]:
        top_k = top_k or self.settings.default_top_k
        candidate_limit = max(self.settings.retrieval_candidates, top_k)
        lexical = self.store.lexical_candidates(question, candidate_limit, document_id)
        query_vector = self.embedder.embed([question])[0]
        semantic_ranked = self.store.vector_candidates_with_scores(
            query_vector, candidate_limit, document_id=document_id
        )
        semantic = [chunk_id for chunk_id, _ in semantic_ranked]
        semantic_scores = dict(semantic_ranked)

        # Reciprocal Rank Fusion: robusto anche se i punteggi dei due motori hanno scale diverse.
        fused: dict[int, float] = {}
        for rank, chunk_id in enumerate(semantic, start=1):
            fused[chunk_id] = fused.get(chunk_id, 0.0) + (
                self.settings.retrieval_semantic_weight / (self.settings.retrieval_rrf_k + rank)
            )
        for rank, chunk_id in enumerate(lexical, start=1):
            fused[chunk_id] = fused.get(chunk_id, 0.0) + (
                self.settings.retrieval_lexical_weight / (self.settings.retrieval_rrf_k + rank)
            )
        ranked = sorted(fused.items(), key=lambda item: item[1], reverse=True)[:top_k]
        return self.store.get_hits(ranked, semantic_scores)


class AnswerService:
    def __init__(
        self,
        retriever: Retriever,
        llm: LLMClient,
        settings: Settings,
    ) -> None:
        self.retriever = retriever
        self.llm = llm
        self.settings = settings

    def answer(
        self,
        question: str,
        *,
        top_k: int | None = None,
        document_id: str | None = None,
        include_images: bool = True,
    ) -> Answer:
        hits = self.retriever.search(question, top_k=top_k, document_id=document_id)
        if not hits:
            return Answer(
                text="Non ho trovato informazioni pertinenti nei manuali indicizzati.",
                sources=[],
            )

        # Una sola fonte riduce la contaminazione. Manteniamo anche la seconda soltanto quando
        # la similarità semantica è quasi equivalente e il ranking è quindi realmente ambiguo.
        hits = _select_answer_sources(hits, self.settings.answer_ambiguity_margin)

        source_blocks: list[str] = []
        image_paths: list[Path] = []
        seen_images: set[str] = set()
        for index, hit in enumerate(hits, start=1):
            page = f"pagina {hit.page}" if hit.page else "pagina non specificata"
            source_blocks.append(
                f"[S{index}] Manuale: {hit.manual_title}; {page}; sezione: {hit.section}\n"
                f"{hit.content}"
            )
            if (
                include_images
                and hit.image_path
                and hit.image_path not in seen_images
                and len(image_paths) < self.settings.max_images_per_question
            ):
                candidate = (self.settings.data_dir / hit.image_path).resolve()
                if candidate.is_file() and candidate.is_relative_to(self.settings.data_dir):
                    image_paths.append(candidate)
                    seen_images.add(hit.image_path)

        prompt = (
            "COMPITO\n"
            "Copia dalle fonti solo i fatti indispensabili per rispondere direttamente alla "
            "domanda e riformulali nel minimo numero di parole. Ometti gli argomenti vicini ma "
            "non pertinenti. Non aggiungere spiegazioni, motivazioni, scopi, cause, conseguenze, "
            "consigli o conoscenze generali, anche se plausibili. Non colmare parti confuse o "
            "mancanti.\n\n"
            f"DOMANDA\n{question}\n\n"
            "FONTI\n" + "\n\n".join(source_blocks) + "\n\nVINCOLI DI USCITA\n"
            "Rispondi in italiano con una sola frase breve, oppure con al massimo cinque punti "
            "solo se la domanda richiede più elementi. Termina ogni frase o punto con almeno una "
            "citazione nel formato esatto [S1], [S2], ecc. Non sostituire le citazioni con titoli "
            "o numeri di pagina. Se le fonti non contengono la risposta, scrivi soltanto: "
            "Copia codici e identificatori per intero, carattere per carattere, inclusi prefissi, "
            "cifre e trattini. "
            '"Le fonti fornite non contengono questa informazione."'
        )
        text = self.llm.complete(user_text=prompt, image_paths=image_paths, max_tokens=160)
        return Answer(text=text, sources=hits)
