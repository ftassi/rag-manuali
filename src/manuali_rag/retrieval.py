from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, replace
from pathlib import Path

from .config import Settings
from .embeddings import Embedder, embed_query
from .llm import LLMClient
from .store import FTS_STOPWORDS, FTS_TOKEN_RE, SearchHit, Store
from .structure import (
    ambiguous_choice,
    authentication_supported,
    confident_context,
    focus_question,
    passages_from_hits,
    rank_scores,
    roots,
    scope_tags,
    select_passages,
)

IDENTIFIER_RE = re.compile(r"\b(?=[A-Z0-9-]*[A-Z])(?=[A-Z0-9-]*\d)[A-Z0-9]+(?:-[A-Z0-9]+)*\b")
CLARIFICATION_TEXT = (
    "Di quale funzione o schermata del software stai parlando? "
    "Specifica cosa vuoi aprire o quale operazione vuoi eseguire."
)
EDIT_CLARIFICATION_TEXT = (
    "Vuoi correggere una nota già salvata oppure annullare modifiche non ancora salvate? "
    "Le due operazioni richiedono passaggi diversi."
)


def _personal_scope(question: str) -> bool:
    return bool(re.search(
        r"\b(?:scritt|fatt|creat|inserit|registrat|redatt)\w*\s+da\s+me\b|\b(?:mie|miei)\b",
        question, re.IGNORECASE,
    ))


def _personal_scope_selection(
    question: str, excerpts: list[tuple[int, str]], scores: list[float]
) -> list[int] | None:
    if not _personal_scope(question):
        return None
    matches = [index for index, (_, text) in enumerate(excerpts)
               if re.search(r"\bda me\b|\bpropri\w*\b|utente (?:corrente|connesso)", text, re.IGNORECASE)
               and scores[index] >= 0.35]
    return [max(matches, key=lambda index: scores[index]) + 1] if matches else []


def _complete_filter_steps(
    selected: list[int], excerpts: list[tuple[int, str]], hits: list[SearchHit]
) -> list[int]:
    # L'applicazione è una dipendenza della selezione, anche sulla pagina successiva.
    filter_sources = [hits[excerpts[index - 1][0] - 1] for index in selected
                      if re.search(r"filtr", excerpts[index - 1][1], re.IGNORECASE)]
    confirmations = [index for index, (source, text) in enumerate(excerpts, start=1)
                     if re.search(r"conferm.*applic.*filtr", text, re.IGNORECASE)
                     and any(hit.document_id == hits[source - 1].document_id
                             and hit.page is not None and hits[source - 1].page is not None
                             and abs(hit.page - hits[source - 1].page) <= 1
                             for hit in filter_sources)]
    return [index for index in selected if index not in confirmations] + confirmations


def _needs_clarification(question: str) -> bool:
    # Verbi senza oggetto e pronomi non identificano una procedura; non inventare il contesto.
    tokens = set(FTS_TOKEN_RE.findall(question.casefold())) - FTS_STOPWORDS
    generic = {
        "dove", "devo", "cliccare", "clicco", "aprire", "apro", "lo", "la", "farlo",
        "stato", "cambio", "cambiare", "modifico", "modificare", "attivo", "attivare",
        "disattivo", "è", "aggiorno", "aggiornare", "salvo", "salvare", "configuro",
        "configurare", "creo", "creare",
    }
    return not (tokens - generic)


def _has_named_control(question: str, content: str) -> bool:
    query = " ".join(question.casefold().split())
    for text in _source_sentences(content):
        for match in re.finditer(
            r"(?:^[•◼➢]\s*|(?:cliccando|cliccare|clicca)\s+su\s+|"
            r"(?:pulsante|voce|funzione|tasto)\s+)"
            r"([A-ZÀ-Ý][\w’'-]+(?:\s+[\w’'-]+){1,3})", text,
        ):
            words = match.group(1).split()
            if words[0].casefold() in FTS_STOPWORDS | {"si", "dopo", "prima"}:
                continue
            for length in range(2, len(words) + 1):
                label = " ".join(words[:length]).casefold()
                if words[length - 1].casefold() not in FTS_STOPWORDS and label in query:
                    return True
    return False


@dataclass(slots=True)
class Answer:
    text: str
    sources: list[SearchHit]


def _conversational_steps(text: str) -> str:
    """Raccordi grammaticali soltanto: fatti, condizioni e citazioni restano intatti."""
    verbs = {
        "accedere": "accedi", "selezionare": "seleziona", "cliccare": "clicca",
        "inserire": "inserisci", "compilare": "compila", "premere": "premi",
        "aprire": "apri", "indicare": "indica", "impostare": "imposta",
        "mantenere": "mantieni", "lasciare": "lascia", "fare": "fai",
    }
    pattern = r"(^|[.!?]\s+|:\s+)(" + "|".join(verbs) + r")\b"

    def conjugate(match: re.Match) -> str:
        word = verbs[match[2].casefold()]
        if match[2][0].isupper():
            word = word.capitalize()
        return match[1] + word

    lines = []
    for line in text.split("\n"):
        sentences = []
        for sentence in re.split(r"(?<=[.!?])\s+", line):
            converted = re.sub(pattern, conjugate, sentence, flags=re.IGNORECASE)
            # Coordina solo istruzioni dirette, mai frasi modali o negative.
            if converted != sentence:
                converted = re.sub(r"(\be\s+)(" + "|".join(verbs) + r")\b",
                                   conjugate, converted, flags=re.IGNORECASE)
            converted = re.sub(
                r"(^Una volta[^.!?]*,\s+)(" + "|".join(verbs) + r")\b",
                conjugate, converted, flags=re.IGNORECASE,
            )
            sentences.append(converted)
        lines.append(" ".join(sentences))
    return "\n".join(lines)


def _connected_reply(text: str, position: int) -> str:
    text = _conversational_steps(text)
    text = re.sub(r"(?<!:)\n(?![•◼➢❖▪])", " ", text)
    if position and text.startswith("In "):
        return "Per l’altra operazione, in " + text[3:]
    prefix = "Per iniziare, " if position == 0 else "Per l’operazione successiva, "
    if text and text[0].isupper() and not text.split()[0].isupper():
        text = text[0].lower() + text[1:]
    return prefix + text


def _source_sentences(excerpt: str) -> list[str]:
    sentences = []
    # Mantiene separati i controlli descritti su righe numerate di una tabella PDF.
    excerpt = re.sub(r"\n\s*(\d{1,2})\s+(?=[A-ZÀ-Ý])", r"\n\n\1 ", excerpt)
    for block in excerpt.split("\n\n"):
        normalized = " ".join(block.split())
        if re.search(r"\.{3,}", normalized):
            continue
        if re.match(r"^(?:Figura|Tabella)\s+\d", normalized, re.IGNORECASE):
            continue
        if re.match(r"^\d+(?:\.\d+)+\s+[^.!?]+$", normalized):
            continue
        if re.match(r"^\d+\s+[^a-zàèéìòù.!?]+$", normalized):
            continue
        if re.match(r"^\w+\s*[–-]\s*\d+(?:\.\d+)+(?:\s+[A-Z0-9]+)*$", normalized):
            continue
        if normalized.startswith("Confidential") and "Record name:" in normalized:
            continue
        # Una procedura numerata deve mantenere insieme i passi, non solo il più simile.
        if re.match(r"^\d+\.\s+", normalized):
            if re.search(r"\s+\d+\.\s+[A-Z]", normalized):
                sentences.append(normalized)
                continue
            normalized = re.sub(r"^\d+\.\s+", "", normalized)
        for item in re.split(r"\s+(?=[•◼➢]|\d+\.\s+[A-Z])", normalized):
            item = re.sub(r"^\d+\.\s+", "", item)
            sentences.extend(
                sentence for sentence in re.split(
                    r"(?<!Rif\.)(?<!Par\.)(?<=[.!?])\s+", item, flags=re.IGNORECASE
                ) if sentence
            )
    return sentences


def _page_context(content: str) -> str:
    topics = []
    for block in content.split("\n\n"):
        text = " ".join(block.split())
        if re.search(r"\.{3,}", text):
            continue
        if re.fullmatch(r"\d+(?:\.\d+)+\s+[^.!?]{2,150}", text):
            topics.append(re.sub(r"^\d+(?:\.\d+)+\s+", "", text))
        elif re.match(r"^(?:Figura|Tabella)\s+\d", text, re.IGNORECASE):
            topics.append(re.sub(r"^(?:Figura|Tabella)\s+[\d-]+\s*[: ]?", "", text,
                                 flags=re.IGNORECASE).replace("_", " "))
    return " / ".join(dict.fromkeys(topics))[:600]


def _contextual_passage(hit: SearchHit, text: str) -> str:
    context = _page_context(hit.content)
    return f"Sezione della pagina: {context}\nPassaggio: {text}" if context else text


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


def _selected_quotes(text: str, excerpts: list[tuple[int, str]]) -> list[int] | None:
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("quotes"), list):
        return None
    if len(payload["quotes"]) > 5:
        return None
    selected = []
    for quote in payload["quotes"]:
        if not isinstance(quote, str):
            return None
        matches = [index for index, (_, value) in enumerate(excerpts, start=1)
                   if quote in {value, value.lstrip("•◼➢❖▪ ")}]
        if not matches:
            return None
        selected.append(matches[0])
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
            if re.search(r"accedere.*liste", context, re.IGNORECASE):
                # Una lista di menu richiede il comando introduttivo e la voce scelta.
                completed.add(offset + 1)
            else:
                completed.update([offset + 1, *children])
    return sorted(completed)


def _complete_paragraph_selection(
    selected: list[int], excerpts: list[tuple[int, str]], hits: list[SearchHit], question: str = ""
) -> list[int]:
    """Mantiene condizioni e passi nello stesso breve paragrafo, non altre voci di menu."""
    completed = set(selected)
    for source, hit in enumerate(hits, start=1):
        for block in hit.content.split("\n\n"):
            normalized = " ".join(block.split())
            if len(re.findall(r"[•◼➢❖▪]", normalized)) > 1:
                continue
            values = _source_sentences(block)
            indices = [
                index for index, (number, text) in enumerate(excerpts, start=1)
                if number == source and text in values
            ]
            if len(normalized) > 450:
                permissions = [index for index in indices
                               if re.search(r"abilitat|consent|permess", excerpts[index - 1][1], re.IGNORECASE)]
                if completed.intersection(permissions):
                    completed.update(permissions)
            elif len(indices) <= 5 and completed.intersection(indices):
                if (
                    not question
                    or re.search(r"\bcome\b|\bperch[eé]\b|\be\s+(?:quali?|dove|come|cosa)", question, re.IGNORECASE)
                    or any(re.match(r"Per (?:procedere|ultimare|confermare)", value) for value in values)
                ):
                    completed.update(indices)
    return sorted(completed)


def _credential_value_supported(question: str, excerpts: list[tuple[int, str]]) -> bool:
    credential = re.compile(r"password|credenzial|parola\s+d['’]ordine", re.IGNORECASE)
    initial = re.compile(r"predefinit|default|inizial", re.IGNORECASE)
    if (
        credential.search(question)
        and re.search(r"\b(?:qual[e]?|dimmi)\b", question, re.IGNORECASE)
        and re.search(r"\b(?:mia|mio|mie|miei|personale)\b", question, re.IGNORECASE)
    ):
        return False
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


def _visual_indicator_selection(
    question: str, excerpts: list[tuple[int, str]], scores: list[float]
) -> list[int] | None:
    if not re.search(r"riconosc|sto guardando", question, re.IGNORECASE):
        return None
    indicators = [
        index for index, (_, text) in enumerate(excerpts)
        if re.search(r"\b(?:riga|sfondo|colore|bordo)\b", text, re.IGNORECASE)
        and scores[index] >= 0.5
    ]
    return [max(indicators, key=lambda index: scores[index]) + 1] if indicators else None


def _price_value_supported(question: str, excerpts: list[tuple[int, str]]) -> bool:
    if not re.search(r"quanto\s+costa|\bprezz[oi]\b|\bcosto\b", question, re.IGNORECASE):
        return True
    evidence = " ".join(text for _, text in excerpts)
    return bool(re.search(
        r"\d[\d., ]*\s*(?:€|euro|eur\b|dollari|usd\b)|[€$]\s*\d|gratuit\w*|senza\s+costo",
        evidence, re.IGNORECASE,
    ))


def _term_features(text: str) -> set[str]:
    features: set[str] = set()
    for token in FTS_TOKEN_RE.findall(text.casefold()):
        if token in FTS_STOPWORDS or (
            len(token) <= 2 and token not in {"me", "io", "tu", "si", "sì", "no"}
            and not any(char.isdigit() for char in token)
        ):
            continue
        features.add(token)
        if len(token) >= 6 and token.isalpha():
            features.add(token[:5])
    return features


def _lexical_evidence_scores(question: str, texts: list[str], scores: list[float]) -> list[float]:
    def roots(text: str) -> set[str]:
        return _term_features(text)

    features = roots(question)
    documents = [roots(text) for text in texts]
    weights = {
        term: math.log((len(texts) + 1) / (1 + sum(term in doc for doc in documents))) + 1
        for term in features
        if any(term in doc for doc in documents)
    }
    total = sum(weights.values()) or 1.0
    return [
        score + 0.30 * sum(weight for term, weight in weights.items() if term in doc) / total
        for score, doc in zip(scores, documents, strict=True)
    ]


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


def _focused_section(content: str, question: str) -> str | None:
    blocks = [block.strip() for block in content.split("\n\n") if block.strip()]
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
    return None


def _procedure_selection(
    question: str, hits: list[SearchHit], excerpts: list[tuple[int, str]]
) -> list[int] | None:
    if not re.search(r"\bcome\b", question, re.IGNORECASE):
        return None
    for source, hit in enumerate(hits, start=1):
        # Un'operazione di correzione non è una semplice consultazione del dettaglio.
        if re.search(r"corregg|corregger|modific", question, re.IGNORECASE) and not re.search(
            r"annull|cronolog|storico|version", question, re.IGNORECASE
        ):
            for heading in hit.content.split("\n\n"):
                match = re.fullmatch(r"\d+(?:\.\d+)+\s+Modifica\s+(.+)", heading.strip())
                if not match or not (_term_features(match[1]) & _term_features(question)):
                    continue
                steps = [index for index, (number, text) in enumerate(excerpts, start=1)
                         if number == source and not text.startswith(("•", "◼", "➢", "❖", "o "))
                         and re.search(r"clicc|pulsante|icona", text, re.IGNORECASE)]
                if steps:
                    opening = [index for index, (number, text) in enumerate(excerpts, start=1)
                               if re.search(r"cliccando sulla|selezionare", text, re.IGNORECASE)
                               and re.search(r"contenuto.*(?:espanso|destra)", text, re.IGNORECASE)
                               and _term_features(match[1]) & _term_features(text)
                               and hits[number - 1].document_id == hit.document_id
                               and hits[number - 1].page is not None and hit.page is not None
                               and 0 < hit.page - hits[number - 1].page <= 2]
                    return opening[:1] + steps
    for source, hit in enumerate(hits, start=1):
        focused = _focused_section(hit.content, question)
        if focused and re.search(r"(?:^|\s)1\.\s", focused):
            return [index for index, (number, _) in enumerate(excerpts, start=1) if number == source]
    return None


def _relevant_excerpt(content: str, question: str, max_blocks: int = 3) -> str:
    blocks = [block.strip() for block in content.split("\n\n") if block.strip()]
    if len(blocks) <= max_blocks:
        return content
    question_features = _term_features(question)
    focused = _focused_section(content, question)
    if focused is not None:
        return focused
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

    def _cached_vectors(self, texts: list[str]) -> list[list[float] | tuple[float, ...]]:
        prefix = f"passage-v2:{self.embedder.model_name}:"
        keys = [prefix + hashlib.sha256(text.encode("utf-8")).hexdigest() for text in texts]
        cached = self.store.passage_vectors(keys)
        text_by_key = dict(zip(keys, texts, strict=True))
        missing = [key for key in dict.fromkeys(keys) if key not in cached]
        for start in range(0, len(missing), 32):
            batch = missing[start:start + 32]
            vectors = self.embedder.embed([text_by_key[key] for key in batch])
            rows = list(zip(batch, vectors, strict=True))
            self.store.save_passage_vectors(rows)
            cached.update(dict(rows))
        return [cached[key] for key in keys]

    def passage_ranked(self, question: str, hits: list[SearchHit]) -> list[SearchHit]:
        units = [(hit, text) for hit in hits for text in _source_sentences(hit.content)]
        if not units:
            return []
        contextual = [_contextual_passage(hit, text) for hit, text in units]
        vectors = self._cached_vectors(contextual)
        query = embed_query(self.embedder, question)
        scores = [sum(a * b for a, b in zip(query, vector, strict=True)) for vector in vectors]
        scores = _lexical_evidence_scores(question, contextual, scores)
        best: dict[int, float] = {}
        for (hit, _), score in zip(units, scores, strict=True):
            best[hit.chunk_id] = max(best.get(hit.chunk_id, -1.0), score)
        # Una procedura nominata esplicitamente mantiene priorità rispetto a sinonimi generici.
        for hit in hits:
            if _focused_section(hit.content, question):
                best[hit.chunk_id] = max(best.get(hit.chunk_id, 0.0), 0.9)
            if _has_named_control(question, hit.content):
                best[hit.chunk_id] = max(best.get(hit.chunk_id, 0.0), 1.4)
        ranked = sorted(hits, key=lambda hit: best.get(hit.chunk_id, -1.0), reverse=True)
        for hit in ranked:
            hit.semantic_score = best.get(hit.chunk_id, -1.0)
            hit.score = hit.semantic_score
        return ranked

    def search(
        self, question: str, top_k: int | None = None, document_id: str | None = None
    ) -> list[SearchHit]:
        top_k = top_k or self.settings.default_top_k
        candidate_limit = max(self.settings.retrieval_candidates, top_k, 50)
        lexical = self.store.lexical_candidates(question, candidate_limit, document_id)
        # Un singolo verbo generico non deve prevalere sulla ricerca semantica.
        lexical = [
            hit.chunk_id
            for hit in self.store.get_hits([(chunk_id, 0.0) for chunk_id in lexical])
            if _strong_lexical_match(question, hit.content)
        ]
        query_vector = embed_query(self.embedder, question)
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
        ranked = sorted(fused.items(), key=lambda item: item[1], reverse=True)
        hits = self.store.get_hits(ranked, semantic_scores)
        if self.settings.embedding_provider == "openai":
            hits = self.store.all_hits(document_id)
            passages = self.passage_ranked(question, hits)
            retained = passages[:max(1, top_k - 3)]
            by_id = {hit.chunk_id: hit for hit in passages}
            retained.extend(by_id[cid] for cid, _ in semantic_ranked[:3] if cid in by_id)
            retained.extend(passages)
            seen = set()
            hits = [hit for hit in retained if not (hit.chunk_id in seen or seen.add(hit.chunk_id))]
        return hits[:top_k]


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

    def _structured_answer(
        self, question: str, hits: list[SearchHit], document_id: str | None,
    ) -> Answer | None:
        passages = passages_from_hits(self.retriever.store.all_hits(document_id))
        if not passages:
            return None
        structured_ids = {p.document_id for p in passages}
        explicit = bool(scope_tags(passages) & set(FTS_TOKEN_RE.findall(question.casefold())))
        subjects = roots(" ".join(p.scope for p in passages)) - roots(
            "gestione manuale utente guida configurazione"
        )
        explicit = explicit or bool(subjects & roots(question))
        mandatory = document_id in structured_ids or explicit
        missing = Answer("Le fonti fornite non contengono questa informazione.", [])
        if not authentication_supported(question, passages):
            return missing if mandatory else None
        available = set().union(*(roots(p.contextual) for p in passages))
        query_terms = roots(question)
        if not query_terms & available:
            return missing if mandatory else None
        evidence = [(index, p.text) for index, p in enumerate(passages)]
        if not _credential_value_supported(question, evidence) or not _price_value_supported(question, evidence):
            return missing if mandatory else None
        focused = focus_question(question)
        query = embed_query(self.retriever.embedder, focused)
        vectors = self.retriever._cached_vectors([p.contextual for p in passages])
        similarities = [sum(a * b for a, b in zip(query, v, strict=True)) for v in vectors]
        scores = rank_scores(question, passages, similarities)
        best = max(range(len(scores)), key=scores.__getitem__)
        body_terms = roots(passages[best].text)
        topic_terms = roots(passages[best].topic)
        if (not confident_context(passages, scores, best) or similarities[best] < 0.35
                or not (query_terms & body_terms)
                or not mandatory and not query_terms & topic_terms):
            return missing if mandatory else None
        competitors = [hit.semantic_score or 0 for hit in hits if hit.document_id not in structured_ids]
        if competitors and max(competitors) > scores[best] + 0.06 and not mandatory:
            return None
        if ambiguous_choice(question, passages, scores):
            return Answer(CLARIFICATION_TEXT, [])
        selected = select_passages(focused, passages, scores)
        parts = [part for index in selected for part in passages[index].parts]
        sources: list[SearchHit] = []
        headings = list(dict.fromkeys(" / ".join(passages[index].path.split(" / ")[:2])
                                      for index in selected))
        lines = []
        seen = set()
        for hit, text in parts:
            key = (hit.chunk_id, text)
            if key in seen:
                continue
            seen.add(key)
            source = next((i for i, existing in enumerate(sources, start=1)
                           if existing.chunk_id == hit.chunk_id), None)
            if source is None:
                sources.append(replace(hit, semantic_score=scores[best], score=scores[best]))
                source = len(sources)
            lines.append(f"{text} [S{source}]")
        body = _conversational_steps("\n".join(lines))
        scopes = list(dict.fromkeys(passages[index].scope for index in selected
                                    if passages[index].scope))
        if scopes:
            context = " / ".join(scopes)
            if passages[selected[0]].kind != "steps":
                chapters = list(dict.fromkeys(passages[index].chapter for index in selected))
                context += " (" + " / ".join(chapters) + ")"
            body = "In " + context + ", " + body[0].lower() + body[1:]
        elif headings:
            body = " — ".join(headings) + ":\n" + body
        return Answer(body, sources)

    def _search_question(self, question: str) -> str:
        normalized = re.sub(
            r"\b(?:ho|ha|abbiamo)\s+(?:fatto|effettuato)\s+(?:l['’])?accesso\b(?!\s+all?[aeo]?\b)",
            "dopo il login", question, flags=re.IGNORECASE,
        )
        normalized = re.sub(
            r"\b(\w+)\s+che\s+(?:sono|è|e)\s+stat[ioae]\s+(\w+)\b",
            r"\1 \2", normalized, flags=re.IGNORECASE,
        )
        normalized = re.sub(
            r"\brichiud\w*\b", "chiudere", normalized, flags=re.IGNORECASE,
        )
        normalized = re.sub(r"\bcorregg\w*|\bcorregger\w*", "modificare", normalized,
                            flags=re.IGNORECASE)
        if re.search(r"riconosc|riconosco|sto guardando", question, re.IGNORECASE):
            normalized = re.sub(
                r"come\s+riconosco", "come viene evidenziato", normalized, flags=re.IGNORECASE,
            )
            normalized = re.sub(
                r"che\s+sto\s+guardando", "selezionato", normalized, flags=re.IGNORECASE,
            )
        return normalized

    def answer(
        self,
        question: str,
        *,
        top_k: int | None = None,
        document_id: str | None = None,
        include_images: bool = True,
    ) -> Answer:
        if _needs_clarification(question):
            return Answer(text=CLARIFICATION_TEXT, sources=[])
        if (re.search(r"sbagliat|errore", question, re.IGNORECASE)
                and re.search(r"annull", question, re.IGNORECASE)
                and not re.search(r"salvat|inserimento|prima di|ancora", question, re.IGNORECASE)):
            return Answer(text=EDIT_CLARIFICATION_TEXT, sources=[])
        clauses = re.split(r"\s+(?:e\s+)?poi\s+", question, flags=re.IGNORECASE)
        if 1 < len(clauses) <= 3 and all(not _needs_clarification(clause) for clause in clauses):
            replies = [self.answer(clause, top_k=top_k, document_id=document_id,
                                   include_images=include_images) for clause in clauses]
            incomplete = next((reply for reply in replies if not reply.sources), None)
            if incomplete is not None:
                return incomplete
            sources = []
            paragraphs = []
            for position, reply in enumerate(replies):
                mapping = {}
                for old, hit in enumerate(reply.sources, start=1):
                    source = next((i for i, item in enumerate(sources, start=1)
                                   if item.chunk_id == hit.chunk_id), None)
                    if source is None:
                        sources.append(hit)
                        source = len(sources)
                    mapping[old] = source
                paragraphs.append(re.sub(r"\[S(\d+)\]", lambda m, source_map=mapping: f"[S{source_map[int(m[1])]}]",
                                         _connected_reply(reply.text, position)))
            return Answer("\n\n".join(paragraphs), sources)
        search_question = question
        semantic = self.settings.embedding_provider == "openai"
        if semantic:
            tokens = FTS_TOKEN_RE.findall(question)
            proper = [token.casefold() for token in tokens[1:]
                      if len(token) >= 4 and token[0].isupper() and token[1:].islower()
                      and token.casefold() not in FTS_STOPWORDS]
            if proper:
                vocabulary = set(FTS_TOKEN_RE.findall(" ".join(
                    hit.content for hit in self.retriever.store.all_hits(document_id)
                ).casefold()))
                if any(word not in vocabulary for word in proper):
                    return Answer("Le fonti fornite non contengono questa informazione.", [])
        hits = self.retriever.search(
            question, top_k=max(top_k or 5, 8) if semantic else top_k,
            document_id=document_id,
        )
        if semantic:
            structured = self._structured_answer(question, hits, document_id)
            if structured is not None:
                return structured
        if semantic:
            named = [hit for hit in hits if _has_named_control(question, hit.content)]
            if named:
                hits = named
            else:
                search_question = self._search_question(question)
                if search_question != question:
                    extra = self.retriever.search(search_question, top_k=8, document_id=document_id)
                    seen = {hit.chunk_id for hit in hits}
                    hits.extend(hit for hit in extra if hit.chunk_id not in seen)
                    named = [hit for hit in hits if _has_named_control(search_question, hit.content)]
                    if named:
                        hits = named
            # Le istruzioni di applicazione possono continuare alla pagina seguente.
            if _personal_scope(question) or re.search(r"filtr", question, re.IGNORECASE):
                neighbors = [hit for hit in hits if re.search(
                    r"filtr", _page_context(hit.content), re.IGNORECASE
                )]
                seen = {hit.chunk_id for hit in hits}
                if neighbors:
                    hits.extend(hit for hit in self.retriever.store.all_hits(document_id)
                                if hit.chunk_id not in seen and any(
                                    hit.document_id == anchor.document_id
                                    and hit.page is not None and anchor.page is not None
                                    and hit.page == anchor.page + 1 for anchor in neighbors))
            if re.search(r"corregg|corregger|modific", question, re.IGNORECASE) and not re.search(
                r"annull|cronolog|storico|version", question, re.IGNORECASE
            ):
                anchors = [hit for hit in hits if re.search(
                    r"^\d+(?:\.\d+)+\s+Modifica\s+", hit.content, re.MULTILINE
                )]
                seen = {hit.chunk_id for hit in hits}
                if anchors:
                    hits.extend(hit for hit in self.retriever.store.all_hits(document_id)
                                if hit.chunk_id not in seen and any(
                                    hit.document_id == anchor.document_id
                                    and hit.page is not None and anchor.page is not None
                                    and 0 < anchor.page - hit.page <= 2 for anchor in anchors))
        if not hits:
            return Answer(
                text="Non ho trovato informazioni pertinenti nei manuali indicizzati.",
                sources=[],
            )

        # Una sola fonte riduce la contaminazione. Manteniamo anche la seconda soltanto quando
        # entrambi i punteggi (semantico e ibrido) sono quasi equivalenti.
        if not semantic:
            hits = _select_answer_sources(hits, self.settings.answer_ambiguity_margin)

        excerpts: list[tuple[int, str]] = []
        image_paths: list[Path] = []
        seen_images: set[str] = set()
        for index, hit in enumerate(hits, start=1):
            excerpt = _focused_section(hit.content, question)
            if excerpt is None:
                excerpt = (
                    hit.content if self.settings.embedding_provider == "openai"
                    else _relevant_excerpt(hit.content, question)
                )
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

        if (
            not excerpts or not _credential_value_supported(question, excerpts)
            or not _price_value_supported(question, excerpts)
        ):
            return Answer(
                text="Le fonti fornite non contengono questa informazione.", sources=[]
            )

        candidates = _candidate_indices(question, excerpts)
        scores = []
        if semantic and not image_paths:
            query = embed_query(self.retriever.embedder, search_question)
            contextual = [
                _contextual_passage(hits[source - 1], text) for source, text in excerpts
            ]
            vectors = self.retriever._cached_vectors(contextual)
            scores = [sum(a * b for a, b in zip(query, v, strict=True)) for v in vectors]
            scores = _lexical_evidence_scores(search_question, contextual, scores)
            ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
            direct = _personal_scope_selection(question, excerpts, scores)
            if direct is None:
                direct = _visual_indicator_selection(question, excerpts, scores)
            requested_ids = set(IDENTIFIER_RE.findall(question.upper()))
            if requested_ids and re.search(r"\b(?:quali?|quali)\b.*(?:messaggi|codici)", question, re.IGNORECASE):
                coded = [index for index in ranked
                         if set(IDENTIFIER_RE.findall(excerpts[index][1].upper())) - requested_ids
                         and requested_ids & set(IDENTIFIER_RE.findall(hits[excerpts[index][0] - 1].content.upper()))
                         and not re.match(r"^\d+-\s*\d+[a-z]", excerpts[index][1])]
                if coded:
                    source = excerpts[coded[0]][0]
                    direct = [index + 1 for index in coded if excerpts[index][0] == source][:5]
            features = _term_features(search_question)
            for index in ranked:
                text = excerpts[index][1]
                if (
                    text.endswith(":") or len(FTS_TOKEN_RE.findall(text)) < 4
                    or re.match(r"^\d+-\s*\d+[a-z]", text)
                ):
                    continue
                matched = features & _term_features(contextual[index])
                if (
                    scores[index] >= self.settings.answer_unit_min_similarity
                    and len(matched) >= min(2, len(features))
                    and len(matched) / max(1, len(features)) >= 0.35
                    and direct is None
                ):
                    direct = [index + 1]
                break
            nearest = [index + 1 for index in ranked if not excerpts[index][1].endswith(":")
                       and not re.match(r"^\d+-\s*\d+[a-z]", excerpts[index][1])][:4]
            candidates = sorted(nearest)
        else:
            direct = None
        evidence_lines = []
        previous_source = None
        for visible, index in enumerate(candidates, start=1):
            source, text = excerpts[index - 1]
            if source != previous_source:
                context = _page_context(hits[source - 1].content)
                if context:
                    evidence_lines.append(f"CONTESTO DELLA PAGINA: {context}")
                previous_source = source
            evidence_lines.append(f"[F{visible}] {text}")
        prompt = (
            "PASSAGGI:\n" + "\n".join(evidence_lines)
            + f"\nDOMANDA: {question}\n"
            + "Scegli solo le frasi che rispondono alla domanda, senza argomenti aggiuntivi. "
            'Se le fonti non contengono la risposta, restituisci {"extracts": []}.'
        )
        output_options = {
            "image_paths": image_paths,
            "max_tokens": 80,
            "response_schema": {
                "type": "object",
                "properties": {"extracts": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 1, "maximum": len(candidates)},
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
        if semantic:
            values = [excerpts[index - 1][1].lstrip("•◼➢❖▪ ") for index in candidates]
            prompt = (
                "PASSAGGI:\n" + "\n".join(evidence_lines) + f"\nDOMANDA: {question}\n"
                "Copia nel campo quotes solo i testi dei passaggi che rispondono alla domanda. "
                "Non copiare i numeri F o il contesto della pagina. Non modificare il testo. "
                'Se non trovi la risposta, restituisci {"quotes": []}.'
            )
            output_options.update({
                "max_tokens": 900,
                "system_prompt": "Seleziona citazioni esatte che rispondono alla domanda, senza altri argomenti.",
                "response_schema": {
                    "type": "object", "properties": {"quotes": {
                        "type": "array", "items": {"type": "string", "enum": values},
                        "maxItems": 5,
                    }}, "required": ["quotes"], "additionalProperties": False,
                },
            })
        selected = direct if _personal_scope(question) else None
        if selected is None:
            selected = _procedure_selection(question, hits, excerpts)
        procedure_selected = selected is not None and not _personal_scope(question)
        if selected is None and re.search(
            r"serve|acced|access|visualizz|vedere|vedo|trovo|trovare|aprire|apro|ottenere",
            question, re.IGNORECASE,
        ):
            anchors = [index for index, (_, text) in enumerate(excerpts, start=1)
                       if _has_named_control(search_question, text)]
            if anchors:
                complete = [index for index in anchors
                            if excerpts[index - 1][1].rstrip().endswith((".", "!", "?", ";"))]
                selected = (complete or anchors)[:1]
        if selected is None and self.settings.embedding_provider == "openai" and not image_paths:
            selected = _semantic_selection(
                question, excerpts, scores, math.inf
            )
        if selected is None and direct is not None:
            selected = direct
        if selected is None:
            raw = self.llm.complete(user_text=prompt, **output_options)
            if semantic:
                selected = _selected_quotes(raw, excerpts)
            else:
                visible = _selected_indices(raw, len(candidates))
                selected = [candidates[index - 1] for index in visible] if visible is not None else None
        if selected is None:
            correction = (
                f"{prompt}\n\nCORREZIONE OBBLIGATORIA\n"
                "La risposta precedente non contiene estratti verificabili nel formato richiesto. "
                "Usa solo numeri F presenti nelle FONTI. "
                f"I numeri validi sono da 1 a {len(candidates)}. "
                f"Correggi questa selezione: {raw}\n"
                'Restituisci esclusivamente JSON con il campo "extracts" e numeri validi.'
            )
            if semantic:
                correction = (
                    prompt + "\nCopia esattamente il testo di un passaggio, senza aggiunte. "
                    'Restituisci solo JSON con quotes, oppure {"quotes": []}.'
                )
            raw = self.llm.complete(user_text=correction, **output_options)
            if semantic:
                selected = _selected_quotes(raw, excerpts)
            else:
                visible = _selected_indices(raw, len(candidates))
                selected = [candidates[index - 1] for index in visible] if visible is not None else None
        if selected is None:
            text = (
                "Non riesco a ricavare una risposta verificabile dalle fonti fornite. "
                "Consulta le pagine indicate."
            )
        else:
            if selected and scores and not procedure_selected:
                source_scores: dict[int, float] = {}
                for index in selected:
                    source = excerpts[index - 1][0]
                    source_scores[source] = max(source_scores.get(source, -1.0), scores[index - 1])
                strongest = max(source_scores.values())
                selected = [index for index in selected
                            if source_scores[excerpts[index - 1][0]] >= strongest - self.settings.answer_ambiguity_margin]
            selected = _complete_paragraph_selection(selected, excerpts, hits, question)
            selected = _complete_list_selection(selected, excerpts)
            if procedure_selected:
                selected.sort(key=lambda index: (
                    hits[excerpts[index - 1][0] - 1].document_id,
                    hits[excerpts[index - 1][0] - 1].page or 0, index,
                ))
            selected = _complete_filter_steps(selected, excerpts, hits)
            text = _render_excerpts(selected, excerpts)
            if not selected:
                hits = []
        cited = {int(index) for index in re.findall(r"\[S(\d+)\]", text)}
        if cited:
            # Testo e anteprime seguono l'ordine dei passi, anche fra pagine diverse.
            source_indices = list(dict.fromkeys(
                int(index) for index in re.findall(r"\[S(\d+)\]", text)
            ))
            mapping = {old: new for new, old in enumerate(source_indices, start=1)}
            text = re.sub(
                r"\[S(\d+)\]",
                lambda match: f"[S{mapping[int(match.group(1))]}]",
                text,
            )
            hits = [hits[index - 1] for index in source_indices]
        return Answer(text=text, sources=hits)
