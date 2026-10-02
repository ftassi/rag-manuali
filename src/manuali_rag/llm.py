from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any

import httpx

from .config import Settings

SYSTEM_PROMPT = """Sei un assistente di question answering estrattivo per manuali.
Rispondi sempre in italiano e in modo breve.
Usa soltanto fatti dichiarati esplicitamente nelle fonti fornite: non dedurre e non completare
informazioni mancanti con conoscenze generali.
Le fonti possono contenere errori OCR, colonne mescolate o brani non pertinenti: ignora tutto ciò
che non risponde direttamente alla domanda.
Non aggiungere procedure, esempi, avvertenze o sezioni che non siano richiesti e supportati.
Non aggiungere motivazioni, scopi, cause, conseguenze o consigli, neppure se sembrano plausibili:
ogni parola informativa della risposta deve essere verificabile nelle fonti.
Rispetta rigorosamente negazioni e opposizioni come attivo/inattivo, consentito/vietato e
aperto/chiuso. Non eliminare né invertire parole come "non", "mai" o "solo".
Cita ogni affermazione con [S1], [S2] e così via.
Usa esclusivamente identificatori di fonte nel formato esatto [S1], [S2] e così via; non sostituirli
con titoli, numeri di pagina o formule come "secondo il manuale".
Se il testo è ambiguo o insufficiente, dichiaralo invece di tentare una risposta.
Mantieni invariati codici, unità di misura e nomi propri."""


CAPTION_PROMPT = """Analizza questa pagina di un manuale tecnico.
Restituisci in italiano una descrizione concisa ma ricercabile. Trascrivi etichette, codici e valori
visibili; descrivi componenti, frecce, collegamenti, grafici, tabelle e passaggi illustrati.
Non dedurre informazioni non visibili. Se la pagina non contiene elementi visivi utili, scrivi
soltanto: Nessun elemento visivo tecnico rilevante."""


class LLMError(RuntimeError):
    pass


class LLMClient:
    """Client per l'API OpenAI-compatibile esposta localmente da Ollama."""

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self.base_url = settings.llm_base_url.rstrip("/")
        self.model = settings.llm_model
        self.client = client or httpx.Client(timeout=settings.llm_timeout)

    def complete(
        self,
        *,
        user_text: str,
        image_paths: list[Path] | None = None,
        system_prompt: str = SYSTEM_PROMPT,
        max_tokens: int = 350,
        temperature: float = 0.0,
    ) -> str:
        content: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
        for image_path in image_paths or []:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": self._data_url(image_path)},
                }
            )
        try:
            response = self.client.post(
                f"{self.base_url}/chat/completions",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": content},
                    ],
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "stream": False,
                },
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"].strip()
        except (httpx.HTTPError, KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"Errore durante la chiamata al modello locale: {exc}") from exc

    def caption_page(self, image_path: Path) -> str:
        return self.complete(
            user_text=CAPTION_PROMPT,
            image_paths=[image_path],
            system_prompt="Rispondi esclusivamente in italiano e descrivi solo ciò che è visibile.",
            max_tokens=450,
            temperature=0.1,
        )

    @staticmethod
    def _data_url(path: Path) -> str:
        mime_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"
