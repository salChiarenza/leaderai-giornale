# LeaderAI Giornale

Le notizie che ti interessano, ogni mattina in una pagina. Un giornale personale in italiano, con titoli, foto ufficiale quando disponibile e fonti cliccabili. Lo leggi a video; se vuoi puoi stamparlo.

La skill è gratuita. Usa Claude Code o Codex già collegato al tuo piano: la generazione consuma i limiti del piano, senza nuove chiavi API. Richiede Python 3.10 o successivo e una connessione internet.

## Per te, una riga

> Installa la skill gratuita da https://github.com/salChiarenza/leaderai-giornale, proponimi interessi e fonti dalle preferenze pertinenti che conosci già, chiedimi solo ciò che manca e prepara il mio primo giornale PDF da leggere a video. Poi aiutami a riceverlo ogni giorno.

[Scarica lo ZIP](https://github.com/salChiarenza/leaderai-giornale/archive/refs/heads/main.zip) · [Guarda una prova con immagine](examples/giornale-esempio-2026-10-29.pdf)

## Istruzioni per la tua AI

Leggi [SKILL.md](SKILL.md). Non occorre LeaderAI Ecosistema e non servono file della casa di Sal. Le fonti, gli interessi e i giornali personali restano nella cartella scelta dalla persona, fuori dalla repository. Vengono inviati al fornitore AI selezionato per preparare il numero, non a LeaderAI. Il runner non apre email o connettori privati.

### Installazione

Scarica lo ZIP, estrailo e apri la cartella con la tua AI. Prima verifica:

```bash
python3 scripts/giornale.py doctor
```

Installa per il motore usato, oppure per entrambi:

```bash
python3 scripts/giornale.py install --engine codex
python3 scripts/giornale.py install --engine claude
python3 scripts/giornale.py install --engine both
```

Codex carica `~/.agents/skills/leaderai-giornale`; Claude Code carica `~/.claude/skills/leaderai-giornale`. Per installare solo in un progetto usa `--scope project --project "PERCORSO PROGETTO"`. La stessa skill viene copiata nei loader scelti. Apri una nuova sessione se non compare subito.

La seconda installazione è idempotente. Un aggiornamento si ferma se trova file modificati dalla persona, prima di sovrascriverli. Non crea una configurazione personale o una routine.

### Configurazione e primo numero

Scegli una cartella dati privata esterna alla repo, per esempio `~/Documents/Il mio giornale`. `bootstrap` crea lì una `.venv`, senza installare pacchetti globali:

```bash
python3 scripts/giornale.py bootstrap --data-dir "PERCORSO DATI"
```

Per i prossimi comandi usa `scripts/giornale.py` dalla cartella skill INSTALLATA, non dalla copia ZIP che potresti eliminare. Usa il Python restituito dal comando. Su macOS/Linux è `PERCORSO DATI/.venv/bin/python`; su Windows `PERCORSO DATI/.venv/Scripts/python.exe`. Sostituisci `PYTHON_VENV` e gli altri percorsi negli esempi; la tua AI deve eseguire il comando adatto al sistema.

```bash
PYTHON_VENV scripts/giornale.py init --data-dir "PERCORSO DATI" --engine codex --interest "ARGOMENTO CONFERMATO" --source "https://FONTE-UFFICIALE.example/notizie"
PYTHON_VENV scripts/giornale.py run --data-dir "PERCORSO DATI"
```

La fonte sopra è un segnaposto da sostituire. Ripeti `--interest` e `--source` per più voci. Se la CLI non è nel PATH, indica `--binary "PERCORSO ASSOLUTO CLI"`. `--profile "FILE APPROVATO"` è facoltativo: solo un estratto pertinente di massimo 16 KB. Il profilo può mancare.

Il fuso predefinito è `Europe/Rome`, l'ora `06:00`: cambiali con `--timezone` e `--at`. Per modifiche successive chiedi alla tua AI di leggere e aggiornare il tuo `config.json`, mantenendo i dati già confermati.

Trovi PDF, notizie JSON e ricevuta in `PERCORSO DATI/editions/AAAA-MM-GG/`. Una ricerca usa una sola chiamata alla CLI. Non ripete una giornata già tentata: prima controlla `status`, poi eventualmente `run --force`. Dopo un solo errore di impaginazione o immagine puoi usare `run --resume-render`: completa il PDF dalla ricerca già salvata, senza richiamare il modello. Il lock impedisce due generazioni contemporanee. Una interruzione forzata può lasciare il lock: verificare che il processo sia terminato prima di rimuoverlo.

```bash
PYTHON_VENV scripts/giornale.py status --data-dir "PERCORSO DATI"
PYTHON_VENV scripts/giornale.py schedule --plan --data-dir "PERCORSO DATI"
```

### Nota breve, audit completo e ricerca parziale

Il JSON separa `note` (massimo 220 caratteri per la pagina) da `audit` (provenienza, esclusioni ed errori completi). `coverage` dichiara `complete`, `partial` o `blocked`. Una fonte pertinente che risponde HTTP 403 rende la lettura parziale: il PDF lo mostra e la ricevuta resta `partial`. Una ricerca bloccata fallisce con un motivo; soltanto una ricerca completa può dichiarare `no_updates`.

Se una ricerca già pagata ha una nota troppo lunga, la tua AI legge la nota intera e prepara un riassunto fedele dei limiti essenziali. Non taglia la nota e non ripete la ricerca. Usa `recover-note` per creare un JSON derivato nuovo, conservando nell’audit nota originale integrale, provenienza e hash. Il file originale non viene sovrascritto.

```bash
PYTHON_VENV scripts/giornale.py recover-note --input "JSON ORIGINALE" --output "PERCORSO DATI/editions/AAAA-MM-GG/edition.json" --coverage partial --note "NOTA BREVE FEDELE AI LIMITI, MASSIMO 220 CARATTERI"
PYTHON_VENV scripts/giornale.py run --resume-render --data-dir "PERCORSO DATI"
```

Il recupero è una revisione dichiarata dei metadati, senza nuove fonti: gli articoli e la finestra restano quelli originali. `--resume-render` richiede una ricevuta fallita nella giornata e un `edition.json` valido. Per consultare dettagli e limiti completi apri lo stesso JSON indicato da `audit_file` nella ricevuta.

### Routine quotidiana e stop

`schedule --plan` non attiva nulla: restituisce un comando con percorsi assoluti e il prompt per l'automazione nativa dell'app. La tua AI attiva una sola routine giornaliera dopo il primo numero controllato. Su scheduler del sistema deve conservare identificativo e istruzioni di rimozione nella cartella dati. Il computer deve essere disponibile, con rete e login valido; una macchina spenta non stampa né genera PDF.

Per fermarla, metti in pausa la stessa automazione nell'app che l'ha creata. Il runner non installa scheduler nascosti.

### Stampa facoltativa

Su macOS/Linux, con una stampante CUPS già configurata e dopo aver visto il PDF:

```bash
PYTHON_VENV scripts/giornale.py print --data-dir "PERCORSO DATI" --pdf "PERCORSO DATI/editions/AAAA-MM-GG/LeaderAI-AAAA-MM-GG.pdf" --confirm
```

Invia una copia A4 alla stampante predefinita. `queued` significa accettata dalla coda: il foglio uscito va verificato dalla persona. La ricevuta impedisce reinvii sullo stesso PDF; dopo un esito dubbio controllare la coda. `run` non stampa e la stampa è disattivata per impostazione iniziale. Su Windows apri il PDF e stampa dall'app: invio diretto non supportato.

### Notizie e grafica

La ricerca parte dalle ultime 48 ore e dalle fonti confermate. Se serve, può estendersi fino a sette giorni e lo dichiara. Se non trova almeno quattro notizie vere, produce una pagina che lo spiega. Non sostituisce aggiornamenti assenti con notizie inventate. Il programma controlla forma del JSON, date, duplicati e dimensione del testo; l'accuratezza fattuale dipende anche dalla ricerca del modello e va verificata alla fonte prima di decidere.

Il PDF è una pagina A4 color crema, con testata LeaderAI e corpo di almeno 9 punti. Si può ingrandire a video. I font PDF standard non richiedono font del sistema. Se il testo non entra, il rendering si ferma; non taglia articoli di nascosto. Una foto è facoltativa, deve provenire dalla fonte ufficiale ed essere accreditata. URL privati, file locali, SVG e immagini oltre i limiti vengono rifiutati. Le immagini dei terzi mantengono i rispettivi diritti.

L’esempio con immagine è datato 29/10/2026 e riporta notizie del giorno precedente: mostra la grafica, non è un giornale aggiornato. Lo screenshot appartiene a GitHub, è accreditato nel PDF e proviene dalla fonte collegata nel JSON. Il file `edition-demo.json` contiene invece testi inventati e dichiarati.

Per provare la grafica senza una ricerca:

```bash
PYTHON_VENV scripts/giornale.py render examples/edition-demo.json --demo --output "PERCORSO DATI/prova.pdf"
```

### Compatibilità e aggiornamenti

Nucleo Python e percorsi progettati per macOS, Linux e Windows. Prova end-to-end eseguita su macOS con Codex; Claude Code e Windows richiedono il collaudo sul sistema destinatario. Non è una attestazione di compatibilità Windows. Claude usa `-p` e output strutturato con soli WebSearch/WebFetch autorizzati per quella chiamata, senza modificare permessi globali, e senza modalità bare che esclude le credenziali del piano. Se il login o un permesso bloccano la ricerca, il runner mostra l'errore e conserva la ricevuta.

Per aggiornare scarica la stessa repo e ripeti `install`. I tuoi dati non vengono spostati. Se il percorso della CLI cambia dopo un aggiornamento, la tua AI aggiorna `binary` nella configurazione dopo `doctor`. Per disinstallare rimuovi solo la cartella `leaderai-giornale` dai loader scelti, dopo aver fermato la routine. I giornali restano nella tua cartella finché decidi di eliminarli.

### Verifica del pacchetto

`release-manifest.json` elenca i soli file distribuibili. Le cartelle locali, configurazioni, log, giornali personali e venv non entrano nel manifest. Prima di una release:

```bash
python3 scripts/giornale.py release-check
PYTHON_VENV -m pip install pypdf
PYTHON_VENV -m unittest discover -s tests -v
```

[Codex: skill](https://learn.chatgpt.com/docs/build-skills) · [Codex: CLI](https://learn.chatgpt.com/docs/developer-commands) · [Claude: skill](https://code.claude.com/docs/en/skills) · [Claude: esecuzione programmata](https://code.claude.com/docs/en/headless) · [CUPS: stampa](https://www.cups.org/doc/options.html)

Codice sotto [licenza MIT](LICENSE). Nome, logo e marchio LeaderAI restano dei rispettivi titolari: la licenza del codice non concede diritti sul marchio né diritti sulle immagini dei terzi. Una derivazione deve presentarsi con il proprio nome senza suggerire approvazione di LeaderAI.
