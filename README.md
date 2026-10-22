# Nova Alarm per Home Assistant — 0.4.0

Prima versione sperimentale di una **custom integration** per il cloud AVS.
Si configura da Impostazioni → Dispositivi e servizi. Non è un add-on da
installare nello store del Supervisor e non richiede un servizio Docker.

Integrazione non ufficiale con l’allarme **Nova**, tramite il backend AVS e
l’account dell’app Mio Antifurto già verificati nella prova iniziale. Il nome
Nova identifica questo progetto; non implica compatibilità già provata con
tutti i modelli Nova. Il protocollo locale EWeb rimane fuori da questa versione.

## Installazione con HACS

Il repository deve essere pubblico per poter essere scaricato da HACS.

1. In HACS apri il menu e scegli **Repository personalizzati**.
2. Aggiungi `https://github.com/epgdev/HA-nova-alarm`, categoria
   **Integrazione**.
3. Cerca **Nova Alarm**, scarica l’integrazione e riavvia Home Assistant.
4. Aggiungi **Nova Alarm** da Impostazioni → Dispositivi e servizi.

La pubblicazione del repository non lo inserisce automaticamente nel catalogo
predefinito di HACS. Il progetto usa il dominio `nova_alarm`; la vecchia bozza
con dominio `mio_antifurto` deve essere rimossa se era stata installata.

## Cosa include

- Accesso con username, password e PIN dell'app Mio Antifurto.
- Scelta dell'impianto associato all'account.
- Un `alarm_control_panel` per settore, con inserimento e disinserimento protetti da PIN.
- Comandi ON, HO, AR, PE, OFF con controlli sulle zone e permessi restituiti dalla centrale.
- Un sensore con la modalità originale AVS: ON, HO, AR, PE, OFF.
- Modalità di inserimento visibili configurabili (per esempio solo ON).
- Interruttori normali per escludere e reincludere ogni zona.
- Sensori binari per apertura, manomissione, batteria scarica,
  guasto, antimascheramento e memoria allarme di ciascuna zona.
- Nomi delle zone e dei settori recuperati dal cloud, se disponibili.
- Aggiornamento coordinato ogni **60 secondi**, modificabile da 30 a 600.
- Sessioni brevi condivise fra le entità durante ogni operazione, richieste serializzate, un solo tentativo
  di rinnovo per aggiornamento quando la sessione scade.
- Nuova richiesta delle credenziali se l'autenticazione viene rifiutata.
- Traduzioni italiane e inglesi; identificativi stabili delle entità.

Per limitare l'affollamento, apertura e manomissione sono abilitate per default.
Gli altri sensori diagnostici possono essere abilitati nella pagina delle entità.
Il bit AVS `attiva` non viene esposto come entità autonoma; viene controllato
prima di modificare un’esclusione, come nell’app ufficiale.

## Installazione manuale

1. Estrai lo ZIP su un dispositivo personale.
2. Copia la cartella `custom_components/nova_alarm` nella cartella
   `custom_components` della configurazione di Home Assistant. Il risultato
   deve essere `/config/custom_components/nova_alarm/manifest.json`.
3. Riavvia Home Assistant.
4. Apri **Impostazioni → Dispositivi e servizi → Aggiungi integrazione**.
5. Cerca **Nova Alarm**, inserisci username/password, poi seleziona
   l'impianto e inserisci il PIN della centrale. Gli zeri iniziali del PIN
   vengono conservati.

L’integrazione include l’icona verde Mio Antifurto nella cartella `brand/`.
Home Assistant 2026.3 o successivo la carica localmente; dopo l’aggiornamento
riavvia Home Assistant e, se necessario, ricarica la pagina per aggiornare l’icona.

Non aggiungere righe a `configuration.yaml`. Il repository è predisposto per essere aggiunto a HACS come repository
personalizzato di tipo Integrazione.

### Riutilizzare il dispositivo della prova Python

Il cloud può conteggiare l'integrazione come un nuovo dispositivo. Se hai già
eseguito `mioantifurto_probe.py`, puoi riutilizzarne l'ID anziché crearne un altro.
Nel medesimo terminale e utente in cui avevi eseguito la prova:

```bash
cat ~/.config/mioantifurto-probe/device_id
```

Copia il valore nel campo facoltativo **ID dispositivo esistente** del primo
passaggio di configurazione. Se lo lasci vuoto, viene generato un ID casuale
che sarà conservato nei successivi riavvii e rinnovi della sessione.
Non eseguire contemporaneamente la prova e l'integrazione usando lo stesso ID.
In caso di limite dispositivi, gestisci i dispositivi dall'app ufficiale:
l'integrazione non sostituisce dispositivi né accetta consensi automaticamente.

## Interpretazione degli stati

Il campo `type` del settore contiene più bit: `type & 15` identifica la modalità.
I campi `on`, `ho`, `ar`, `pe`, `off` della risposta sono permessi/modalità
comandabili e non vanno interpretati come cinque stati contemporaneamente attivi.

| Codice AVS | Modalità | Stato HA predefinito |
| --- | --- | --- |
| 0 | ON | Inserito fuori casa |
| 1 | HO | Inserito in casa |
| 2 | AR | Inserito personalizzato |
| 3 | PE | Inserito notte |
| 4 | OFF | Disinserito |

La corrispondenza tra ON/HO/AR/PE e le modalità di Home Assistant è una
**convenzione iniziale configurabile nelle opzioni**: le modalità possono
essere personalizzate nell'impianto. Il sensore modalità AVS e l'attributo
`avs_mode` conservano sempre il valore originale.
Valori diversi da 0–4 e dati non validi producono stato sconosciuto.

Per le zone i bit della risposta `flags` sono quelli decodificati dall'app:

| Bit | Significato |
| --- | --- |
| 0 | Aperta |
| 1 | Manomissione |
| 2 | Esclusa |
| 4 | Batteria scarica |
| 5 | Guasto |
| 6 | Antimascheramento |
| 7 | Memoria allarme |

Una memoria allarme **non viene trasformata in allarme attualmente scattato**.
Questa versione non ricostruisce ancora ingresso ritardato, uscita ritardata,
sirena attiva o stato `triggered`. I dati mancanti non diventano falsi/chiusi:
la relativa zona è indisponibile. Se un aggiornamento fallisce, le entità
diventano indisponibili anziché mantenere uno stato apparentemente attuale.

## Limiti e verifiche ancora necessarie

Il primo script di prova ha verificato su un impianto AVS FENICE 8/EWeb (backend AVS):
login, accesso con PIN, lettura di un settore e sei zone, OFF con
`type=16777236`, contatto aperto con `flags=1`, logout.
Il passaggio fisico aperta → chiusa e l'inserimento reale delle diverse modalità
non sono ancora stati verificati sul campo.

Questa integrazione usa le API cloud ricostruite dall'APK. Non usa l'indirizzo
locale EWeb e dipende da Internet e dal servizio AVS. Non è un prodotto ufficiale
di AVS e il protocollo può cambiare. I nomi tramite `/avs/get_desc`, il rinnovo
automatico e l'uso continuativo del polling devono ancora essere verificati
su questo impianto. Se i nomi non sono disponibili vengono usati nomi generici;
si possono rinominare le entità dall'interfaccia di Home Assistant.

## Comandi da Home Assistant

Dalla versione **0.2.0** il pannello del settore espone inserimento e
disinserimento. Per default inserisci il **PIN della centrale già configurato
nell’integrazione** per ogni operazione, anche nelle chiamate ai servizi HA.
Dalla 0.3.3 puoi disattivare questa richiesta locale nelle opzioni (vedi sotto).
Conserva gli zeri iniziali: nelle automazioni il codice deve essere una stringa,
ad esempio `code: "01234"` (esempio fittizio).

La corrispondenza nelle opzioni ora determina **sia gli stati sia i comandi**:
per default Fuori casa → ON, In casa → HO, Personalizzato → AR, Notte → PE;
Disinserisci invia OFF. Verifica nell’app ufficiale quali zone sono associate
alle modalità del tuo impianto. Ogni modalità AVS selezionata deve avere uno stato HA
distinto; vecchie corrispondenze duplicate fra modalità visibili rendono il relativo comando ambiguo
e quindi indisponibile finché non vengono corrette nelle opzioni.

I pulsanti di inserimento compaiono solo per le modalità esplicitamente
consentite dalla risposta AVS (`on`, `ho`, `ar`, `pe` uguale a 1). Il client
rilegge i permessi prima di ogni comando e controlla anche `off` per il
disinserimento. Permessi mancanti non vengono interpretati come consenso.
Il settore aggregato con ID 0 non è comandabile in questa versione.

Il comando mantiene `check=1` e `checkzone=1`, come il comando singolo dell’app:
**non forza inserimenti, non esclude zone e non ritenta disabilitando i controlli**.
Se la centrale rifiuta l’operazione, controlla zone aperte e anomalie nell’app
ufficiale. Dopo la richiesta viene riletto lo stato effettivo, senza mostrare
ottimisticamente la modalità richiesta. Durante eventuali ritardi della
centrale può rimanere lo stato precedente fino al polling successivo.

Un timeout o una risposta non valida non provocano il reinvio del comando:
l’esito può essere incerto. Controlla lo stato nell’app prima di riprovare.
I comandi sono stati ricostruiti dall’APK e verificati con risposte simulate;
**il collaudo su un impianto reale resta da effettuare**.

### Mostrare solo ON

Apri **Impostazioni → Dispositivi e servizi → Nova Alarm → Configura**
(o Opzioni) e in **Modalità di inserimento visibili** lascia selezionato solo
**ON**. Salva: rimarranno il comando di inserimento associato a ON (di default
Fuori casa) e Disinserisci. Puoi anche nascondere tutti gli inserimenti lasciando
vuota la selezione. Le modalità nascoste non sono comandabili tramite i servizi
HA, ma lo stato effettivo continua a essere mostrato anche se l’impianto viene
inserito in un’altra modalità dall’app. L’opzione non cambia la programmazione
della centrale e si applica a tutti i settori dell’integrazione.

### Escludere una zona prima di inserire l’allarme

Dalla **0.3.0** ogni zona ha un interruttore **«Nome zona esclusione»**, abilitato
per default fra i controlli normali del dispositivo, senza categoria diagnostica:

- **Acceso = zona esclusa** dalla protezione.
- **Spento = zona inclusa** nella protezione.

A impianto disinserito, attiva l’esclusione delle zone desiderate e attendi che
lo stato sia confermato. Poi inserisci l’allarme dal pannello usando il PIN.
Escludere una zona non inserisce l’allarme e inserire l’allarme non modifica
automaticamente le esclusioni. Dopo l’uso disinserisci e reincludi le zone
quando opportuno: il comportamento e la durata dell’esclusione dipendono
dalla centrale, non viene programmata una reinclusione automatica da HA.

Gli interruttori usano la sessione già autenticata con il PIN configurato;
non chiedono un secondo PIN a ogni cambio. Se la zona è attiva (bit AVS 3),
ha dati mancanti o la centrale rifiuta il comando, l’operazione viene bloccata.
Il client ricontrolla lo stato prima di scrivere e non ritenta le scritture.
Uno stato richiesto non ancora confermato viene segnalato, senza aggiornamento
ottimistico. Le esclusioni sono disponibili anche tramite `switch.turn_on`
e `switch.turn_off` per plance e automazioni.

Il vecchio sensore binario di esclusione rimane per compatibilità con le
relative automazioni, è facoltativo e non è più diagnostico; per modificare
l’esclusione usa il nuovo interruttore. Non sono stati eseguiti comandi reali
sull’impianto durante lo sviluppo.

### Aggiornare dalla 0.1.0 o 0.2.0

Aggiorna tutti i file di `custom_components/nova_alarm` con quelli della 0.3.0
e riavvia Home Assistant. La configurazione esistente viene conservata.
Se usi HACS, l’aggiornamento sarà scaricabile solo dopo la pubblicazione della
nuova versione nel repository; fino ad allora puoi copiare manualmente la
cartella. Apri le opzioni dell’integrazione e verifica la corrispondenza delle
modalità prima di usare i comandi. Se mancano pulsanti, controlla i permessi
concessi al tuo utente nell’app ufficiale.

Non sono implementati forzatura o comandi globali.

Le credenziali e il PIN sono conservati nella configurazione dell'integrazione
gestita da Home Assistant. Il client non li scrive nei log, negli attributi
delle entità o nei messaggi di errore. I token rimangono solo in memoria.

## Sviluppo e verifica

Ambiente di prova: Home Assistant **2026.10.2**, Python **3.14.8**. Il terminale
dell'add-on e Home Assistant Core sono ambienti distinti: controllare la versione
Core nella pagina delle informazioni di sistema. Altre versioni non sono state
collaudate. È presente un fallback per gli schemi `voluptuous` delle versioni
precedenti, che non equivale a una garanzia di compatibilità.

Per eseguire i test in un ambiente virtuale Python 3.14:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q
.venv/bin/ruff check .
```

I test usano risposte simulate; non si collegano ad account AVS. Coprono il
protocollo, la conservazione degli zeri nel PIN, il rinnovo limitato delle
sessioni, errori, dati mancanti, stati HA e configurazione da interfaccia.
Esito iniziale della 0.1.0: **18 test superati** su Home Assistant 2026.10.2/Python 3.14.8;
controlli Ruff e formattazione superati. Il test di ciclo completo carica
le piattaforme reali di HA, registra le entità, applica aggiornamenti simulati,
apre le opzioni e scarica l'integrazione.
La suite della 0.2.0 aggiunge test dei comandi, del PIN, dei permessi, delle
corrispondenze, dei rifiuti, della serializzazione e dell’assenza di reinvio
automatico. I servizi HA di inserimento e disinserimento sono esercitati nel
test di ciclo completo con client simulato.
La 0.3.0 aggiunge test dei controlli di esclusione/inclusione e della selezione
delle modalità, comprese chiamate ai servizi switch in Home Assistant reale
con risposte AVS simulate.
Il codice sorgente del client è separato dall'adattamento a Home Assistant
nel file `custom_components/nova_alarm/api.py`.

Riferimenti di architettura:

- [Config entries](https://contributors.home-assistant.io/core/integrations/config-entries/)
- [Aggiornamenti coordinati](https://contributors.home-assistant.io/architecture/core/data-updates/)


## HACS e controlli su GitHub

Il file `hacs.json` configura il progetto come integrazione scaricabile.
Il workflow `Validate` esegue test, lint e controllo HACS a ogni push/PR.
Il controllo del brand è escluso per questa prima versione come repository
personalizzato: non è una dichiarazione di ammissione al catalogo HACS.
Il README e le issue del repository costituiscono la documentazione e il
canale per le segnalazioni. Licenza MIT.

## Diagnostica di accesso e comandi (0.3.1)

Se l’app ufficiale legge lo stato ma Home Assistant non riesce a configurare
l’integrazione, non è ancora possibile attribuire il problema alla centrale,
alla rete o alla sessione. Dalla 0.3.1 i moduli `nova_alarm.config_flow` e
`nova_alarm.coordinator` registrano il tipo di errore, l’endpoint AVS e un codice
controllato, per esempio `TOO-MANY-USERS`, `COMMUNICATION-ERROR`, `timeout`,
`http_429` o `invalid_xml`. I messaggi della configurazione distinguono queste
cause. Non vengono registrati parametri, PIN, credenziali, token o XML remoto.

Dopo l’aggiornamento e il riavvio, riprova soltanto l’accesso o la lettura e apri
**Impostazioni → Sistema → Registri**, cercando `AVS setup failed` oppure
`AVS read failed`. Per problemi ai comandi cerca `AVS command failed`.
Non ripetere un comando dall’esito incerto prima di aver verificato lo stato
nell’app ufficiale. Non occorre eliminare e ricreare l’integrazione per ottenere
questi dettagli; eventuali nuove configurazioni possono registrare un nuovo
dispositivo sull’account AVS.

### Correzione comandi nella 0.3.2

La richiesta dei comandi ora mantiene la virgola letterale nelle coppie
settore/modalità e zona/esclusione, come l’app ufficiale. Prima veniva inviata
come `%2C`: questa differenza è stata individuata dopo una risposta
`BAD-ARGUMENT` sul campo. I test confrontano i byte effettivi del corpo HTTP;
la conferma del funzionamento sull’impianto rimane da effettuare.
Aggiorna da HACS e riavvia Home Assistant. Non vengono inviati comandi durante
l’aggiornamento e non vengono introdotti reinvii automatici o forzature.

## PIN dei comandi facoltativo (0.3.3)

Durante la prima configurazione o nelle opzioni dell’integrazione trovi
**Richiedi il PIN per inserire e disinserire**, attivo per default anche per
le installazioni esistenti. Puoi disattivarlo senza riconfigurare l’account.

Quando è disattivato, il pannello comunica a Home Assistant che non serve
un codice: le schede che rispettano questi attributi, compresa Mushroom,
non devono mostrarne la richiesta. Anche i servizi di inserimento e
disinserimento funzionano senza `code`. Chi ha accesso ai controlli del
pannello in HA può quindi usare entrambe le operazioni senza un secondo PIN.
Riattivando l’opzione tornano la richiesta e la verifica del codice.

Il PIN della centrale resta obbligatorio nella configurazione: autentica
la sessione AVS e non viene eliminato o esposto nelle entità. L’opzione
riguarda solo il controllo locale dei comandi in HA, non il protocollo AVS,
i permessi, le esclusioni o i controlli sulle zone. L’aggiornamento e la
modifica dell’opzione non inviano comandi all’impianto.

## Convivenza con l’app Mio Antifurto (0.4.0)

Prima della 0.4.0 l’integrazione manteneva la sessione aperta tra i polling.
Ora, per default, dopo ogni lettura e ogni comando tenta il logout della
**propria** sessione, anche se l’operazione fallisce o viene annullata. La
rilettura successiva a un comando apre e chiude una propria sessione.
L’ID dispositivo rimane quello salvato, non viene generato a ogni accesso.
Le descrizioni già lette rimangono in cache per non richiederle a ogni login.

Aggiorna e riavvia HA. Nelle opzioni:

- **Mantieni la sessione AVS aperta**: lascia disattivato per liberare la
  sessione tra le operazioni. Attivandolo si torna al comportamento precedente.
- **Aggiornamenti automatici**: puoi disattivarli per evitare accessi periodici
  mentre usi l’app. Restano la lettura iniziale all’avvio/reload, gli aggiornamenti
  richiesti manualmente (per esempio `homeassistant.update_entity`) e le riletture
  dopo i comandi. I sensori non si aggiornano autonomamente in questa modalità:
  non interpretare un vecchio stato come una lettura attuale.

Il logout riduce l’occupazione della sessione, ma non aggira eventuali limiti
AVS sugli accessi simultanei: durante una lettura/comando HA la sessione resta
necessaria. Gli accessi più frequenti aumentano anche il numero di login/logout;
non è consigliato ridurre aggressivamente il polling. Se il server risponde
`TOO-MANY-USERS` non vengono espulse sessioni altrui né forzati accessi.
Un logout fallito viene segnalato nei registri come `AVS logout unconfirmed`:
la cancellazione dei token locali non garantisce la chiusura sul server.
La convivenza effettiva con l’app resta da verificare sull’impianto; lo sviluppo
ha usato esclusivamente risposte simulate e non ha inviato comandi reali.
