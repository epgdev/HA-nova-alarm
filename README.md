# Nova Alarm per Home Assistant — 0.1.0

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
- Un `alarm_control_panel` in sola lettura per settore.
- Un sensore con la modalità originale AVS: ON, HO, AR, PE, OFF.
- Sensori binari per apertura, manomissione, esclusione, batteria scarica,
  guasto, antimascheramento e memoria allarme di ciascuna zona.
- Nomi delle zone e dei settori recuperati dal cloud, se disponibili.
- Aggiornamento coordinato ogni **60 secondi**, modificabile da 30 a 600.
- Sessione condivisa fra le entità, richieste serializzate, un solo tentativo
  di rinnovo per aggiornamento quando la sessione scade.
- Nuova richiesta delle credenziali se l'autenticazione viene rifiutata.
- Traduzioni italiane e inglesi; identificativi stabili delle entità.

Per limitare l'affollamento, apertura e manomissione sono abilitate per default.
Gli altri sensori diagnostici possono essere abilitati nella pagina delle entità.
Il bit AVS `attiva` non viene esposto: la sua utilità come entità autonoma
deve ancora essere verificata.

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

Non sono implementati inserimento, disinserimento o esclusione delle zone.
Home Assistant può mostrare un'azione di disinserimento anche per un pannello
senza funzioni supportate: se invocata, questa versione restituisce un errore
esplicito e non invia richieste di comando alla centrale.

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
Esito iniziale: **18 test superati** su Home Assistant 2026.10.2/Python 3.14.8;
controlli Ruff e formattazione superati. Il test di ciclo completo carica
le piattaforme reali di HA, registra le entità, applica aggiornamenti simulati,
apre le opzioni e scarica l'integrazione.
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
