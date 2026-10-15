# Punto di ripresa — 15 ottobre 2026

## Obiettivo finale

Usare il RAG direttamente dal Raspberry, scrivendo domande e leggendo risposte nel
browser locale anche senza Internet. Manuali, indice e modelli devono restare locali.
Il promemoria operativo aggiornabile è [GUIDA_USO.md](GUIDA_USO.md).

## Riscontro pratico successivo — 15 ottobre 2026

La prova personale sul codice pubblicato `8468371` evidenzia altri limiti:

- Annullamento/correzione di una nota: testo non pertinente, immagine pertinente.
  L'utente ha chiarito di voler correggere una nota già salvata, distinta
  dall'annullamento di modifiche non ancora salvate.
- Visualizzazione delle sole note dell'utente: risposta generica sul dettaglio,
  senza conservare il vincolo sull'autore. Caso non superato.
- Ripristino dei filtri: testo e immagine accettati, istruzioni migliorabili in completezza.
- Richiesta senza operazione specificata: chiarimento corretto, confermato dall'utente.

Il risultato 47/47 riportato sotto resta riferito ai casi del 13 ottobre: non copre
queste nuove formulazioni. L'utente ha confermato l'indirizzo dopo la prova offline;
connessione SSH ripristinata e versione controllata prima della sincronizzazione.

## Correzione della prova pratica — codice `e555e6c`

La selezione conserva il vincolo sull'autore delle note. Le istruzioni di filtro
includono la conferma per applicarle, anche quando è sulla pagina successiva dello
stesso documento. Per le correzioni di contenuti salvati vengono recuperati apertura,
comando di modifica e salvataggio; le righe numerate delle tabelle PDF sono separate
per evitare di trascinare altri controlli. Le anteprime seguono l'ordine delle citazioni.
Se il testo esprime insieme un errore e l'annullamento senza chiarire lo stato di
salvataggio, viene chiesto quale operazione si intende prima di scegliere una procedura.

Sul Raspberry: lint e **67 test** superati sul codice `e555e6c`. Prova mirata
precedente **5/5** sul codice applicativo `ea0a689`, prima del solo riordino delle
anteprime. Casi privati in `data/evaluations/qara-practical-cases-2026-10-15.json`;
report in `qara-practical-report-2026-10-15.json`. Collaudo complessivo ampliato
nel file `qara-all-cases-2026-10-15.json`: 51 casi, inclusi tutti i 47 precedenti.
Per il precedente filtro sulle proprie note è accettata anche pagina 51, verificata
sul manuale: contiene la conferma necessaria per applicare il filtro di pagina 50.
Criterio rivisto annotato nel nuovo file, esiti e criteri storici conservati.
Collaudo completo sul codice `e555e6c`: **51/51 superati via API** con controllo di
fatti, pagine, citazioni e immagini; report privato
`data/evaluations/qara-all-workflows-2026-10-15.json`.
Categorie: 44 positivi, 4 informazioni assenti e 3 richieste ambigue, tutti superati.
Regressione sintetica **11/11** (`/tmp/qara-workflows-e2e.json` sul Raspberry), HTTP
**6/6**, `make health` e `make ollama-check` superati. Prova nella slice locale:
accesso esterno negato dal kernel, interfaccia e nuova procedura della nota salvata
con immagine funzionanti. Entrambi i servizi attivi nella slice locale, senza
riavvii automatici; indice principale invariato, due documenti e 228 chunk.
Non è una nuova prova fisica senza Wi-Fi: il riscontro personale dopo la
correzione resta da eseguire. Modelli e manuali rimangono locali.


## Correzione di recupero e ambiguità — codice `ff00bfc`

Il recupero confronta il catalogo completo dei passaggi con titoli e didascalie reali,
conserva il soggetto e l'azione delle domande colloquiali e completa condizioni,
alternative e liste obbligatorie. Le richieste prive di soggetto ricevono un chiarimento
senza fonti. Le informazioni assenti richiedono astensione; i prezzi devono avere un
riscontro economico esplicito. Le indicazioni visive vengono distinte dalle istruzioni
per aprire una schermata. Nessun caso privato è stato aggiunto come risposta predefinita.

Ollama resta locale con `llama3.2:3b` e `nomic-embed-text-v2-moe`. Corretti i prefissi
Nomic per query e documenti; ricalcolati i 228 vettori dell'indice con backup SQLite,
conservando documenti, chunk e pagine. Aggiunta cache locale dei passaggi. Il confronto
sperimentale con `qwen2.5:1.5b` non ha giustificato il cambio del modello di risposta.
Lint e **62 test** superati sul Raspberry sul commit `ff00bfc`.
Collaudo completo via API: **47/47** (23 casi precedenti più 24 spontanei),
con **41/41 positivi**, **4/4 informazioni assenti**, **2/2 chiarimenti per ambiguità**.
Tutti i positivi hanno superato anche fatti, citazioni, pagine e disponibilità immagini.
Report privato `data/evaluations/qara-all-verified-2026-10-13.json`; criteri nel file
`data/evaluations/qara-all-cases-2026-10-13.json`. Conservati i giri intermedi falliti.
L'indice contiene ancora due documenti e 228 chunk; i manuali non sono pubblicati.
Regressione sintetica **11/11**, HTTP **6/6**, `make health` e `make ollama-check`
superati. Provati interfaccia, domanda QARA e immagine citata nella slice
`manuali-local.slice`: il kernel rifiuta l'accesso esterno con EPERM, mentre le
richieste locali funzionano. Nessuna nuova disconnessione fisica Wi-Fi o riavvio
in questo passaggio; resta valida la precedente prova personale dell'utente.
Report sintetico `/tmp/qara-final-e2e.json` sul Raspberry; entrambi i servizi attivi,
nella slice locale, senza riavvii automatici dopo l'ultimo riavvio del servizio.



## Verifiche precedenti (storico)

Il codice verificato è `df7469e`; `fac3bfc` aggiorna la guida con gli esiti.
Le correzioni separano intestazioni e istruzioni, completano le liste e le alternative,
selezionano i passaggi con embedding locali e affidano i casi ambigui a Ollama.
Le richieste di credenziali iniziali senza riscontro esplicito vengono rifiutate.
Non sono serviti nuovi modelli o una nuova indicizzazione.

Controlli eseguiti sul Raspberry sul codice `df7469e`:

- `make check`: lint superato e **37 test superati**.
- Collaudo QARA: **14/14**, con fatti, pagine, citazioni, completezza delle alternative
  e assenza dei dettagli superflui noti; due domande senza risposta vengono rifiutate.
- Collaudo sintetico end-to-end: **11/11**.
- Controlli HTTP: **6/6**.
- API del servizio principale dopo il riavvio: risposta completa sulle alternative,
  pagina citata accessibile e rifiuto della richiesta di credenziali senza fonti.
- `make health` e `make ollama-check`: superati.

QARA è indicizzato localmente: **201 pagine PDF, 226 chunk**, documento
`cbce3b965bede02f`. Questi risultati coprono i casi provati, non ogni possibile domanda.
Manuali, domande, risposte e report privati non sono versionati su GitHub.

Per ripetere il collaudo dalla copia sul Raspberry:

```bash
cd /home/michele/progetti/rag-manuali
PYTHONIOENCODING=utf-8 make manual-eval \
  CASES=data/evaluations/qara-cases.json \
  MANUAL_EVAL_OUTPUT=data/evaluations/qara-corrected-2026-10-12.json
```

Il report precedente resta in `data/evaluations/qara-expanded-2026-10-12.json`.
I file dei casi e dei report sono locali e ignorati da Git.

## Avvio automatico e collaudo dopo riavvio

Configurazione e script verificati nel commit `389b236`:

- `manuali-rag.service`: abilitato e attivo, utente `michele`, repository sul Raspberry,
  ascolto `127.0.0.1:8000`, ordinato dopo Ollama e riavvio in caso di errore.
- `ollama.service`: abilitato e attivo, ascolto `127.0.0.1:11434`, cloud disabilitato
  con `OLLAMA_NO_CLOUD=true` nel drop-in `manuali-local.conf`.
- `manuali-local.slice`: comune ai due servizi, `IPAddressDeny=any` e
  `IPAddressAllow=localhost`. Il kernel blocca le connessioni esterne; SSH resta operativo.
- Configurazioni installate da `deploy/` dopo sincronizzazione tramite GitHub.

Il Raspberry è stato realmente riavviato il **13 ottobre 2026**. Il boot ID è cambiato
ed entrambi i servizi sono ripartiti automaticamente, senza un avvio manuale.
`make check` ha superato 37 test; dopo il riavvio health e Ollama sono disponibili.

`scripts/check_local_runtime.py`, eseguito nella stessa slice dopo il riavvio, verifica
un rifiuto esplicito del kernel (`EPERM`/`EACCES`) all'invio di un datagramma esterno,
la pagina HTTP, una domanda QARA con fatti/pagine/citazioni attesi e l'immagine citata.
Seguono 6/6 controlli HTTP su un documento sintetico in un indice temporaneo.
Tutto superato; il QARA originale resta l'unico documento nell'indice principale,
con 226 chunk. Il comando ripetibile è nella [guida, sezione 12](GUIDA_USO.md#12-verifica-ripetibile-delluso-locale-senza-rete-esterna).

Questa è una verifica con accesso esterno bloccato per RAG, Ollama e processo di prova.
Non è una prova grafica dei clic né uno scollegamento fisico di Wi-Fi/cavo; la macchina
mantiene la rete necessaria a SSH. La verifica pratica sul desktop resta da fare.
I log permanenti sono consultabili con `journalctl -u manuali-rag -b`.

## Collegamento desktop e prova pratica

Installati **Manuali RAG.desktop** (eseguibile e attendibile) e **prova-offline.md** in
`/home/michele/Desktop`, dal repository sincronizzato tramite GitHub. Installato anche
il collegamento nel menu applicazioni in `~/.local/share/applications`.
Il file `.desktop` è stato verificato con `desktop-file-validate`; usa `xdg-open` sulla
pagina locale, senza avviare un nuovo server. Il browser predefinito è Firefox.
Firefox è stato avviato nella sessione Wayland con la pagina locale e il servizio risponde.
L'utente ha svolto la prova: importazione del Markdown sintetico e risposta con fonte
riuscite offline; due risposte QARA insoddisfacenti. Il risultato complessivo resta parziale.
La procedura è nella guida, sezione 13.

## Ultime correzioni a testo e immagini — codice `16d2b63`

Il linguaggio conversazionale non deve escludere la sezione richiesta dalla ricerca.
Le procedure con titolo corrispondente conservano tutti i passaggi; riferimenti come
«Rif. Par.» non spezzano le frasi; le voci di menu mantengono il comando introduttivo,
con esclusione delle altre voci non richieste. Il testo dell'indice non diventa risposta.
L'interfaccia mostra testo e anteprima delle pagine PDF insieme, con link per ingrandirle;
il placeholder usa esempi dell'ambito dei software sanitari.

Verifiche sul Raspberry: **42 test**, **16/16 QARA**, **11/11 end-to-end**, **6/6 HTTP**.
Le due nuove domande sono nel file privato `data/evaluations/qara-cases.json`; report
`data/evaluations/qara-text-visual-2026-10-13.json`. Domande e contenuti riservati restano
fuori da Git. Le due risposte API hanno testo, citazioni e pagine corrette.
Il servizio è stato riavviato sul codice nuovo. Nel browser del PC, collegato al servizio
Raspberry tramite tunnel SSH locale temporaneo, verificate entrambe le risposte testuali
con immagini caricate; controllata visivamente la schermata testo e anteprima.
Ripetuta con successo la prova con rete esterna bloccata nella slice comune.
L'indice principale contiene QARA e il documento sintetico importato dall'utente.

La prova fisica è stata poi confermata dall’utente: importazione del file sintetico,
pazienti dimessi e login con testo e immagini corretti, con Wi-Fi disattivato.

## Ultimo riscontro dell'utente e varianti login — codice `2e70848`

L'utente conferma risposta testuale e immagine corrette per i pazienti dimessi.
Segnala ancora accesso confuso con firma per «come faccio il login?».
La ricerca trattava «faccio» come argomento, ma escludeva già «fare»:
corrette più forme colloquiali e aggiunti controlli contro la confusione con firma.
Sul Raspberry, **51 test superati** e **otto formulazioni del login via API** superate
con fatti, citazione, pagina 11 e immagine accessibile. Il servizio è stato riavviato.
Collaudo QARA ampliato: **23/23**, regressione sintetica **11/11**, health superato; report privato
`data/evaluations/qara-login-variants-2026-10-13.json`.
Le sette nuove varianti sono nel file privato `data/evaluations/qara-cases.json`.
L’utente ha confermato nel browser anche «come faccio il login?», dopo aver già
confermato «come posso fare il login?» senza Wi-Fi.

## Ultimo collaudo spontaneo — codice `7690ed7`

Aggiunta modalità `--api-url` allo script `scripts/evaluate_manual_cases.py`: interrogazione
HTTP reale con immagini, verifiche su testo, citazioni, pagine e immagini disponibili.
Nessuna modifica al comportamento delle risposte in questo passaggio; codice applicativo
precedentemente validato `2e70848`. Lint e **51 test** superati sul Raspberry.

**24 nuove domande: 8/24 superate dopo revisione.** Positive 6/20, assenti 2/2,
ambigue 0/2. Inizialmente 7/24; accettata e riprovata una pagina alternativa corretta
per la chiusura dei Support Data. Conservati entrambi gli esiti. Dei 14 casi positivi
non superati, 12 hanno testo/sezione non pertinenti o fatti mancanti; 2 rifiutano una
risposta che il manuale contiene. Le due domande senza argomento ricevono istruzioni
arbitrarie. Le immagini servite correttamente non compensano una fonte sbagliata.

Report e casi privati in `data/evaluations/`:
`qara-spontaneous-cases-2026-10-13.json`, `qara-spontaneous-2026-10-13.json`,
`qara-spontaneous-review-case-report.json`, `qara-spontaneous-reviewed-2026-10-13.json`.
Il report rivisto contiene i riferimenti all'originale e al caso riprovato. Dati ignorati
da Git; indice principale invariato, due documenti e 228 chunk. `make health` superato.
La guida, sezione 14, include il comando per ripetere il collaudo sul servizio locale.
I 23/23 casi precedenti non vanno estesi alle nuove formulazioni, che mostrano limiti reali.

## Prossimo passo e opzioni

1. **Consigliato:** ripetere nel browser del Raspberry, con Wi-Fi disattivato,
   i casi pratici di nota salvata, proprie note e ripristino filtri; aggiornare
   con `Ctrl+Shift+R`, verificare testo completo e pagine pertinenti. La nota
   già salvata va specificata nella domanda; la precedente frase ambigua
   deve chiedere di distinguere modifica salvata e annullamento prima del salvataggio.
2. Importare e collaudare un secondo manuale, controllando le risposte tra documenti.
3. Aggiungere il selettore dei manuali per limitare esplicitamente la ricerca.

Le correzioni della prova pratica e il collaudo di 51 casi sono completati sul
Raspberry. Atteso il riscontro personale dopo l'aggiornamento; gli esiti precedenti
restano riferiti al loro codice e ai loro criteri.

## Come riprendere lo sviluppo

Leggere `AGENTS.md` e la guida. Modificare il codice sul PC in
`/home/michele/Progetti/rag-manuali`, eseguire i controlli sul Raspberry in
`/home/michele/progetti/rag-manuali`. Usare l'ultimo IP comunicato nella chat,
senza salvarlo nel repository, e SSH con `-F /dev/null`.

Prima di sincronizzare controllare branch, stato e commit di entrambe le copie.
Il branch verificato è `master`. Pubblicare le modifiche pertinenti su GitHub,
aggiornare il Raspberry con `git pull --ff-only` e verificare il commit prima dei test.
La chiave GitHub del Raspberry non ha funzionato durante questa sessione;
il pull HTTPS dal repository pubblico ha funzionato, senza cambiare il remote:

```bash
git pull --ff-only https://github.com/ftassi/rag-manuali.git master
```

Aggiornare questo punto di ripresa e la guida al termine dei prossimi passaggi.
