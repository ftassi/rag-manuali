from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


@dataclass(frozen=True, slots=True)
class Settings:
    data_dir: Path
    database_path: Path
    llm_base_url: str
    llm_model: str
    llm_timeout: float
    embedding_provider: str
    embedding_base_url: str
    embedding_model: str
    embedding_timeout: float
    hash_embedding_dimensions: int
    render_dpi: int
    ocr_enabled: bool
    ocr_languages: str
    ocr_min_chars: int
    caption_mode: str
    max_images_per_question: int
    chunk_chars: int
    chunk_overlap_chars: int
    retrieval_candidates: int
    retrieval_semantic_weight: float
    retrieval_lexical_weight: float
    retrieval_rrf_k: int
    answer_ambiguity_margin: float
    default_top_k: int

    @classmethod
    def from_env(cls) -> Settings:
        _load_env_file(Path(".env"))
        data_dir = Path(os.getenv("MANUALI_DATA_DIR", "./data")).expanduser().resolve()
        caption_mode = os.getenv("MANUALI_CAPTION_MODE", "off").strip().lower()
        if caption_mode not in {"off", "visual", "all"}:
            raise ValueError("MANUALI_CAPTION_MODE deve essere off, visual oppure all")

        provider = os.getenv("MANUALI_EMBEDDING_PROVIDER", "openai").strip().lower()
        if provider not in {"openai", "hash"}:
            raise ValueError("MANUALI_EMBEDDING_PROVIDER deve essere openai oppure hash")

        return cls(
            data_dir=data_dir,
            database_path=data_dir / "manuali.sqlite3",
            llm_base_url=os.getenv("MANUALI_LLM_BASE_URL", "http://127.0.0.1:11434/v1"),
            llm_model=os.getenv("MANUALI_LLM_MODEL", "llama3.2:3b"),
            llm_timeout=_float("MANUALI_LLM_TIMEOUT", 300),
            embedding_provider=provider,
            embedding_base_url=os.getenv("MANUALI_EMBEDDING_BASE_URL", "http://127.0.0.1:11434/v1"),
            embedding_model=os.getenv("MANUALI_EMBEDDING_MODEL", "nomic-embed-text-v2-moe"),
            embedding_timeout=_float("MANUALI_EMBEDDING_TIMEOUT", 120),
            hash_embedding_dimensions=_int("MANUALI_HASH_EMBEDDING_DIMENSIONS", 384),
            render_dpi=_int("MANUALI_RENDER_DPI", 130),
            ocr_enabled=_bool("MANUALI_OCR_ENABLED", False),
            ocr_languages=os.getenv("MANUALI_OCR_LANGUAGES", "ita+eng"),
            ocr_min_chars=_int("MANUALI_OCR_MIN_CHARS", 80),
            caption_mode=caption_mode,
            max_images_per_question=_int("MANUALI_MAX_IMAGES_PER_QUESTION", 0),
            chunk_chars=_int("MANUALI_CHUNK_CHARS", 2200),
            chunk_overlap_chars=_int("MANUALI_CHUNK_OVERLAP_CHARS", 250),
            retrieval_candidates=_int("MANUALI_RETRIEVAL_CANDIDATES", 30),
            retrieval_semantic_weight=_float("MANUALI_RETRIEVAL_SEMANTIC_WEIGHT", 1.0),
            retrieval_lexical_weight=_float("MANUALI_RETRIEVAL_LEXICAL_WEIGHT", 1.0),
            retrieval_rrf_k=_int("MANUALI_RETRIEVAL_RRF_K", 60),
            answer_ambiguity_margin=_float("MANUALI_ANSWER_AMBIGUITY_MARGIN", 0.02),
            default_top_k=_int("MANUALI_DEFAULT_TOP_K", 5),
        )

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "documents").mkdir(exist_ok=True)
        (self.data_dir / "incoming").mkdir(exist_ok=True)


def _load_env_file(path: Path) -> None:
    """Carica un semplice file .env senza sovrascrivere l'ambiente del processo."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or not key.replace("_", "").isalnum():
            continue
        try:
            parsed = shlex.split(value, comments=True)
            value = parsed[0] if parsed else ""
        except ValueError:
            value = value.strip().strip("\"'")
        os.environ.setdefault(key, value)
