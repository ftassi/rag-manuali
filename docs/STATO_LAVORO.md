# Punto di ripresa — 12 ottobre 2026

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

## Avvio attuale

Ollama è attivo e abilitato all'avvio, con `llama3.2:3b` e
`nomic-embed-text-v2-moe` già disponibili. Gli endpoint sono locali.
Il RAG è stato riavviato con il codice aggiornato ed è attivo sulla porta 8000,
avviato manualmente in background; il log è `/tmp/manuali-rag-qara.log`.
Al momento della verifica l'unità `manuali-rag.service` non è installata.
Il processo attuale ascolta su `0.0.0.0`; nel browser del Raspberry si usa
`http://127.0.0.1:8000`.

**Restano da verificare il riavvio automatico e l'uso con rete scollegata.**

## Prossimo passo e opzioni

1. **Consigliato:** configurare l'avvio automatico del RAG su `127.0.0.1`, usando
   utente e percorso corretti. Verificare e fermare il processo manuale prima di
   avviare il servizio, evitando duplicati. Poi collaudare dopo un riavvio, senza rete:
   interfaccia, domanda, apertura della pagina citata e importazione di un file locale.
   Coordinare riavvio e scollegamento con l'utente, perché interrompono SSH.
2. Mantenere l'avvio manuale e provare l'uso offline dal desktop del Raspberry.
3. Ampliare prima i casi e i manuali di prova; successivamente aggiungere selettore
   dei manuali, gestione delle revisioni o accesso alla guida nell'interfaccia.

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
