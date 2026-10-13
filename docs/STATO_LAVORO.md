# Punto di ripresa — 13 ottobre 2026

## Obiettivo finale

Usare il RAG direttamente dal Raspberry, scrivendo domande e leggendo risposte nel
browser locale anche senza Internet. Manuali, indice e modelli devono restare locali.
Il promemoria operativo aggiornabile è [GUIDA_USO.md](GUIDA_USO.md).

## Stato completato e verificato

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

La prova fisica delle risposte QARA corrette sul desktop del Raspberry **resta da confermare**.
Ricaricare il browser con `Ctrl+Shift+R` e ripetere le due domande, anche senza rete.

## Prossimo passo e opzioni

1. **Consigliato:** ripetere e registrare la prova delle risposte QARA corrette nel browser del Raspberry
   con rete fisicamente scollegata:
   domanda, apertura della pagina e importazione di un file locale. Lo scollegamento
   interrompe SSH, quindi quella parte richiede l'utente davanti al Raspberry.
2. Ampliare il collaudo con altri manuali e domande.
3. Migliorare l'interfaccia con selettore dei manuali, gestione delle revisioni o guida locale.

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
