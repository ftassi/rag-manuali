"""Passaggi con contesto e procedure per guide con capitoli numerati semplici.

I titoli sono metadati, mai risposte. I riferimenti alle pagine rimangono quelli
originali, anche quando un elenco continua nella pagina successiva.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass

from .store import FTS_STOPWORDS, FTS_TOKEN_RE, SearchHit

BULLET = re.compile(r"^[•◼➢❖▪]\s*")
NUMBER = re.compile(r"^(\d+)\.\s*(.+)$")
VERB = re.compile(r"^(?:[A-Za-zÀ-ÿ]+(?:are|ere|ire)|clicca|seleziona|accedi|premi)\b", re.IGNORECASE)
NOISE = (FTS_STOPWORDS - {"codice"}) | {"quali", "quanti", "dove", "già", "gia", "devo", "posso", "come", "il", "che"}


def focus_question(question: str) -> str:
    tail = question.rsplit(":", 1)[-1].strip()
    return tail if re.match(r"come\b|cosa\b|quali?\b|quando\b", tail, re.IGNORECASE) else question


def target_terms(question: str) -> set[str]:
    match = re.search(
        r"\b(?:quali|quale|quanti)\s+(.+?)(?=\s+(?:devo|imposto|scelgo|uso|configuro|per|di)\b|[?])",
        question, re.IGNORECASE,
    )
    return roots(match[1]) if match else set()


def roots(text: str) -> set[str]:
    result = set()
    for token in FTS_TOKEN_RE.findall(text.casefold()):
        if token in NOISE or len(token) < 3 and not any(c.isdigit() for c in token):
            continue
        if re.fullmatch(r"creo|creare|creazione", token):
            token = "creaz"
        elif re.fullmatch(r"aggiungo|aggiungere|inserire|inserimento", token):
            token = "inser"
        elif token in {"ora", "orari", "orario"}:
            token = "ora"
        elif len(token) >= 6 and token.isalpha():
            token = token[:5]
        elif len(token) >= 4 and token[-1] in "aeio":
            token = token[:-1]
        result.add(token)
    return result


def flat_heading(text: str) -> str | None:
    match = NUMBER.fullmatch(text)
    if match and len(text) <= 120 and not text.endswith((".", ":", ";")):
        title = match[2]
        if title[0].isupper() and not VERB.match(title):
            return title
    return None


def _plain_heading(text: str) -> bool:
    return (3 <= len(text) <= 100 and not text.endswith((".", ";", ",", ":"))
            and not BULLET.match(text) and not NUMBER.match(text)
            and not VERB.match(text) and text[0].isupper()
            and not re.search(r"\b(?:è|sono|viene|consente|possibile)\b", text, re.IGNORECASE))


@dataclass
class Passage:
    path: str
    topic: str
    scope: str
    kind: str
    parts: list[tuple[SearchHit, str]]

    @property
    def text(self) -> str:
        return "\n".join(text for _, text in self.parts)

    @property
    def document_id(self) -> str:
        return self.parts[0][0].document_id

    @property
    def chapter(self) -> str:
        return self.path.split(" / ")[1 if self.scope else 0]

    @property
    def contextual(self) -> str:
        return f"Contesto: {self.path}\nPassaggio: {self.text}"


def passages_from_hits(hits: list[SearchHit]) -> list[Passage]:
    documents: dict[str, list[SearchHit]] = defaultdict(list)
    for hit in hits:
        documents[hit.document_id].append(hit)
    return [passage for doc_hits in documents.values()
            for passage in _document_passages(doc_hits)]


def _document_passages(doc_hits: list[SearchHit]) -> list[Passage]:
    result = []
    ordered = sorted(doc_hits, key=lambda hit: (hit.page or 0, hit.chunk_id))
    blocks = [(hit, " ".join(block.split())) for hit in ordered
              for block in hit.content.split("\n\n") if block.strip()]
    flat = sum(flat_heading(text) is not None for _, text in blocks)
    nested = sum(bool(re.match(r"^\d+(?:\.\d+)+\s+", text)) for _, text in blocks)
    if flat < 2 or flat <= nested:
        return []
    scope = section = label = ""
    intro: tuple[SearchHit, str] | None = None
    group: list[tuple[SearchHit, str]] = []
    group_kind = ""
    group_topic = ""
    group_path = ""
    group_scope = ""
    last_number = 0
    last_prose = ""

    def path() -> str:
        return " / ".join(part for part in (scope, section, label) if part)

    def emit(kind: str, parts: list[tuple[SearchHit, str]], topic: str = "") -> None:
        if parts:
            named = re.match(r"Nella sezione ([^,]+),", parts[0][1])
            local = named[1] if named else topic or label or section
            result.append(Passage(path(), local, scope, kind, list(parts)))

    def flush() -> None:
        nonlocal group, group_kind, last_number
        if group:
            parts = ([intro] if intro else []) + group
            result.append(Passage(group_path, group_topic, group_scope, group_kind, parts))
            if group_kind == "fields":
                for hit, text in group:
                    match = re.match(r"^[•◼➢❖▪]\s*([^:]{2,65}):\s*(.+)", text)
                    if match:
                        parts = ([(intro[0], intro[1])] if intro and match[1].casefold() == "valore" else [])
                        result.append(Passage(
                            group_path + " / " + match[1], match[1], group_scope,
                            "field", parts + [(hit, text)],
                        ))
        group = []
        group_kind = ""
        last_number = 0

    seen = {}
    for hit, text in blocks:
        key = (hit.page, text)
        if key in seen and seen[key] != hit.chunk_id:
            continue
        seen[key] = hit.chunk_id
        if text.isdigit() or re.search(r"\.{3,}", text):
            continue
        heading = flat_heading(text)
        root = re.fullmatch(r"[A-ZÀ-Ý0-9][A-ZÀ-Ý0-9 /_-]{2,70}:", text)
        if heading or root or _plain_heading(text):
            flush()
            intro = None
            if root:
                scope, section, label = text.rstrip(":"), "", ""
            elif heading:
                section, label = heading, ""
            else:
                label = text
                intro = (hit, text)
            last_prose = ""
            continue
        number = NUMBER.match(text)
        kind = "fields" if BULLET.match(text) else (
            "steps" if number or VERB.match(text) and not text.endswith(":") else ""
        )
        if kind:
            value = int(number[1]) if number else 0
            if group and (kind != group_kind or number and value <= last_number):
                flush()
                intro = None
            if not group:
                group_kind = kind
                group_path = path() + (" / " + last_prose[:180] if last_prose else "")
                group_topic, group_scope = label or section, scope
            group.append((hit, text))
            last_number = value
            continue
        flush()
        if not text.endswith(":"):
            emit("prose", [(hit, text)])
            last_prose = text
        intro = (hit, text) if text.endswith(":") or re.match(r"Una volta", text) else None
    flush()

    return result


def scope_tags(passages: list[Passage]) -> set[str]:
    scopes = {p.scope for p in passages if p.scope}
    counts = Counter(token.casefold() for scope in scopes for token in set(FTS_TOKEN_RE.findall(scope)))
    return {token for token, count in counts.items() if count == 1
            and token not in {"manuale", "utente", "guida", "configurazione"}}


def ambiguous_choice(question: str, passages: list[Passage], scores: list[float]) -> bool:
    if not scores:
        return False
    tags = scope_tags(passages) & set(FTS_TOKEN_RE.findall(question.casefold()))
    if len(tags) == 1:
        return False
    best = max(range(len(scores)), key=scores.__getitem__)
    first = passages[best]
    return any(
        (p.document_id, p.scope) != (first.document_id, first.scope)
        and scores[index] >= 0.65 and scores[best] - scores[index] <= 0.04
        for index, p in enumerate(passages)
    )


def rank_scores(question: str, passages: list[Passage], similarities: list[float]) -> list[float]:
    """Il soggetto della sezione pesa più delle citazioni incidentali nel testo."""
    query = roots(focus_question(question))
    targets = target_terms(focus_question(question))
    metadata = [roots(p.path) for p in passages]
    frequencies = Counter(word for words in metadata for word in words)
    weights = {word: 1 + len(passages) / (1 + frequencies[word]) ** 0.5 for word in query}
    total = sum(weights.values()) or 1

    def coverage(words: set[str]) -> float:
        return sum(weights[word] for word in query & words) / total

    scores = []
    procedural = bool(re.search(r"\bcome\b|da dove|quali passi", question, re.IGNORECASE))
    field_names = set().union(*(roots(p.topic) for p in passages if p.kind == "field"))
    requested_fields = (targets or query) & field_names
    parallel = bool(re.search(r"\bquali\b.+\be\b", question, re.IGNORECASE))
    entities = set()
    for p in passages:
        title = p.path.split(" / ")[1 if p.scope else 0]
        entities.update(word.casefold() for word in FTS_TOKEN_RE.findall(title)[1:]
                        if word[0].isupper() and len(word) >= 3)
    wanted_entities = entities & set(FTS_TOKEN_RE.findall(question.casefold()))
    for p, similarity, context in zip(passages, similarities, metadata, strict=True):
        score = similarity + 0.30 * coverage(context) + 0.15 * coverage(roots(p.text))
        score += 0.12 * coverage(roots(p.topic))
        if procedural and p.kind == "steps":
            score += 0.08
        if p.kind == "field" and roots(p.topic) <= query:
            score += 0.10
        if requested_fields and not requested_fields & roots(p.text) and not parallel:
            score -= 0.35
        title = p.path.split(" / ")[1 if p.scope else 0].casefold()
        if wanted_entities and not all(entity in title for entity in wanted_entities):
            score -= 0.45
        if p.kind == "fields":
            labels = [roots(match[1]) for match in re.finditer(
                r"^[•◼➢❖▪]\s*([^:]+):", p.text, re.MULTILINE
            )]
            counts = Counter(word for label in labels for word in label)
            requested = sum(bool(query & {word for word in label if counts[word] == 1})
                            for label in labels)
            score += 0.12 * max(0, requested - 1)
            if labels and re.search(r"\bquali\b", question, re.IGNORECASE):
                common = set.intersection(*labels)
                if common & query:
                    score += 0.18
            if targets and targets & roots(p.text):
                score += 0.12
        if "esempio" in p.text.casefold() and "esempio" not in question.casefold():
            score -= 0.08
        scores.append(score)
    return scores


def select_passages(question: str, passages: list[Passage], scores: list[float]) -> list[int]:
    if not scores:
        return []
    ranked = sorted(range(len(scores)), key=lambda index: scores[index], reverse=True)
    best = ranked[0]
    selected = [best]
    first = passages[best]
    query = roots(question)
    # Una procedura generale può rimandare al dettaglio dell'operazione richiesta.
    if first.kind == "steps":
        for index in ranked[1:]:
            p = passages[index]
            if (p.document_id == first.document_id and p.scope == first.scope
                    and p.path.startswith(first.path + " / ") and p.kind == "prose"
                    and roots(p.topic) & query and scores[index] >= scores[best] - 0.30):
                selected.append(index)
                break
    # Una domanda su più parametri deve coprire i diversi nomi, non solo uno.
    if re.search(r"\be\b|\bquali\b", question, re.IGNORECASE):
        query = roots(question)
        covered = roots(passages[best].text) & query
        covered_topics = roots(first.topic) & query
        for index in ranked[1:]:
            p = passages[index]
            if p.document_id != first.document_id or p.scope != first.scope:
                continue
            if p.chapter != first.chapter:
                continue
            if scores[index] < scores[best] - 0.16:
                continue
            if any(p.text in passages[chosen].text for chosen in selected):
                continue
            matched = roots(p.text) & query
            topics = roots(p.topic) & query
            if ((matched - covered and (topics or p.kind == "prose"))
                    or topics - covered_topics):
                selected.append(index)
                covered.update(matched)
                covered_topics.update(topics)
            if len(selected) >= 3:
                break
    return selected
