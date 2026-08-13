# Manuali RAG

Prototipo locale per importare manuali PDF o Markdown e porre domande in italiano. Le risposte
sono prodotte da un modello vision-language eseguito con `llama.cpp` e includono i riferimenti
al manuale e alla pagina.

## Cosa include

- estrazione del testo e rendering delle pagine PDF con PyMuPDF;
- OCR italiano/inglese opzionale tramite Tesseract;
- descrizione indicizzabile di diagrammi e pagine visive tramite il VLM;
- importazione Markdown con commenti di pagina;
- chunking per pagina e conservazione dei metadati;
- indice ibrido SQLite FTS5 + embedding;
- risposte multimodali con le pagine recuperate come input visivo;
- API FastAPI, CLI e interfaccia web minimale;
- funzionamento interamente locale, senza API cloud.

## Requisiti

- Python 3.11 o successivo;
- Raspberry Pi OS 64 bit oppure una distribuzione Linux ARM64;
- `llama.cpp` recente con supporto multimodale `libmtmd`;
- circa 4–6 GB di RAM libera per VLM, embedding e applicazione;
- raffreddamento attivo consigliato sul Raspberry Pi 5.

Per PDF scansionati:

```bash
sudo apt install tesseract-ocr tesseract-ocr-ita tesseract-ocr-eng
```

## Installazione dell'applicazione

Percorso rapido con Make:

```bash
make init
make check
make start
```

Per importare e interrogare un manuale:

```bash
make ingest FILE=./manuali/caldera-x100.pdf
make ask QUESTION="Come sostituisco il filtro?"
```

Usare `make help` per vedere tutti i target. Per avviare l'API senza un server embedding,
solo per una prova del retrieval lessicale, usare `make start-dev`.

In alternativa, l'installazione manuale è:

```bash
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e .
cp .env.example .env
```

Il file `.env` viene letto automaticamente dalla CLI e dall'API.

## Avvio rapido senza modello di embedding

Questa modalità consente di provare importazione e ricerca. L'embedding hash non comprende
davvero la semantica e non è adatto alla produzione.

Modificare in `.env`:

```dotenv
MANUALI_EMBEDDING_PROVIDER=hash
MANUALI_CAPTION_MODE=off
```

Quindi:

```bash
.venv/bin/manuali-rag ingest percorso/manuale.md
.venv/bin/manuali-rag search "Cosa significa il codice E104?"
.venv/bin/manuali-rag serve
```

Aprire `http://raspberrypi.local:8000`.

## Configurazione completa con llama.cpp

Installare e compilare il runtime dal repository ufficiale:

```bash
make llama-install
make llama-version
```

Il target installa i prerequisiti con `apt` e compila una build Release ottimizzata per la
macchina corrente in `.local/llama.cpp`. Eseguirlo nuovamente aggiorna il clone con
`git pull --ff-only` e ricompila.

Sono previsti due processi locali:

1. porta 8080: modello multimodale per risposte e immagini;
2. porta 8081: piccolo modello di embedding per il retrieval.

Esempio VLM, con nomi dei file da adattare ai GGUF scaricati:

```bash
.local/llama.cpp/build/bin/llama-server \
  -m models/Qwen3VL-2B-Instruct-Q4_K_M.gguf \
  --mmproj models/mmproj-Qwen3-VL-2B-Instruct-Q8_0.gguf \
  --ctx-size 8192 --threads 4 \
  --host 127.0.0.1 --port 8080
```

In alternativa si può provare Gemma 4 E2B-it Q4 con il relativo file `mmproj`.

Esempio server embedding:

```bash
.local/llama.cpp/build/bin/llama-server \
  -m models/embeddinggemma-300m-Q8_0.gguf \
  --embedding --pooling mean --ctx-size 2048 --threads 4 \
  --host 127.0.0.1 --port 8081
```

Verificare il pooling raccomandato nella model card della specifica conversione GGUF. La
configurazione applicativa predefinita è già predisposta per queste due porte:

```dotenv
MANUALI_LLM_BASE_URL=http://127.0.0.1:8080/v1
MANUALI_LLM_MODEL=qwen3-vl-2b-instruct
MANUALI_EMBEDDING_PROVIDER=openai
MANUALI_EMBEDDING_BASE_URL=http://127.0.0.1:8081/v1
MANUALI_EMBEDDING_MODEL=embeddinggemma-300m
```

Il termine `openai` indica soltanto il formato compatibile dell'API: le richieste restano sul
Raspberry Pi.

## Importazione

```bash
manuali-rag ingest ./manuali/caldera-x100.pdf
manuali-rag documents
```

Per attivare OCR e descrizione preventiva delle pagine visive:

```dotenv
MANUALI_OCR_ENABLED=true
MANUALI_OCR_LANGUAGES=ita+eng
MANUALI_CAPTION_MODE=visual
```

Le modalità di descrizione sono:

- `off`: nessuna descrizione durante l'importazione;
- `visual`: descrive pagine con immagini, disegni o poco testo;
- `all`: descrive ogni pagina, più accurato ma molto lento sul Pi.

Per un PDF lungo conviene iniziare con `off`, verificare il retrieval e successivamente
reimportare con `--force` e `visual`.

I Markdown possono indicare la pagina originale così:

```markdown
<!-- pagina: 42 -->

## Sostituzione del filtro

Testo della procedura...

![Schema](images/schema-filtro.png)
```

## Domande

```bash
manuali-rag ask "Come sostituisco il filtro e quali avvertenze devo seguire?"
```

Oppure tramite API:

```bash
curl -X POST http://127.0.0.1:8000/api/questions \
  -H 'Content-Type: application/json' \
  -d '{"question":"Cosa significa E104?","top_k":5,"include_images":true}'
```

Endpoint principali:

- `POST /api/documents`: upload e indicizzazione;
- `GET /api/documents`: manuali disponibili;
- `POST /api/search`: solo retrieval, utile per diagnosi;
- `POST /api/questions`: retrieval e risposta;
- `GET /api/health`: configurazione e dimensione dell'indice.

La documentazione OpenAPI è disponibile su `/docs`.

## Deploy come servizio

Il file [deploy/manuali-rag.service](deploy/manuali-rag.service) è un esempio systemd. Adattare
utente e percorso, poi installarlo:

```bash
sudo cp deploy/manuali-rag.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now manuali-rag
```

I due processi `llama-server` andrebbero configurati come servizi systemd separati e avviati
prima dell'applicazione.

## Test

```bash
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
.venv/bin/ruff check .
```

## Limiti del prototipo

- l'importazione avviene nella richiesta HTTP e può richiedere minuti;
- l'indice vettoriale viene scandito in memoria: adeguato a un prototipo, non a milioni di chunk;
- un Markdown caricato via browser non può includere automaticamente le immagini adiacenti;
- una pagina puramente illustrata è recuperabile meglio se `MANUALI_CAPTION_MODE=visual`;
- la qualità va misurata con domande italiane reali e con le quantizzazioni effettivamente usate.
