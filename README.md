# Manuali RAG

Prototipo locale per importare manuali PDF o Markdown e porre domande in italiano. Le risposte
sono prodotte da un modello locale eseguito con Ollama e includono i riferimenti
al manuale e alla pagina.

## Cosa include

- estrazione del testo e rendering delle pagine PDF con PyMuPDF;
- OCR italiano/inglese opzionale tramite Tesseract;
- descrizione opzionale di diagrammi e pagine visive (richiede un modello Ollama vision);
- importazione Markdown con commenti di pagina;
- chunking per pagina e conservazione dei metadati;
- indice ibrido SQLite FTS5 + embedding;
- risposte testuali con `llama3.2:3b` tramite l'API locale di Ollama;
- API FastAPI, CLI e interfaccia web minimale;
- funzionamento interamente locale, senza API cloud.

## Requisiti

- Python 3.11 o successivo;
- Raspberry Pi OS 64 bit oppure una distribuzione Linux ARM64;
- Ollama con il modello `llama3.2:3b` già scaricato;
- circa 3–4 GB di RAM libera per modello e applicazione;
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
make ollama-check
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

## Configurazione con Ollama

Ollama deve essere in esecuzione e il modello deve essere disponibile localmente. Il progetto non
installa runtime o modelli:

```bash
make ollama-check
ollama list
```

I modelli locali richiesti sono `llama3.2:3b` e `nomic-embed-text-v2-moe`. Se il secondo non è
ancora presente, scaricarlo con `ollama pull nomic-embed-text-v2-moe` (circa 958 MB).

La configurazione predefinita usa l'endpoint OpenAI-compatibile di Ollama:

```dotenv
MANUALI_LLM_BASE_URL=http://127.0.0.1:11434/v1
MANUALI_LLM_MODEL=llama3.2:3b
MANUALI_EMBEDDING_PROVIDER=openai
MANUALI_EMBEDDING_BASE_URL=http://127.0.0.1:11434/v1
MANUALI_EMBEDDING_MODEL=nomic-embed-text-v2-moe
MANUALI_CAPTION_MODE=off
MANUALI_MAX_IMAGES_PER_QUESTION=0
```

`llama3.2:3b` è testuale, quindi caption e immagini sono disattivate.
`nomic-embed-text-v2-moe` fornisce il retrieval semantico multilingue tramite Ollama;
l'embedding hash resta disponibile soltanto per sviluppo. Tutte le richieste rimangono sul
Raspberry Pi.

## Benchmark sul Raspberry Pi

Il benchmark esegue un warm-up e tre prompt italiani deterministici, poi salva tempi, token e
token/s restituiti dall'API nativa di Ollama:

```bash
make benchmark
```

Il risultato predefinito è `benchmark-results/llama3.2-3b.json`. Per cambiare destinazione:

```bash
make benchmark BENCHMARK_OUTPUT=/tmp/llama3.2-3b.json
```

Per confrontare end-to-end i modelli su fonti tecniche sintetiche, senza manuali reali:

```bash
make rag-eval
```

La valutazione controlla retrieval, fatti attesi, dettagli vietati e citazioni, salvando il
confronto in `benchmark-results/rag-model-comparison.json`.

Per confrontare l'embedding hash con `nomic-embed-text-v2-moe` su query italiane parafrasate:

```bash
make embedding-eval
```

Il report viene salvato in `benchmark-results/embedding-comparison.json`.

Per calibrare i pesi del retrieval ibrido FTS5 + embedding con Reciprocal Rank Fusion:

```bash
make hybrid-eval
```

Il report viene salvato in `benchmark-results/hybrid-retrieval-comparison.json`.

I pesi predefiniti sono bilanciati (`semantic=1.0`, `lexical=1.0`, `rrf_k=60`) e possono essere
modificati con `MANUALI_RETRIEVAL_SEMANTIC_WEIGHT`, `MANUALI_RETRIEVAL_LEXICAL_WEIGHT` e
`MANUALI_RETRIEVAL_RRF_K`.

Per limitare la contaminazione, la generazione usa normalmente la prima fonte e include la
seconda solo quando la differenza di similarità è al massimo
`MANUALI_ANSWER_AMBIGUITY_MARGIN=0.02`.

Per valutare insieme retrieval, risposta e citazioni senza limitare la ricerca a un documento:

```bash
make e2e-eval
```

Il report viene salvato in `benchmark-results/end-to-end-v2-llama3.2.json`.

## Regressione sul Raspberry Pi

Per eseguire test, lint e tutti i controlli live su Ollama con soglie automatiche:

```bash
make regression
```

I report vengono salvati in `benchmark-results/regression/`. Il comando termina con codice non
zero se peggiorano accuratezza top-1/top-3, MRR, risposte end-to-end o latenza mediana. La suite
include inoltre l'importazione completa di un Markdown sintetico temporaneo, la reimportazione
idempotente, la ricerca, tre risposte live e lo smoke test del server HTTP reale; non utilizza né
conserva manuali reali. Per ricontrollare i report senza rieseguire i modelli usare
`make regression-check`. Il solo test del flusso di importazione si può lanciare con
`make ingestion-eval`.

Per verificare anche il server web reale, l'upload multipart e gli endpoint HTTP senza conservare
dati di prova usare `make smoke-http`. Il comando avvia Uvicorn soltanto su `127.0.0.1`, sceglie
una porta locale libera e rimuove il manuale sintetico e il database temporaneo al termine.

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

Il servizio Ollama deve essere avviato prima dell'applicazione.

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
