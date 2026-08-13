from __future__ import annotations

import re

HEADING_RE = re.compile(r"^(?:#{1,6}\s+)?(.{1,100})$")


def guess_section(text: str, fallback: str = "Contenuto") -> str:
    for raw_line in text.splitlines():
        line = raw_line.strip().lstrip("#").strip()
        if 3 <= len(line) <= 100 and not line.endswith((".", ";", ",")):
            return line
    return fallback


def chunk_text(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    """Divide sui paragrafi, con fallback sulle frasi e overlap limitato."""
    cleaned = re.sub(r"[ \t]+", " ", text)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    if not cleaned:
        return []
    if len(cleaned) <= max_chars:
        return [cleaned]

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", cleaned) if part.strip()]
    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        units = _split_long_unit(paragraph, max_chars)
        for unit in units:
            candidate = f"{current}\n\n{unit}".strip() if current else unit
            if len(candidate) <= max_chars:
                current = candidate
                continue
            if current:
                chunks.append(current)
                prefix = _overlap(current, overlap_chars)
                current = f"{prefix}\n\n{unit}".strip() if prefix else unit
            else:
                chunks.append(unit[:max_chars])
                current = unit[max_chars - overlap_chars :]

    if current:
        chunks.append(current)
    return chunks


def _split_long_unit(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    sentences = re.split(r"(?<=[.!?;:])\s+", text)
    result: list[str] = []
    current = ""
    for sentence in sentences:
        if len(sentence) > max_chars:
            words = sentence.split()
            for word in words:
                candidate = f"{current} {word}".strip()
                if len(candidate) > max_chars and current:
                    result.append(current)
                    current = word
                else:
                    current = candidate
            continue
        candidate = f"{current} {sentence}".strip()
        if len(candidate) > max_chars and current:
            result.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        result.append(current)
    return result


def _overlap(text: str, size: int) -> str:
    if size <= 0:
        return ""
    suffix = text[-size:]
    first_space = suffix.find(" ")
    return suffix[first_space + 1 :] if first_space >= 0 else suffix
