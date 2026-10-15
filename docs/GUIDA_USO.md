# Guida pratica al RAG dei manuali

Ultimo aggiornamento: **13 ottobre 2026**. Questa guida è un promemoria da mantenere
insieme al codice: descrive le funzioni disponibili e distingue quelle ancora da completare.

## 1. A cosa serve e dove funziona

Il RAG permette di importare manuali PDF o Markdown, fare domande in italiano e leggere
risposte accompagnate dalle pagine di riferimento. L'obiettivo finale è usarlo direttamente
sul Raspberry Pi, anche senza Internet, con schermo, tastiera e browser.

I manuali, il testo estratto, le immagini delle pagine e l'indice restano sul Raspberry.
Ollama esegue localmente i modelli per ricerca e risposta. GitHub contiene il codice e
questa guida; non serve durante l'uso ordinario.

**Stato attuale:** importazione, domande e consultazione delle pagine sono disponibili.
RAG e Ollama sono configurati come servizi automatici con accesso solo alla rete locale
loopback. La prova ripetibile blocca le connessioni esterne dei servizi, mantenendo SSH
disponibile; la prova con Wi-Fi/cavo fisicamente scollegati va distinta da questo controllo.

## 2. Promemoria rapido

1. Sul Raspberry fai doppio clic su **Manuali RAG** sul desktop, oppure apri il browser su **http://127.0.0.1:8000**.
2. Se appare «Manuali locali», il RAG è già avviato: non avviarlo una seconda volta.
3. Per aggiungere un manuale, scegli il file in **Importa un manuale** e premi
   **Importa e indicizza**. Aspetta la conferma prima di fare domande sul nuovo documento.
4. Scrivi una domanda precisa e premi **Cerca nei manuali**.
5. Leggi la risposta testuale e controlla l’anteprima della pagina sotto le fonti. Usa **Apri la pagina** per ingrandirla. Nei documenti Markdown senza immagini la fonte resta testuale.

`127.0.0.1` indica la macchina su cui è aperto il browser: questo indirizzo va usato
**nel browser del Raspberry**, non in quello di un altro PC.

## 3. Se il RAG non è avviato

Apri un terminale sul Raspberry:

```bash
cd /home/michele/progetti/rag-manuali
make health
```

Se compare un risultato con `"status":"ok"`, il servizio risponde già. Il servizio automatico
si gestisce con questi comandi:

```bash
systemctl status manuali-rag ollama
sudo systemctl restart manuali-rag
journalctl -u manuali-rag -b --no-pager -n 50
```

Dopo aggiornamenti del codice riavvia `manuali-rag`. Per fermarlo usa
`sudo systemctl stop manuali-rag`; per disabilitare l'avvio automatico usa
`sudo systemctl disable manuali-rag`. Ollama e RAG ascoltano solo su `127.0.0.1`.
La configurazione limita entrambi alla slice `manuali-local.slice`, che blocca gli IP
esterni. I download di nuovi modelli richiedono una manutenzione con accesso alla rete,
non sono parte dell'uso offline ordinario.

Se scegli l'avvio manuale, prima ferma il servizio automatico e verifica la porta:

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

Le risposte riportano estratti del manuale. Il programma confronta i singoli passaggi con
la domanda usando i modelli locali; nei casi ambigui interviene il modello di selezione.
Mostra il testo originale e la relativa citazione `[S1]`, `[S2]`, ecc. Le fonti inutilizzate
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

Il primo collaudo QARA del 12 ottobre aveva rilevato che una domanda su un'informazione assente
poteva ricevere frasi non pertinenti invece di una mancata risposta. Aveva rilevato anche domande
che trovano la pagina corretta ma restano senza risposta, risposte con frasi superflue e
una risposta incompleta sulle alternative previste dalla configurazione.

Quando chiedi un valore, una credenziale, una condizione o un elenco di alternative,
controlla che la pagina contenga proprio quell'informazione: una citazione non basta.
Non interpretare un estratto su un altro argomento come la risposta alla tua domanda.
Se la risposta dipende da configurazione o permessi, verifica il contesto e tutte le
alternative nella pagina citata. Le correzioni successive selezionano passaggi più mirati,
mantengono il contesto delle liste configurabili e dei campi obbligatori, e richiedono un
riscontro esplicito per le richieste di credenziali iniziali. Il ricollaudo delle stesse domande
è riportato sotto; non certifica tutte le possibili domande o tutti i manuali futuri.

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

Per ripetere il collaudo QARA mantenendo domande e risposte private:

```bash
cd /home/michele/progetti/rag-manuali
make manual-eval CASES=data/evaluations/qara-cases.json MANUAL_EVAL_OUTPUT=data/evaluations/qara-corrected-2026-10-12.json
```

Il comando verifica fatti richiesti, pagine, citazioni, alternative e frasi superflue note;
termina con errore se un caso non supera i controlli. Richiede il manuale ancora indicizzato
e il file dei casi locale: questi dati non arrivano tramite GitHub. Il report completo resta
in `data/evaluations/` e non va pubblicato. I criteri vanno aggiornati quando cambi manuale
o aggiungi nuove prove; non modificare le aspettative solo per far passare una risposta errata.

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
- **12 ottobre 2026, correzioni:** passaggi separati dalle intestazioni, liste complete,
  selezione semantica locale e controllo delle richieste di credenziali iniziali;
  aggiunto il comando di collaudo privato ripetibile.

- **13 ottobre 2026:** avvio automatico locale con systemd, Ollama cloud disabilitato,
  isolamento di rete comune e verifica ripetibile dopo riavvio; aggiunti comandi di gestione
  del servizio e distinzione fra isolamento dei servizi e scollegamento fisico.

## 11. Collaudi e prossimi passi

- Il codice `df7469e` ha superato 37 test automatici, 11/11 casi sintetici end-to-end
  e 6/6 controlli HTTP di importazione, ricerca e domanda.
- **Primo collaudo reale QARA, 12 ottobre 2026, codice `820a925`:** 14 domande, di cui 12 su
  informazioni presenti e 2 su informazioni assenti. Dopo il controllo della pagina
  alternativa corretta, 11/12 domande positive contengono i fatti e le fonti attesi;
  1/2 domande negative viene rifiutata correttamente. Questi numeri non certificano
  la qualità completa: cinque risposte includono dettagli superflui e una è incompleta
  sulle alternative di configurazione. Il riepilogo dei controlli su fatti/fonti è 12/14,
  distinto dall'accuratezza complessiva delle risposte.
- Il report dettagliato e la revisione restano sul Raspberry in
  `data/evaluations/qara-expanded-2026-10-12.json`, fuori da Git. Domande, risposte ed
  estratti del manuale non vengono pubblicati nella guida.
- **Ricollaudo dopo le correzioni, codice `df7469e`: 14/14 casi superati.** Sono le stesse
  12 domande positive e 2 negative, con criteri più severi: fatti attesi, pagine, citazioni,
  assenza dei dettagli superflui noti e presenza delle alternative di configurazione.
  Entrambe le domande negative vengono rifiutate senza fonti estranee. Il nuovo report è
  `data/evaluations/qara-corrected-2026-10-12.json`; il report iniziale resta conservato.
  L'esito riguarda questi casi di prova, non tutte le possibili domande.
- **13 ottobre 2026, codice `389b236`:** servizi RAG e Ollama abilitati all'avvio;
  riavvio effettivo verificato e ripartenza automatica confermata. Entrambi usano
  `manuali-local.slice`, con connessioni esterne bloccate dal kernel, e ascolto locale.
  Ollama ha anche `OLLAMA_NO_CLOUD=true`. Dopo il riavvio: health e modelli disponibili,
  interfaccia HTTP, domanda QARA e pagina citata superati; 6/6 controlli di importazione
  e interrogazione HTTP in un indice temporaneo. `make check`: 37 test superati.
- **Prova pratica riferita dall'utente:** importazione del documento sintetico e risposta
  testuale con citazione riuscite senza rete. Le prime due domande QARA (accesso e
  visualizzazione dei dimessi) non sono state accettate per la risposta testuale mancante
  o inadeguata: la prova complessiva non va dichiarata superata.
- **Correzioni successive, codice `16d2b63`:** 42 test automatici, 16/16 casi QARA
  (inclusi i due segnalati), 11/11 casi sintetici e 6/6 controlli HTTP. Verificati via API
  e nel browser testo completo e immagini delle fonti per le due domande. Il browser
  di collaudo sul PC usa un tunnel SSH locale al servizio Raspberry; non è una nuova
  prova sul desktop del Raspberry con rete fisicamente scollegata.
  Report privato: `data/evaluations/qara-text-visual-2026-10-13.json`.
  Ripetuta anche la prova con rete esterna bloccata per i servizi.

Il collegamento **Manuali RAG** è installato sul desktop e nel menu applicazioni.
Il prossimo passaggio è ripetere le due domande QARA nel browser del Raspberry dopo
le correzioni e confermare testo e immagini anche senza rete. Ricaricare la pagina con
`Ctrl+Shift+R` per vedere l’interfaccia aggiornata.
Le alternative sono ampliare i manuali e le domande di prova oppure aggiungere selettore
dei manuali, gestione delle revisioni e accesso alla guida dall'interfaccia locale.


## 12. Verifica ripetibile dell'uso locale senza rete esterna

Esegui dal terminale del Raspberry:

```bash
cd /home/michele/progetti/rag-manuali
sudo systemd-run --wait --pipe --collect --unit=manuali-offline-check \
  --slice=manuali-local.slice -p User=michele \
  -p WorkingDirectory=/home/michele/progetti/rag-manuali \
  -p Environment=PYTHONIOENCODING=utf-8 \
  /home/michele/progetti/rag-manuali/.venv/bin/python \
  scripts/check_local_runtime.py --cases data/evaluations/qara-cases.json
```

Il controllo richiede il file privato dei casi già presente sul Raspberry. Verifica un
rifiuto esplicito del kernel a una connessione esterna, poi interfaccia HTTP, una domanda
su un manuale locale, pagina citata e importazione/interrogazione di un documento sintetico
in un indice temporaneo. L'indice dei manuali personali resta invariato. Questa prova
controlla le risorse usate dai servizi; non simula i clic in un browser grafico e non
scollega fisicamente il Raspberry dalla rete. Per quella verifica, apri il browser sul
Raspberry, scollega Wi-Fi/cavo e prova domanda e pagina; SSH sarà indisponibile.


## 13. Collegamento sul desktop e prova pratica senza rete

Sul desktop del Raspberry sono disponibili **Manuali RAG** e **prova-offline.md**.
Il collegamento apre la pagina locale con il browser predefinito; non avvia un secondo
server. Se il desktop chiede come aprire il file `.desktop`, scegli l'esecuzione.
Il collegamento è anche nel menu applicazioni. Per ricrearlo dalla copia del repository:

```bash
cd /home/michele/progetti/rag-manuali
desktop_dir=$(xdg-user-dir DESKTOP)
install -m 755 deploy/manuali-rag.desktop "$desktop_dir/Manuali RAG.desktop"
install -m 644 deploy/prova-offline.md "$desktop_dir/prova-offline.md"
gio set "$desktop_dir/Manuali RAG.desktop" metadata::trusted true
```

Esegui la prova davanti al Raspberry:

1. Scollega Ethernet se presente e disattiva il Wi-Fi dal desktop.
2. Apri **Manuali RAG**. Fai una domanda QARA già collaudata e apri la pagina citata.
3. Importa **prova-offline.md** dal desktop con **Importa e indicizza**.
4. Chiedi «Che cosa indica OFFLINE-42?». La risposta attesa dice che la prova locale
   è riuscita e cita il documento sintetico.
5. Riattiva la rete e annota l'esito. Se l'IP cambia, comunicalo nella chat successiva.

L'importazione aggiunge un documento sintetico all'indice principale, senza modificare
QARA; ripetere lo stesso file non lo duplica. Non è disponibile la rimozione dall'interfaccia.
Questa prova pratica va dichiarata superata solo dopo conferma dei passaggi; la precedente
prova automatica con isolamento dei servizi resta un controllo distinto.


### Esito della prova e ricollaudo

L'utente ha confermato che l'importazione di `prova-offline.md`, la risposta e la citazione
funzionano offline. Le prime risposte QARA non soddisfacevano il requisito di testo utile
insieme alle pagine: sono state corrette e aggiunte al collaudo privato.
L'interfaccia ora mostra il testo sopra le fonti e, per le pagine PDF disponibili,
l'anteprima direttamente nella stessa schermata. Il placeholder è coerente con i software
sanitari. Dopo `Ctrl+Shift+R`, ripetere le due domande e controllare sia il testo sia l'immagine;
L'utente ha poi confermato correttezza del testo e dell'immagine per i pazienti dimessi.
La variante «come faccio il login?» ha ancora fallito, confondendo accesso e firma;
dopo la correzione successiva l’utente ha confermato anche quella variante.


### Varianti colloquiali del login

La correzione `2e70848` tratta in modo coerente le forme dei verbi di supporto
(«fare», «faccio», «devo», «effettuo», ecc.) nella ricerca delle procedure.
Sul Raspberry, otto formulazioni dell'accesso, inclusa quella segnalata dall'utente,
restituiscono testo, citazione e pagina corretti, senza passaggi sulla firma.
Sono stati aggiunti test per mantenere distinte le domande sulla firma e sull'accesso.
`make check`: 51 test superati. Collaudo QARA ampliato: **23/23**, regressione sintetica **11/11**; report privato
`data/evaluations/qara-login-variants-2026-10-13.json`. Le nuove formulazioni sono conservate nel file privato
dei casi, insieme alle prove precedenti. L’utente ha confermato la risposta corretta a
entrambe le formulazioni del login, verificando anche testo e immagine senza Wi-Fi.
Questi controlli non garantiscono la correttezza su ogni possibile domanda.


## 14. Collaudo di domande spontanee — 13 ottobre 2026

Il collaudo è stato ampliato con **24 nuove domande**, distinte dai precedenti 23 casi:
20 su informazioni presenti, 2 su informazioni assenti e 2 senza un argomento chiaro.
Coprono accesso, liste pazienti, Support Data, problemi attivi, dati anagrafici, attività,
diario e filtri. Criteri definiti dopo lettura delle pagine del manuale; interrogazioni al
servizio reale con `include_images=true`, controllo del testo, pagine, citazioni e risposta
HTTP delle immagini. Non sono nuovi collaudi fisici con Wi-Fi scollegato; i servizi
continuano a usare la slice con accesso esterno bloccato.

**Esito rivisto: 8/24 superati.** Il report iniziale era 7/24; dopo lettura della pagina
alternativa 162 e ripetizione del singolo caso, la risposta sulla chiusura dei Support Data
è stata accettata come corretta. Il report iniziale resta conservato.

| Categoria | Superati | Totale |
| --- | ---: | ---: |
| Informazione presente | 6 | 20 |
| Informazione assente | 2 | 2 |
| Richiesta ambigua | 0 | 2 |

Fra le risposte positive non superate, 12 recuperano una sezione non pertinente o non
forniscono i fatti richiesti; 2 dichiarano di non avere informazioni che sono invece nel
manuale. Le due richieste ambigue ricevono istruzioni specifiche senza aver chiarito
l'argomento. Un'immagine disponibile e una citazione formalmente corretta non certificano
che la risposta affronti la domanda. I precedenti 23/23 casi mirati restano un risultato
storico, non una misura della robustezza alle nuove parafrasi.

Codice di collaudo: `7690ed7`; risposte applicative invariate rispetto a `2e70848`.
Lint e 51 test superati sul Raspberry; servizio sano, indice invariato (QARA più file
sintetico). Domande, risposte e criteri restano in `data/evaluations/`, esclusi da Git.

File privati:

- `qara-spontaneous-cases-2026-10-13.json`: nuovi casi con criteri rivisti.
- `qara-spontaneous-2026-10-13.json`: report iniziale.
- `qara-spontaneous-review-case-report.json`: ripetizione del caso con pagina alternativa.
- `qara-spontaneous-reviewed-2026-10-13.json`: riepilogo rivisto, con riferimenti ai report.

Per ripetere l'intero collaudo, senza sovrascrivere questi risultati:

```bash
cd /home/michele/progetti/rag-manuali
PYTHONIOENCODING=utf-8 .venv/bin/python scripts/evaluate_manual_cases.py \
  --cases data/evaluations/qara-spontaneous-cases-2026-10-13.json \
  --output data/evaluations/qara-spontaneous-next.json \
  --api-url http://127.0.0.1:8000
```

I limiti di questo giro sono stati affrontati nel passaggio successivo, documentato
nella sezione 15. Questo esito resta conservato come riferimento storico.


## 15. Recupero dei passaggi e richieste ambigue

La ricerca conserva il soggetto e l'operazione della domanda, confronta i passaggi
con titoli e didascalie reali e mantiene insieme condizioni, campi obbligatori e
alternative necessarie. Le risposte usano testo del manuale con citazioni e pagine
visualizzabili. Una richiesta senza soggetto, come un generico invito ad aprire
qualcosa, riceve una domanda di chiarimento: specificare la funzione o schermata.
Se l'informazione manca, il sistema deve dichiararlo senza inventare istruzioni.

Il modello di risposta resta `llama3.2:3b`, eseguito da Ollama sul Raspberry.
Anche gli embedding e la cache dei passaggi restano locali. Il primo uso dopo
una modifica può essere più lento mentre si completa la cache. Non bisogna
ricaricare i manuali per ogni domanda. I vettori dell'indice sono stati aggiornati
con i prefissi richiesti da Nomic, conservando documenti e pagine e creando un
backup SQLite locale; per la manutenzione consultare `reembed` nel README.

I casi precedenti e spontanei sono riuniti in un collaudo privato di 47 domande.
Per ripeterlo sul servizio in esecuzione, conservando i risultati precedenti:

```bash
cd /home/michele/progetti/rag-manuali
PYTHONIOENCODING=utf-8 .venv/bin/python scripts/evaluate_manual_cases.py \
  --cases data/evaluations/qara-all-cases-2026-10-13.json \
  --output data/evaluations/qara-all-next.json \
  --api-url http://127.0.0.1:8000
```

Il controllo include fatti richiesti, dettagli da escludere, pagine, citazioni,
immagini disponibili e chiarimenti senza fonti per le richieste ambigue. I file
con domande, criteri e risposte rimangono sul Raspberry, esclusi da GitHub.


### Esito verificato sul codice `ff00bfc`

**47/47 superati via API sul Raspberry:** 41 domande con informazioni presenti,
4 su informazioni assenti e 2 richieste ambigue. Nei 41 casi positivi sono passati
anche i controlli di citazione, pagina e immagine. Report privato:
`data/evaluations/qara-all-verified-2026-10-13.json`.
Sono passati anche lint e 62 test, regressione sintetica 11/11 e controlli HTTP 6/6.
Nella slice locale il kernel blocca l'accesso esterno e funzionano interfaccia,
domanda QARA e immagine; `make health` e `make ollama-check` sono passati.
Questa verifica non è una nuova disconnessione fisica del Wi-Fi o un nuovo riavvio.

I giri intermedi non superati restano conservati: il risultato finale riguarda
questi 47 casi e non garantisce la correttezza di qualunque futura domanda.

Prossimo passo consigliato: fare una prova personale dal browser del Raspberry,
con Wi-Fi disattivato, usando altre domande spontanee e controllando testo e pagina.
Per aggiornare l'interfaccia usare `Ctrl+Shift+R`. In alternativa si può collaudare
un secondo manuale o aggiungere un selettore del manuale prima della domanda.


## 16. Prova pratica: autore, modifica e applicazione dei filtri

La prova personale del 15 ottobre ha mostrato due risposte non pertinenti su
formulazioni non presenti nei 47 casi iniziali. Una pagina corretta non basta:
il testo deve rispondere all'operazione e ai vincoli richiesti.

Quando chiedi di correggere una nota, specifica se è già salvata oppure se stai
ancora scrivendo. Modifica di un contenuto salvato e annullamento prima del
salvataggio richiedono procedure diverse; il RAG deve chiedere un chiarimento
quando non può distinguerle. Per una modifica salvata verifica apertura, comando
di modifica e salvataggio. Per le proprie note deve conservare il vincolo sull'autore;
per i filtri deve riportare anche l'eventuale conferma richiesta dal manuale.

I nuovi criteri sono locali e privati. Per ripetere tutti i casi, ora 51:

```bash
cd /home/michele/progetti/rag-manuali
PYTHONIOENCODING=utf-8 .venv/bin/python scripts/evaluate_manual_cases.py \
  --cases data/evaluations/qara-all-cases-2026-10-15.json \
  --output data/evaluations/qara-all-workflows-next.json \
  --api-url http://127.0.0.1:8000
```

La sola prova pratica ampliata usa invece
`data/evaluations/qara-practical-cases-2026-10-15.json`.


Sul codice `e555e6c`, **67 test** e collaudo complessivo **51/51** superati sul
Raspberry. I cinque casi pratici mirati erano già passati sul codice `ea0a689`;
il giro completo include anche il successivo riordino delle anteprime.
Report privato: `data/evaluations/qara-all-workflows-2026-10-15.json`.
La successiva verifica personale del 15 ottobre è confermata dall'utente:
nota salvata e proprie note con risposte accettabili e immagini corrette;
ripristino filtri con risposta e immagini corrette. Nella risposta sulla nota
salvata rimangono frasi superflue, pur con procedimento corretto nella parte finale.
I risultati valgono per i casi provati, non per ogni possibile formulazione.

Anche regressione sintetica **11/11**, controlli HTTP **6/6** e controlli di salute
sono passati. La prova nella slice locale ha verificato il blocco della rete esterna
e il funzionamento di interfaccia, procedura della nota salvata e immagine citata.
Per la prova personale aggiorna il browser con `Ctrl+Shift+R`, disattiva il Wi-Fi e
ripeti i casi pratici. Successivamente si può collaudare un secondo manuale oppure
aggiungere un selettore dei manuali.
