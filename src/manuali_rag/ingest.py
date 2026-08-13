from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .chunking import chunk_text, guess_section
from .config import Settings
from .embeddings import Embedder
from .llm import LLMClient, LLMError
from .store import ChunkInput, Store

PAGE_COMMENT_RE = re.compile(r"<!--\s*(?:pagina|page)\s*:\s*(\d+)\s*-->", re.IGNORECASE)
IMAGE_RE = re.compile(r"!\[[^]]*]\(([^)]+)\)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


@dataclass(slots=True)
class ExtractedPage:
    number: int
    text: str
    section: str
    image_path: str | None = None
    visual_summary: str | None = None


@dataclass(slots=True)
class IngestResult:
    document_id: str
    title: str
    page_count: int
    chunk_count: int
    warnings: list[str] = field(default_factory=list)
    already_indexed: bool = False


class Ingestor:
    def __init__(
        self,
        settings: Settings,
        store: Store,
        embedder: Embedder,
        llm: LLMClient | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.embedder = embedder
        self.llm = llm

    def ingest(self, source: Path, *, force: bool = False) -> IngestResult:
        source = source.expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        if source.suffix.casefold() not in {".pdf", ".md", ".markdown"}:
            raise ValueError("Sono supportati soltanto file PDF e Markdown")

        checksum = _sha256(source)
        existing = self.store.document_by_checksum(checksum)
        if existing and not force:
            return IngestResult(
                document_id=existing["id"],
                title=existing["title"],
                page_count=existing["page_count"],
                chunk_count=existing.get("chunk_count", 0),
                warnings=existing["warnings"],
                already_indexed=True,
            )

        document_id = checksum[:16]
        title = _title_from_filename(source)
        document_dir = self.settings.data_dir / "documents" / document_id
        pages_dir = document_dir / "pages"
        images_dir = document_dir / "images"
        document_dir.mkdir(parents=True, exist_ok=True)
        pages_dir.mkdir(exist_ok=True)
        images_dir.mkdir(exist_ok=True)
        stored_source = document_dir / f"source{source.suffix.casefold()}"
        if source != stored_source:
            shutil.copy2(source, stored_source)

        warnings: list[str] = []
        if source.suffix.casefold() == ".pdf":
            pages = self._extract_pdf(stored_source, pages_dir, warnings)
        else:
            pages = self._extract_markdown(source, images_dir, warnings)

        chunks = self._pages_to_chunks(pages)
        if not chunks:
            raise ValueError("Il documento non contiene testo o descrizioni indicizzabili")

        markdown_path = document_dir / "document.md"
        markdown_path.write_text(_pages_to_markdown(title, pages), encoding="utf-8")

        embeddings: list[list[float]] = []
        batch_size = 16
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            embeddings.extend(self.embedder.embed([chunk.content for chunk in batch]))

        self.store.replace_document(
            document_id=document_id,
            checksum=checksum,
            source_name=source.name,
            title=title,
            markdown_path=str(markdown_path.relative_to(self.settings.data_dir)),
            page_count=len(pages),
            warnings=warnings,
            chunks=chunks,
            embeddings=embeddings,
            embedding_model=self.embedder.model_name,
        )
        return IngestResult(
            document_id=document_id,
            title=title,
            page_count=len(pages),
            chunk_count=len(chunks),
            warnings=warnings,
        )

    def _extract_pdf(
        self, source: Path, pages_dir: Path, warnings: list[str]
    ) -> list[ExtractedPage]:
        try:
            import pymupdf
        except ImportError as exc:  # pragma: no cover - dipendenza d'installazione
            raise RuntimeError("PyMuPDF non è installato") from exc

        document = pymupdf.open(source)
        pages: list[ExtractedPage] = []
        try:
            for index, page in enumerate(document, start=1):
                text = page.get_text("text", sort=True).strip()
                image_file = pages_dir / f"page-{index:04d}.jpg"
                pixmap = page.get_pixmap(dpi=self.settings.render_dpi, alpha=False)
                pixmap.save(image_file)

                if self.settings.ocr_enabled and _visible_chars(text) < self.settings.ocr_min_chars:
                    ocr_text = self._ocr(image_file, index, warnings)
                    if len(ocr_text) > len(text):
                        text = ocr_text

                visual_page = self._is_visual_page(page, text)
                visual_summary = self._caption_if_enabled(image_file, index, visual_page, warnings)
                relative_image = str(image_file.relative_to(self.settings.data_dir))
                pages.append(
                    ExtractedPage(
                        number=index,
                        text=text,
                        section=guess_section(text, f"Pagina {index}"),
                        image_path=relative_image,
                        visual_summary=visual_summary,
                    )
                )
        finally:
            document.close()
        return pages

    def _extract_markdown(
        self, source: Path, images_dir: Path, warnings: list[str]
    ) -> list[ExtractedPage]:
        raw = source.read_text(encoding="utf-8")
        blocks: list[tuple[int, str, str]] = []
        page = 1
        section = _title_from_filename(source)
        buffer: list[str] = []

        def flush() -> None:
            if any(line.strip() for line in buffer):
                blocks.append((page, section, "\n".join(buffer).strip()))
                buffer.clear()

        for line in raw.splitlines():
            page_match = PAGE_COMMENT_RE.search(line)
            heading_match = HEADING_RE.match(line)
            if page_match:
                flush()
                page = int(page_match.group(1))
                continue
            if heading_match:
                flush()
                section = heading_match.group(2).strip()
            buffer.append(line)
        flush()

        pages: list[ExtractedPage] = []
        for page_number, page_section, content in blocks:
            copied_image: str | None = None
            for image_ref in IMAGE_RE.findall(content):
                candidate = (source.parent / image_ref.split()[0]).resolve()
                if not candidate.is_file() or not candidate.is_relative_to(source.parent):
                    warnings.append(f"Immagine Markdown non trovata o non sicura: {image_ref}")
                    continue
                target = images_dir / f"p{page_number:04d}-{candidate.name}"
                shutil.copy2(candidate, target)
                copied_image = str(target.relative_to(self.settings.data_dir))
                break
            plain = re.sub(r"!\[([^]]*)]\([^)]+\)", r"Immagine: \1", content)
            plain = re.sub(r"`{1,3}", "", plain).strip()
            summary = None
            if copied_image:
                absolute = self.settings.data_dir / copied_image
                summary = self._caption_if_enabled(
                    absolute, page_number, visual_page=True, warnings=warnings
                )
            pages.append(
                ExtractedPage(
                    number=page_number,
                    text=plain,
                    section=page_section,
                    image_path=copied_image,
                    visual_summary=summary,
                )
            )
        return pages

    def _pages_to_chunks(self, pages: list[ExtractedPage]) -> list[ChunkInput]:
        chunks: list[ChunkInput] = []
        for page in pages:
            combined = page.text
            if page.visual_summary:
                combined = f"{combined}\n\nDescrizione visiva:\n{page.visual_summary}".strip()
            for part in chunk_text(
                combined,
                max_chars=self.settings.chunk_chars,
                overlap_chars=self.settings.chunk_overlap_chars,
            ):
                chunks.append(
                    ChunkInput(
                        page=page.number,
                        section=page.section,
                        content=part,
                        image_path=page.image_path,
                        visual_summary=page.visual_summary,
                    )
                )
        return chunks

    def _ocr(self, image_path: Path, page: int, warnings: list[str]) -> str:
        executable = shutil.which("tesseract")
        if not executable:
            warnings.append(
                "OCR richiesto ma Tesseract non è installato; alcune pagine scansionate "
                "potrebbero non essere ricercabili."
            )
            return ""
        try:
            result = subprocess.run(
                [executable, str(image_path), "stdout", "-l", self.settings.ocr_languages],
                check=True,
                capture_output=True,
                text=True,
                timeout=180,
            )
            return result.stdout.strip()
        except (subprocess.SubprocessError, OSError) as exc:
            warnings.append(f"OCR fallito a pagina {page}: {exc}")
            return ""

    def _caption_if_enabled(
        self,
        image_path: Path,
        page: int,
        visual_page: bool,
        warnings: list[str],
    ) -> str | None:
        should_caption = self.settings.caption_mode == "all" or (
            self.settings.caption_mode == "visual" and visual_page
        )
        if not should_caption:
            return None
        if self.llm is None:
            warnings.append("Descrizione visiva saltata: client LLM non configurato.")
            return None
        try:
            return self.llm.caption_page(image_path)
        except LLMError as exc:
            warnings.append(f"Descrizione visiva fallita a pagina {page}: {exc}")
            return None

    @staticmethod
    def _is_visual_page(page: object, text: str) -> bool:
        try:
            images = bool(page.get_images(full=True))  # type: ignore[attr-defined]
            drawings = len(page.get_drawings()) >= 3  # type: ignore[attr-defined]
            return images or drawings or _visible_chars(text) < 200
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return _visible_chars(text) < 200


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _title_from_filename(path: Path) -> str:
    return re.sub(r"[_-]+", " ", path.stem).strip().title()


def _visible_chars(text: str) -> int:
    return sum(character.isalnum() for character in text)


def _pages_to_markdown(title: str, pages: list[ExtractedPage]) -> str:
    output = [f"# {title}"]
    for page in pages:
        output.extend(
            [
                "",
                f"<!-- pagina: {page.number} -->",
                "",
                f"## {page.section}",
                "",
                page.text or "_Nessun testo estratto._",
            ]
        )
        if page.image_path:
            output.extend(["", f"![Pagina {page.number}]({page.image_path})"])
        if page.visual_summary:
            output.extend(["", "### Descrizione visiva", "", page.visual_summary])
    return "\n".join(output).strip() + "\n"
