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
        semantic = self.store.vector_candidates(
            query_vector, candidate_limit, document_id=document_id
        )

        # Reciprocal Rank Fusion: robusto anche se i punteggi dei due motori hanno scale diverse.
        fused: dict[int, float] = {}
        for rank, chunk_id in enumerate(semantic, start=1):
            fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (60 + rank)
        for rank, chunk_id in enumerate(lexical, start=1):
            fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.25 / (60 + rank)
        ranked = sorted(fused.items(), key=lambda item: item[1], reverse=True)[:top_k]
        return self.store.get_hits(ranked)


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
            f"DOMANDA\n{question}\n\n"
            "FONTI RECUPERATE\n"
            + "\n\n".join(source_blocks)
            + "\n\nRispondi in italiano e cita le fonti con [S1], [S2], ecc."
        )
        text = self.llm.complete(user_text=prompt, image_paths=image_paths)
        return Answer(text=text, sources=hits)
