# Guida pratica al RAG dei manuali

Ultimo aggiornamento: **12 ottobre 2026**. Questa guida è un promemoria da mantenere
insieme al codice: descrive le funzioni disponibili e distingue quelle ancora da completare.

## 1. A cosa serve e dove funziona

Il RAG permette di importare manuali PDF o Markdown, fare domande in italiano e leggere
risposte accompagnate dalle pagine di riferimento. L'obiettivo finale è usarlo direttamente
sul Raspberry Pi, anche senza Internet, con schermo, tastiera e browser.

I manuali, il testo estratto, le immagini delle pagine e l'indice restano sul Raspberry.
Ollama esegue localmente i modelli per ricerca e risposta. GitHub contiene il codice e
questa guida; non serve durante l'uso ordinario.

**Stato attuale:** importazione, domande e consultazione delle pagine sono disponibili.
L'avvio automatico dopo l'accensione e il collaudo completo dopo un riavvio senza rete
restano da completare. Non considerare una sessione avviata in background come un servizio
già configurato per ripartire dopo ogni riaccensione.

## 2. Promemoria rapido

1. Sul Raspberry apri il browser su **http://127.0.0.1:8000**.
2. Se appare «Manuali locali», il RAG è già avviato: non avviarlo una seconda volta.
3. Per aggiungere un manuale, scegli il file in **Importa un manuale** e premi
   **Importa e indicizza**. Aspetta la conferma prima di fare domande sul nuovo documento.
4. Scrivi una domanda precisa e premi **Cerca nei manuali**.
5. Leggi la risposta e controlla le fonti con **Apri la pagina**.

`127.0.0.1` indica la macchina su cui è aperto il browser: questo indirizzo va usato
**nel browser del Raspberry**, non in quello di un altro PC.

## 3. Se il RAG non è avviato

Apri un terminale sul Raspberry:

```bash
cd /home/michele/progetti/rag-manuali
make health
```

Se compare un risultato con `"status":"ok"`, il servizio risponde già. Se il collegamento
alla porta 8000 fallisce, verifica se la porta è occupata prima di avviare un altro processo:

```bash
ss -ltnp 'sport = :8000'
make ollama-check
```

Se la porta è libera e il controllo Ollama riesce:

```bash
make start HOST=127.0.0.1
```

Lascia aperto quel terminale e usa il browser. Per arrestare **questo avvio manuale in primo
piano**, premi `Ctrl+C` nel suo terminale. Chiudendo quel terminale puoi arrestare il RAG.
Se la porta è occupata ma la pagina non funziona, consulta la sezione sui problemi comuni.

I modelli locali attesi sono `llama3.2:3b` per le risposte e `nomic-embed-text-v2-moe`
per la ricerca semantica. Non usare `make start-dev` per il normale utilizzo: è una modalità
di sviluppo con una ricerca diversa da quella collaudata.

## 4. Come aggiungere altri manuali

### Dal browser: metodo consigliato

Il file può essere sul disco del Raspberry oppure su una chiavetta USB. Non devi copiarlo
in una cartella particolare: selezionalo nella pagina e premi **Importa e indicizza**.
Sono supportati `.pdf`, `.md` e `.markdown`, un file alla volta.

L'importazione estrae il contenuto, prepara le pagine e calcola gli embedding. Può richiedere
minuti su un manuale lungo; il browser può sembrare fermo mentre lavora. Attendi il messaggio
con titolo, pagine e sezioni indicizzate. Il programma conserva una copia locale del file.

### Da una cartella, tramite terminale

Puoi tenere gli originali, per esempio, in `/home/michele/Documents/conoscienza_rag`.
**Copiarli nella cartella non avvia l'importazione:** attualmente non esiste una scansione
automatica delle cartelle. Per ogni file:

```bash
cd /home/michele/progetti/rag-manuali
make ingest FILE="/home/michele/Documents/conoscienza_rag/nuovo-manuale.pdf"
make documents
```

Le virgolette sono necessarie quando il percorso contiene spazi. L'elenco restituito da
`make documents` permette di verificare quali manuali sono stati effettivamente indicizzati.

### Duplicati e nuove revisioni

Un file identico già importato viene riconosciuto dal contenuto e non viene duplicato.
Rinominare un file identico non lo rende un nuovo manuale. Un PDF modificato, anche se
ha lo stesso nome, viene invece indicizzato come un documento distinto.

**Una nuova revisione non elimina automaticamente quella vecchia.** Conserva negli originali
nomi con versione o data. Se devi sostituire una revisione senza mantenere la vecchia
nell'indice, chiedi una gestione esplicita: l'interfaccia attuale non offre un pulsante per
rimuovere documenti. Non cancellare a mano `data/documents` o il database per farlo.

Per reindicizzare lo stesso file, ad esempio dopo una modifica dell'OCR, esiste:

```bash
make ingest FILE="/percorso/manuale.pdf" FORCE=1
```

Questa operazione ricalcola l'indice del documento identico; non è un comando per eliminare
altre versioni del manuale.

## 5. Come fare domande e controllare le risposte

Indica il modulo, il nome del controllo o l'operazione. Preferisci una domanda su un punto
concreto a una richiesta molto generica. Quando il vincolo conta, chiedilo esplicitamente:
«Quando si abilita questo pulsante?» oppure «Questa operazione è consentita in quello stato?».

Le risposte riportano estratti del manuale. Il modello seleziona frasi numerate; il programma
mostra il testo originale e la relativa citazione `[S1]`, `[S2]`, ecc. Le fonti inutilizzate
non sono mostrate nelle risposte verificate. Il controllo evita frasi inventate, ma non
garantisce che le frasi selezionate rispondano alla domanda o che la risposta sia completa.

Apri sempre la pagina citata per le procedure importanti. La pagina indicata dal RAG è
**la posizione nel PDF**: copertine o fogli di approvazione possono creare una differenza
rispetto al numero stampato nel manuale.

Se compare «Le fonti fornite non contengono questa informazione», prova a riformulare la
domanda o a cercare nel PDF. Questa frase non certifica che l'informazione sia assente
dall'intero manuale. Se compare «Non riesco a ricavare una risposta verificabile…», la
selezione del modello non ha superato i controlli: consulta le pagine proposte.

### Più manuali nell'indice

La pagina web attuale cerca in tutti i manuali indicizzati e non ha un selettore del documento.
Specificare il nome del prodotto e della funzione aiuta, ma non impone un filtro rigido.
Per limitare una domanda a un documento dal terminale:

```bash
make documents
.venv/bin/manuali-rag ask "La mia domanda" --document-id ID_DOCUMENTO --no-images
```

Sostituisci `ID_DOCUMENTO` con il campo `id` dell'elenco. Per vedere soltanto i passaggi
recuperati, senza generare una risposta:

```bash
make search QUESTION="La mia domanda"
```

### Limiti osservati nel collaudo reale

Il collaudo QARA del 12 ottobre ha rilevato che una domanda su un'informazione assente
può ricevere frasi non pertinenti invece di una mancata risposta. Ha rilevato anche domande
che trovano la pagina corretta ma restano senza risposta, risposte con frasi superflue e
una risposta incompleta sulle alternative previste dalla configurazione.

Quando chiedi un valore, una credenziale, una condizione o un elenco di alternative,
controlla che la pagina contenga proprio quell'informazione: una citazione non basta.
Non interpretare un estratto su un altro argomento come la risposta alla tua domanda.
Se la risposta dipende da configurazione o permessi, verifica il contesto e tutte le
alternative nella pagina citata. Questi limiti devono essere corretti e ricollaudati.

## 6. Uso offline e riservatezza

Dopo installazione e download dei modelli, ricerca, risposte e importazione di file locali
usano componenti locali. Nel file `.env`, gli indirizzi dei modelli devono restare:

```dotenv
MANUALI_LLM_BASE_URL=http://127.0.0.1:11434/v1
MANUALI_EMBEDDING_BASE_URL=http://127.0.0.1:11434/v1
MANUALI_EMBEDDING_PROVIDER=openai
```

In questa configurazione, il nome del provider `openai` indica il formato dell'API compatibile
esposta da Ollama: gli indirizzi sopra puntano al Raspberry, non a un servizio cloud.
L'interfaccia principale non carica librerie o font da Internet. Installare dipendenze,
scaricare modelli nuovi e aggiornare da GitHub richiede invece una connessione.

`make start HOST=127.0.0.1` permette l'accesso solo sul Raspberry. L'avvio predefinito
`make start` ascolta anche sulle interfacce di rete; è utile durante il collaudo da un altro
PC. Per l'uso personale sul Raspberry è preferibile l'indirizzo di ascolto locale.

Il codice esclude da Git `data/`, `.env` e `.venv/`. Tieni anche gli originali dei manuali
fuori dal repository. Non aggiungere manuali, estratti, screenshot di pagine o report con
risposte reali a commit, issue o allegati pubblici.

Il collaudo finale senza rete deve ancora verificare: riavvio, apertura del browser locale,
domanda su un documento già indicizzato, apertura della pagina e importazione di un file
locale. La connessione SSH dal PC non va confusa con l'uso locale del Raspberry.

## 7. Dove sono i dati e come conservarli

Con la configurazione predefinita:

| Contenuto | Percorso sul Raspberry |
| --- | --- |
| Codice e questa guida | `/home/michele/progetti/rag-manuali` |
| Configurazione locale | `/home/michele/progetti/rag-manuali/.env` |
| Indice | `/home/michele/progetti/rag-manuali/data/manuali.sqlite3` |
| Copie dei manuali e pagine | `/home/michele/progetti/rag-manuali/data/documents` |
| Originali, se usi la cartella concordata | `/home/michele/Documents/conoscienza_rag` |

`MANUALI_DATA_DIR` può cambiare la posizione di `data/`. Gli originali e il contenuto di
`data/` sono distinti dal codice: un aggiornamento Git non li trasferisce fra macchine.

Per un backup su disco o chiavetta locale, arresta prima il RAG e attendi la fine delle
importazioni e dei comandi CLI. Copia **l'intera cartella `data/`**, il file `.env` e gli
originali; non copiare soltanto il database mentre è in uso. Conserva separatamente anche
i modelli se vuoi poter reinstallare tutto senza Internet. Non caricare questo backup
su GitHub. Per un ripristino, mantieni insieme database e pagine corrispondenti.

## 8. Problemi comuni

| Problema | Cosa controllare |
| --- | --- |
| Il browser non apre la pagina | Sei sul Raspberry? Usa `127.0.0.1:8000`, poi `make health` e il controllo della porta. |
| Porta 8000 occupata | Non avviare duplicati. Identifica il processo con `ss -ltnp 'sport = :8000'`. |
| Ollama non risponde o manca un modello | Esegui `make ollama-check` e `ollama list`. Un modello mancante va scaricato quando sei online. |
| Il nuovo manuale non compare | Copiarlo in una cartella non basta: importalo e verifica con `make documents`. |
| Risposta incompleta o fonte estranea | Apri la pagina, riformula con il nome della funzione; per la diagnosi usa `make search`. |
| PDF scansionato poco leggibile | L'OCR può essere necessario. Va configurato e verificato prima di reimportare con `FORCE=1`. |
| Immagini mancanti in un Markdown caricato dal browser | Il caricamento non include automaticamente i file immagine presenti accanto al Markdown. |
| Schema o immagine non compresi | Il modello attuale è testuale: vedere la pagina non significa che il RAG ne comprenda il disegno. |
| Errore `UnicodeEncodeError` nel terminale SSH | Prima dei comandi esegui `export PYTHONIOENCODING=utf-8`. |

Per controllare il codice sul Raspberry: `make check`. Per vedere i target disponibili:
`make help`. Non eseguire una nuova installazione o una regressione completa per ogni domanda.

## 9. Aggiornamenti del codice dal PC

Il codice viene modificato sul PC in `/home/michele/Progetti/rag-manuali`; test e modelli
vengono eseguiti sul Raspberry in `/home/michele/progetti/rag-manuali`.

Durante una sessione di manutenzione, comunica l'IP attuale del Raspberry. Non serve
memorizzare un IP fisso. Dal PC, la verifica del collegamento è:

```bash
ssh -F /dev/null -o BatchMode=yes -o ConnectTimeout=8 michele@<IP_CORRENTE> 'hostname'
```

Non inserire letteralmente `<IP_CORRENTE>`: sostituiscilo con l'indirizzo del momento.
Il browser aperto direttamente sul Raspberry continua a usare `127.0.0.1`, qualunque sia l'IP
di rete. Non inviare password nella chat.

Prima di sincronizzare si controllano branch, commit e modifiche locali su entrambe le
macchine. Le modifiche pertinenti vengono pubblicate su GitHub e recuperate sul Raspberry
con `git pull --ff-only`, senza sovrascrivere lavori locali. Il branch attuale è `master`,
ma va ricontrollato durante ogni manutenzione.

Sul Raspberry l'accesso SSH a GitHub ha mostrato un problema di chiave. Per leggere il
repository, al momento è disponibile il percorso HTTPS:

```bash
cd /home/michele/progetti/rag-manuali
git status --short
git branch --show-current
git pull --ff-only https://github.com/ftassi/rag-manuali.git master
```

Usalo soltanto se sei sul branch corretto e non ci sono modifiche da preservare. Questo non
cambia il remote configurato. Dopo un aggiornamento del codice, verifica il commit,
esegui i controlli necessari e riavvia il processo RAG per caricare le modifiche.

## 10. Come mantenere aggiornata questa guida

La guida principale è questo file, raggiungibile anche dal [README](../README.md).
Puoi leggerla su GitHub quando sei online o direttamente nella copia locale sul Raspberry
quando sei offline, con un editor di testo.

A ogni cambiamento dell'uso del RAG:

1. Aggiorna la sezione interessata, distinguendo funzioni presenti e funzioni future.
2. Verifica i comandi sul Raspberry quando la modifica riguarda operazioni eseguibili.
3. Aggiorna la data iniziale e aggiungi una voce nel registro seguente.
4. Pubblica la guida insieme al codice tramite GitHub e aggiorna la copia sul Raspberry.

Puoi chiedere a Codex: «Aggiorna `docs/GUIDA_USO.md` con le nuove funzioni e i comandi
verificati». Il file può anche essere modificato con l'editor di GitHub: in quel caso
sincronizza le copie locali prima del lavoro successivo. Non inserire contenuti dei manuali
riservati nella guida o nella cronologia pubblica.

### Registro degli aggiornamenti

- **12 ottobre 2026:** prima guida pratica; avvio manuale, importazione, domande, fonti,
  revisioni dei documenti, uso locale/offline, backup e manutenzione tramite GitHub;
  aggiunti risultati e limiti del collaudo reale QARA.

## 11. Collaudi e prossimi passi

- Il collaudo sintetico del codice `820a925` ha superato 11/11 casi.
- **Collaudo reale QARA, 12 ottobre 2026, codice `820a925`:** 14 domande, di cui 12 su
  informazioni presenti e 2 su informazioni assenti. Dopo il controllo della pagina
  alternativa corretta, 11/12 domande positive contengono i fatti e le fonti attesi;
  1/2 domande negative viene rifiutata correttamente. Questi numeri non certificano
  la qualità completa: cinque risposte includono dettagli superflui e una è incompleta
  sulle alternative di configurazione. Il riepilogo dei controlli su fatti/fonti è 12/14,
  distinto dall'accuratezza complessiva delle risposte.
- Il report dettagliato e la revisione restano sul Raspberry in
  `data/evaluations/qara-expanded-2026-10-12.json`, fuori da Git. Domande, risposte ed
  estratti del manuale non vengono pubblicati nella guida.
- Da completare: avvio automatico, prova dopo riavvio senza rete e scelta del modo più
  comodo di accedere alla pagina dal desktop del Raspberry.

Il prossimo passaggio consigliato è correggere la gestione delle domande senza risposta
e la selezione delle frasi, poi ripetere il collaudo reale. Le alternative sono ampliare
ulteriormente le domande oppure predisporre l'avvio automatico locale tenendo espliciti
i limiti attuali. Dopo le correzioni: avvio automatico e prova senza rete. Miglioramenti
successivi possono includere selettore dei manuali e gestione delle revisioni.
