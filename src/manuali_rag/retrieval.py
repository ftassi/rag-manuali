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


def _source_sentences(excerpt: str) -> list[str]:
    sentences = []
    for block in excerpt.split("\n\n"):
        normalized = " ".join(block.split())
        if re.search(r"\.{3,}", normalized):
            continue
        if re.match(r"^(?:Figura|Tabella)\s+\d", normalized, re.IGNORECASE):
            continue
        if re.match(r"^\d+(?:\.\d+)+\s+[^.!?]+$", normalized):
            continue
        if re.match(r"^\w+\s*[–-]\s*\d+(?:\.\d+)+(?:\s+[A-Z0-9]+)*$", normalized):
            continue
        if normalized.startswith("Confidential") and "Record name:" in normalized:
            continue
        # Una procedura numerata deve mantenere insieme i passi, non solo il più simile.
        if re.match(r"^\d+\.\s+", normalized):
            sentences.append(normalized)
            continue
        for item in re.split(r"\s+(?=[•◼➢]|\d+\.\s+[A-Z])", normalized):
            item = re.sub(r"^\d+\.\s+", "", item)
            sentences.extend(
                sentence for sentence in re.split(
                    r"(?<!Rif\.)(?<!Par\.)(?<=[.!?])\s+", item, flags=re.IGNORECASE
                ) if sentence
            )
    return sentences


def _selected_indices(text: str, count: int) -> list[int] | None:
    text = text.strip()
    if text.startswith("```") and text.endswith("```"):
        text = "\n".join(text.splitlines()[1:-1])
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("extracts"), list):
        return None
    selected = payload["extracts"]
    if len(selected) > 5:
        return None
    for index in selected:
        if type(index) is not int or not 1 <= index <= count:
            return None
    return selected


def _complete_list_selection(selected: list[int], excerpts: list[tuple[int, str]]) -> list[int]:
    """Mantiene il contesto e tutte le alternative di una lista condizionata."""
    completed = set(selected)
    for offset, (source, context) in enumerate(excerpts):
        if not context.endswith(":"):
            continue
        children = []
        for index in range(offset + 1, len(excerpts)):
            child_source, text = excerpts[index]
            if child_source != source or not text.startswith(("•", "◼", "➢")):
                break
            children.append(index + 1)
        if not children or not completed.intersection([offset + 1, *children]):
            continue
        # Le alternative configurabili e i campi obbligatori non sono scelte esclusive.
        if "configur" in context.casefold() or "obbligator" in context.casefold():
            completed.update([offset + 1, *children])
    return sorted(completed)


def _credential_value_supported(question: str, excerpts: list[tuple[int, str]]) -> bool:
    credential = re.compile(r"password|credenzial|parola\s+d['’]ordine", re.IGNORECASE)
    initial = re.compile(r"predefinit|default|inizial", re.IGNORECASE)
    if not credential.search(question) or not initial.search(question):
        return True
    if re.search(r"\bcome\b", question, re.IGNORECASE):
        return True
    return any(credential.search(text) and initial.search(text) for _, text in excerpts)


def _candidate_indices(question: str, excerpts: list[tuple[int, str]], limit: int = 8) -> list[int]:
    features = _term_features(question)
    ranked = sorted(
        range(1, len(excerpts) + 1),
        key=lambda index: (-len(features & _term_features(excerpts[index - 1][1])), index),
    )
    return sorted(ranked[:limit])


def _semantic_selection(
    question: str,
    excerpts: list[tuple[int, str]],
    scores: list[float],
    minimum: float,
) -> list[int] | None:
    ranked = sorted(range(len(scores)), key=lambda index: (-scores[index], index))
    if not ranked:
        return []
    # Una richiesta di campi obbligatori deve scegliere la lista, non le istruzioni di upload.
    if re.search(r"\b(?:campi|dati)\b", question, re.IGNORECASE) and re.search(
        r"obbligator", question, re.IGNORECASE
    ):
        lists = [
            index for index in ranked
            if excerpts[index][1].endswith(":")
            and re.search(r"obbligator", excerpts[index][1], re.IGNORECASE)
        ]
        if lists and scores[lists[0]] >= 0.20:
            return [lists[0] + 1]
    best = ranked[0]
    if scores[best] < 0.20:
        return []
    if scores[best] < minimum:
        return None
    selected = [best + 1]
    parts = min(5, 1 + len(re.findall(
        r"\be\s+(?:quali?|dove|come|cosa|quando|chi)\b", question, re.IGNORECASE
    )))
    for index in ranked[1:parts]:
        if scores[index] >= max(minimum, scores[best] * 0.80):
            selected.append(index + 1)
    if "stato" in question.casefold() and re.search(
        r"non\s+(?:può|puo|possono)", excerpts[best][1], re.IGNORECASE
    ):
        for index in ranked[1:]:
            text = excerpts[index][1]
            if "stato" in text.casefold() and not re.search(r"\bnon\b", text, re.IGNORECASE):
                if scores[index] >= scores[best] - 0.15:
                    selected.append(index + 1)
                break
    return selected


def _render_excerpts(selected: list[int], excerpts: list[tuple[int, str]]) -> str:
    if not selected:
        return "Le fonti fornite non contengono questa informazione."
    lines = []
    for index in selected:
        source, value = excerpts[index - 1]
        line = f"{value} [S{source}]"
        if line not in lines:
            lines.append(line)
    return "\n".join(lines)


def _grounded_answer(text: str, excerpts: list[tuple[int, str]]) -> str | None:
    """Il modello seleziona estratti; testo e citazioni provengono dal programma."""
    selected = _selected_indices(text, len(excerpts))
    return _render_excerpts(selected, excerpts) if selected is not None else None


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


def _strong_lexical_match(question: str, content: str) -> bool:
    identifiers = set(IDENTIFIER_RE.findall(question.upper()))
    if identifiers & set(IDENTIFIER_RE.findall(content.upper())):
        return True

    def roots(text: str) -> set[str]:
        return {
            token[:5] if token.isalpha() and len(token) >= 6 else token
            for token in FTS_TOKEN_RE.findall(text.casefold())
            if token not in FTS_STOPWORDS and len(token) > 2
        }

    question_roots = roots(question)
    return bool(question_roots) and len(question_roots & roots(content)) >= min(
        2, len(question_roots)
    )


def _relevant_excerpt(content: str, question: str, max_blocks: int = 3) -> str:
    blocks = [block.strip() for block in content.split("\n\n") if block.strip()]
    if len(blocks) <= max_blocks:
        return content
    question_features = _term_features(question)
    # Le parole della domanda possono comparire solo nell'intestazione della procedura.
    # In quel caso servono i paragrafi successivi, non la sola intestazione o didascalia.
    for index, block in enumerate(blocks):
        if (
            re.fullmatch(r"\d+(?:\.\d+)+\s+[^.!?]+", " ".join(block.split()))
            and question_features
            and question_features <= _term_features(block)
        ):
            end = index + 1
            while end < len(blocks) and end < index + 7:
                if re.match(r"^\d+(?:\.\d+)+\s+", blocks[end]):
                    break
                end += 1
            return "\n\n".join(blocks[index:end])
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
        # Un singolo verbo generico non deve prevalere sulla ricerca semantica.
        lexical = [
            hit.chunk_id
            for hit in self.store.get_hits([(chunk_id, 0.0) for chunk_id in lexical])
            if _strong_lexical_match(question, hit.content)
        ]
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

        excerpts: list[tuple[int, str]] = []
        image_paths: list[Path] = []
        seen_images: set[str] = set()
        for index, hit in enumerate(hits, start=1):
            excerpt = _relevant_excerpt(hit.content, question)
            for sentence in _source_sentences(excerpt):
                excerpts.append((index, sentence))
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

        if not excerpts or not _credential_value_supported(question, excerpts):
            return Answer(
                text="Le fonti fornite non contengono questa informazione.", sources=[]
            )

        candidates = _candidate_indices(question, excerpts)
        prompt = (
            f"DOMANDA: {question}\nPASSAGGI:\n"
            + "\n".join(f"[F{index}] {excerpts[index - 1][1]}" for index in candidates)
            + "\nScegli solo le frasi che rispondono alla domanda, senza argomenti aggiuntivi. "
            'Se le fonti non contengono la risposta, restituisci {"extracts": []}.'
        )
        output_options = {
            "image_paths": image_paths,
            "max_tokens": 80,
            "response_schema": {
                "type": "object",
                "properties": {"extracts": {
                    "type": "array",
                    "items": {"type": "integer", "enum": candidates},
                    "maxItems": 5,
                }},
                "required": ["extracts"],
                "additionalProperties": False,
            },
            "system_prompt": (
                "Seleziona le frasi pertinenti. Restituisci JSON con extracts, "
                "array di numeri interi."
            ),
        }
        selected = None
        if self.settings.embedding_provider == "openai" and not image_paths:
            vectors = self.retriever.embedder.embed([question, *[text for _, text in excerpts]])
            scores = [
                sum(a * b for a, b in zip(vectors[0], vector, strict=True))
                for vector in vectors[1:]
            ]
            selected = _semantic_selection(
                question, excerpts, scores, self.settings.answer_unit_min_similarity
            )
        if selected is None:
            raw = self.llm.complete(user_text=prompt, **output_options)
            selected = _selected_indices(raw, len(excerpts))
            if selected is not None and any(index not in candidates for index in selected):
                selected = None
        if selected is None:
            correction = (
                f"{prompt}\n\nCORREZIONE OBBLIGATORIA\n"
                "La risposta precedente non contiene estratti verificabili nel formato richiesto. "
                "Usa solo numeri F presenti nelle FONTI. "
                f"I numeri validi sono: {candidates}. "
                f"Correggi questa selezione: {raw}\n"
                'Restituisci esclusivamente JSON con il campo "extracts" e numeri validi.'
            )
            raw = self.llm.complete(user_text=correction, **output_options)
            selected = _selected_indices(raw, len(excerpts))
            if selected is not None and any(index not in candidates for index in selected):
                selected = None
        if selected is None:
            text = (
                "Non riesco a ricavare una risposta verificabile dalle fonti fornite. "
                "Consulta le pagine indicate."
            )
        else:
            text = _render_excerpts(_complete_list_selection(selected, excerpts), excerpts)
            if not selected:
                hits = []
        cited = {int(index) for index in re.findall(r"\[S(\d+)\]", text)}
        if cited:
            source_indices = [index for index in range(1, len(hits) + 1) if index in cited]
            mapping = {old: new for new, old in enumerate(source_indices, start=1)}
            text = re.sub(
                r"\[S(\d+)\]",
                lambda match: f"[S{mapping[int(match.group(1))]}]",
                text,
            )
            hits = [hits[index - 1] for index in source_indices]
        return Answer(text=text, sources=hits)
