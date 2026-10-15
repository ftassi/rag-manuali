# Manuali RAG

Per l'uso quotidiano e come promemoria, consulta la **[Guida pratica al RAG](docs/GUIDA_USO.md)**:
avvio, importazione di nuovi manuali, domande, funzionamento offline e problemi comuni.
Per riprendere lo sviluppo, consulta il **[punto di ripresa verificato](docs/STATO_LAVORO.md)**.

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
- risposte estrattive con embedding locali e `llama3.2:3b` per i casi ambigui, tramite Ollama;
- API FastAPI, CLI e interfaccia web minimale;
- funzionamento interamente locale, senza API cloud.

## Obiettivo e utilizzo offline sul Raspberry

Il sistema finale deve permettere di importare manuali, scrivere domande e leggere risposte
direttamente sul Raspberry, anche senza connessione Internet. Nel browser del Raspberry
aprire `http://127.0.0.1:8000` quando il servizio è avviato. L'interfaccia non carica librerie,
font o altri contenuti da servizi esterni.

Manuali, pagine estratte e indice restano nella cartella locale `data/`, esclusa da Git;
Ollama esegue generazione ed embedding localmente. Gli endpoint dei modelli devono restare
configurati su `http://127.0.0.1:11434/v1`. GitHub serve per sincronizzare il codice durante
lo sviluppo; non è necessario durante l'uso. Installazione delle dipendenze e download
dei modelli richiedono una connessione iniziale.

Il collaudo finale deve includere un riavvio e una prova senza rete: apertura dell'interfaccia,
domanda su un manuale già indicizzato, consultazione della pagina citata e importazione
di un nuovo file locale. Questa verifica è distinta dai test automatici su dati sintetici.

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

Con gli embedding Ollama la ricerca confronta il catalogo completo dei passaggi,
con i titoli di sezione e le didascalie reali come contesto. I vettori dei passaggi sono
memorizzati in una cache SQLite locale, distinta dai chunk: non cambiano documenti,
pagine o citazioni. Il primo uso dopo un aggiornamento può richiedere più tempo.
Nomic usa `search_query:` per le domande e `search_document:` per i documenti,
come indicato nella [documentazione del modello](https://huggingface.co/nomic-ai/nomic-embed-text-v2-moe).

La scelta del documento avviene automaticamente dai contenuti della domanda.
Per le guide con capitoli numerati semplici, il recupero mantiene gerarchia delle
sezioni e continuità fra pagine: i titoli sono contesto, le procedure e gli elenchi
conservano i passi necessari e le etichette dei parametri. Il contesto aiuta a
distinguere il soggetto della sezione dai riferimenti ad altri sistemi. Il nome del file non
è una regola di classificazione. I casi incerti fra contesti equivalenti richiedono
un chiarimento; operazioni esplicite in sequenza possono citare più manuali.
La cache locale include il testo del contesto, quindi cambia quando cambiano le fonti.

Le richieste senza un argomento concreto ricevono una domanda di chiarimento senza fonti.
Le risposte riportano testo originale: procedure nominate, liste obbligatorie e passaggi
completi fortemente pertinenti vengono selezionati dal programma; nei casi incerti
`llama3.2:3b` sceglie fra poche citazioni esatte. La selezione diretta richiede sia un punteggio
almeno `MANUALI_ANSWER_UNIT_MIN_SIMILARITY=0.70` sia copertura lessicale del soggetto.
Questa soglia riguarda le singole frasi; il recupero di procedure strutturate
confronta invece contesti di sezione e parametri, conservando i passi correlati.
Il punteggio combina similarità e corrispondenza dei termini nel contesto, non è una probabilità.
`MANUALI_ANSWER_AMBIGUITY_MARGIN=0.02` limita l'aggiunta di fonti meno pertinenti.
Condizioni e alternative necessarie vengono conservate, mentre altre voci di menu non
sono incluse automaticamente. Il fallback hash mantiene la selezione ibrida dei chunk.
Se il modello restituisce testi non presenti fra i passaggi offerti, il sistema richiede
una correzione e poi segnala la mancata verifica.
Questo controllo impedisce testo aggiunto, ma non garantisce che il modello scelga tutti
i passaggi necessari o interpreti correttamente quale risponde alla domanda.

Per ripetere un collaudo su manuali reali con domande e criteri privati:

```bash
make manual-eval CASES=./data/evaluations/casi.json
```

Il JSON deve contenere un elenco `cases` con `id`, `question`, `expected_pdf_pages`,
`required_terms` e, se necessario, `forbidden_terms` o `expect_abstention`.
I report vengono salvati in `data/evaluations/`, fuori da Git. Non pubblicare questi file:
possono contenere estratti dei manuali. Il comando termina con errore se un caso non passa.

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
idempotente, la ricerca, tre risposte live, lo smoke test HTTP e il collaudo dell'interfaccia con
Firefox headless; non utilizza né conserva manuali reali. Per ricontrollare i report senza
rieseguire i modelli usare `make regression-check`. Il solo test del flusso di importazione si può
lanciare con `make ingestion-eval`.

La regressione include anche un caso dedicato alle negazioni operative e alle coppie opposte
(`attivo/inattivo`), derivato in forma sintetica dal primo collaudo controllato su un manuale
reale. Il testo del manuale reale non viene incluso nei report o nel repository.

Per verificare anche il server web reale, l'upload multipart e gli endpoint HTTP senza conservare
dati di prova usare `make smoke-http`. Il comando avvia Uvicorn soltanto su `127.0.0.1`, sceglie
una porta locale libera e rimuove il manuale sintetico e il database temporaneo al termine.

Per collaudare anche i controlli dell'interfaccia in un browser reale usare `make smoke-ui`.
Il test guida Firefox in modalità headless attraverso upload e domanda, verifica risposta e fonti
e salva report e screenshot in `benchmark-results/ui-smoke.*`. Richiede Firefox e le dipendenze
di sviluppo installate da `make init`; anche in questo caso i dati sintetici sono temporanei.

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

Il file [deploy/manuali-rag.service](deploy/manuali-rag.service) usa l'utente `michele`
e il percorso verificato sul Raspberry. Adattarli per altre installazioni.
La slice comune limita RAG e Ollama alle connessioni locali tramite il filtro IP di systemd
(richiede supporto BPF del kernel). Verificare che la porta 8000 sia libera, poi installare:

```bash
sudo install -m 644 deploy/manuali-rag.service deploy/manuali-local.slice /etc/systemd/system/
sudo install -d /etc/systemd/system/ollama.service.d
sudo install -m 644 deploy/ollama-local.conf /etc/systemd/system/ollama.service.d/manuali-local.conf
sudo systemctl daemon-reload
sudo systemctl restart ollama
sudo systemctl enable --now manuali-rag
```

Il servizio RAG richiede l'avvio di Ollama e ascolta su `127.0.0.1:8000`.
Per stato e log usare `systemctl status manuali-rag` e `journalctl -u manuali-rag`.
La limitazione di rete riguarda questi servizi, senza interrompere SSH o il resto del sistema.

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


### Aggiornamento dei vettori di un indice esistente

Dopo un cambiamento del modello embedding o dei prefissi delle richieste, eseguire sul
Raspberry (con il RAG fermo):

```bash
cd /home/michele/progetti/rag-manuali
sudo systemctl stop manuali-rag
.venv/bin/manuali-rag reembed
sudo systemctl start manuali-rag
```

`reembed` calcola i vettori prima dell'aggiornamento e crea un backup SQLite in
`data/backups/`. Mantiene i chunk, le pagine, i documenti e i riferimenti; rifiuta l'aggiornamento
se il contenuto dell'indice è cambiato durante il calcolo. Non serve reimportare il PDF.
Questa manutenzione usa i modelli già disponibili localmente.
