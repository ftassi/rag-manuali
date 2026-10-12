from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .config import Settings
from .embeddings import Embedder
from .llm import LLMClient
from .store import FTS_STOPWORDS, FTS_TOKEN_RE, SearchHit, Store

IDENTIFIER_RE = re.compile(r"\b(?=[A-Z0-9-]*[A-Z])(?=[A-Z0-9-]*\d)[A-Z0-9]+(?:-[A-Z0-9]+)*\b")


@dataclass(slots=True)
class Answer:
    text: str
    sources: list[SearchHit]


def _grounded_answer(text: str, excerpts: list[tuple[int, str]]) -> str | None:
    """Il modello seleziona estratti; testo e citazioni provengono dal programma."""
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("extracts"), list):
        return None
    selected = payload["extracts"]
    if not selected:
        return "Le fonti fornite non contengono questa informazione."
    if not 1 <= len(selected) <= 5:
        return None
    lines = []
    for index in selected:
        if type(index) is not int or not 1 <= index <= len(excerpts):
            return None
        source, value = excerpts[index - 1]
        line = f"{value} [S{source}]"
        if line not in lines:
            lines.append(line)
    return "\n".join(lines)


def _select_answer_sources(hits: list[SearchHit], ambiguity_margin: float) -> list[SearchHit]:
    if len(hits) < 2:
        return hits
    first_score = hits[0].semantic_score
    second_score = hits[1].semantic_score
    if (
        first_score is not None
        and second_score is not None
        and abs(first_score - second_score) <= ambiguity_margin
        and hits[1].score >= hits[0].score * (1 - ambiguity_margin)
    ):
        return hits[:2]
    return hits[:1]


def _term_features(text: str) -> set[str]:
    features: set[str] = set()
    for token in FTS_TOKEN_RE.findall(text.casefold()):
        if token in FTS_STOPWORDS or (
            len(token) <= 2 and not any(char.isdigit() for char in token)
        ):
            continue
        features.add(token)
        if len(token) >= 6 and token.isalpha():
            features.add(token[:5])
    return features


def _relevant_excerpt(content: str, question: str, max_blocks: int = 3) -> str:
    blocks = [block.strip() for block in content.split("\n\n") if block.strip()]
    if len(blocks) <= max_blocks:
        return content
    question_features = _term_features(question)
    ranked = sorted(
        (
            (len(question_features & _term_features(block)), index)
            for index, block in enumerate(blocks)
        ),
        key=lambda item: (-item[0], item[1]),
    )
    selected = sorted(index for score, index in ranked[:max_blocks] if score > 0)
    if not selected:
        return content
    return "\n\n".join(blocks[index] for index in selected)


def _required_identifier(question: str, hits: list[SearchHit], answer: str) -> str | None:
    question_terms = set(FTS_TOKEN_RE.findall(question.casefold()))
    if not question_terms & {"codice", "identificatore", "sigla"}:
        return None
    identifiers = {
        identifier
        for hit in hits
        for identifier in IDENTIFIER_RE.findall(hit.content)
        if not re.fullmatch(r"S\d+", identifier)
    }
    if len(identifiers) != 1:
        return None
    identifier = identifiers.pop()
    return identifier if identifier.casefold() not in answer.casefold() else None


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
        # Nei manuali lunghi una corrispondenza lessicale precisa può non comparire tra i primi
        # candidati semantici. Un secondo contributo al solo primo risultato FTS evita che venga
        # superato da passaggi generici presenti in entrambe le liste.
        if lexical:
            fused[lexical[0]] += self.settings.retrieval_lexical_weight / (
                self.settings.retrieval_rrf_k + 1
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
        # entrambi i punteggi (semantico e ibrido) sono quasi equivalenti.
        hits = _select_answer_sources(hits, self.settings.answer_ambiguity_margin)

        source_blocks: list[str] = []
        excerpts: list[tuple[int, str]] = []
        image_paths: list[Path] = []
        seen_images: set[str] = set()
        for index, hit in enumerate(hits, start=1):
            page = f"pagina {hit.page}" if hit.page else "pagina non specificata"
            excerpt = _relevant_excerpt(hit.content, question)
            numbered: list[str] = []
            for block in excerpt.split("\n\n"):
                for sentence in re.split(r"(?<=[.!?])\s+", " ".join(block.split())):
                    if sentence:
                        excerpts.append((index, sentence))
                        numbered.append(f"[F{len(excerpts)}] {sentence}")
            source_blocks.append(
                f"[S{index}] Manuale: {hit.manual_title}; {page}; sezione: {hit.section}\n"
                + "\n".join(numbered)
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
            "domanda. Riporta le frasi pertinenti delle fonti senza parafrasarle: conserva "
            "nomi dei controlli, condizioni e parole come 'solo'. Puoi omettere frasi intere "
            "non pertinenti, ma non aggiungere passaggi operativi o cambiare il significato. "
            "Se una procedura rimanda a un altro manuale, riporta il rinvio senza inventare "
            "i passaggi mancanti. Ometti gli argomenti vicini ma "
            "non pertinenti. Non aggiungere spiegazioni, motivazioni, scopi, cause, conseguenze, "
            "consigli o conoscenze generali, anche se plausibili. Non colmare parti confuse o "
            "mancanti. Prima di rispondere individua in silenzio la frase esatta che risponde alla "
            "domanda e controllane le negazioni. Se la domanda chiede quando o in quale stato "
            "un'operazione può essere eseguita, uno stato per cui la fonte dice 'non può' deve "
            "essere escluso dalla risposta: cerca invece l'istruzione positiva esplicita. "
            "Conserva esattamente coppie opposte come attivo/inattivo o consentito/vietato e non "
            "trasformare 'non può' in 'può'.\n\n"
            f"DOMANDA\n{question}\n\n"
            "FONTI\n" + "\n\n".join(source_blocks) + "\n\nVINCOLI DI USCITA\n"
            "Per ogni parte della domanda scegli la frase F pertinente, compresi condizioni "
            "e limiti. Se la frase richiede un passaggio vicino per essere comprensibile, "
            "seleziona anche quello. Restituisci esclusivamente un oggetto JSON con i numeri "
            'delle frasi, ad esempio {"extracts": [2, 3]}. '
            "Usa da uno a cinque estratti. Non includere testo né numeri S nel JSON. "
            "Copia codici e identificatori per intero, carattere per carattere, inclusi prefissi, "
            "cifre e trattini. "
            'Se le fonti non contengono la risposta, restituisci {"extracts": []}.'
        )
        output_options = {
            "image_paths": image_paths,
            "max_tokens": 80,
            "system_prompt": (
                "Seleziona le frasi del manuale che rispondono alla domanda. "
                "Restituisci solo JSON con la chiave extracts e un elenco di numeri interi. "
                "Non aggiungere spiegazioni."
            ),
        }
        raw = self.llm.complete(user_text=prompt, **output_options)
        text = _grounded_answer(raw, excerpts)
        if text is None:
            correction = (
                f"{prompt}\n\nCORREZIONE OBBLIGATORIA\n"
                "La risposta precedente non contiene estratti verificabili nel formato richiesto. "
                "Usa solo numeri F presenti nelle FONTI. "
                'Restituisci esclusivamente {"extracts": [numeri delle frasi pertinenti]}.'
            )
            raw = self.llm.complete(user_text=correction, **output_options)
            text = _grounded_answer(raw, excerpts)
        if text is None:
            text = (
                "Non riesco a ricavare una risposta verificabile dalle fonti fornite. "
                "Consulta le pagine indicate."
            )
        return Answer(text=text, sources=hits)
