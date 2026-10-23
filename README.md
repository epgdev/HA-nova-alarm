# Nova Alarm per Home Assistant

Integrazione non ufficiale per monitorare e controllare impianti di allarme
compatibili con il cloud AVS tramite l’account **Mio Antifurto**.

Si installa come integrazione personalizzata di Home Assistant, tramite HACS
o copiando i file manualmente. Non richiede add-on, Docker o modifiche a
`configuration.yaml`.

## Prima di iniziare

- Home Assistant **2026.10.0 o successivo**. La versione di riferimento per i
  test è Home Assistant 2026.10.2.
- Un impianto raggiungibile dall’app ufficiale Mio Antifurto.
- Username e password dell’account AVS, oppure di un account invitato abilitato
  all’impianto, e il PIN della centrale.
- Connessione Internet: l’integrazione usa il cloud AVS, non il collegamento
  locale EWeb.

**Prima di configurare Home Assistant, accedi dall’app ufficiale Mio Antifurto
con l’account che userai nell’integrazione e accetta i termini e le condizioni
d’uso richiesti. Questo passaggio vale anche per gli account creati tramite
invito.** Apri l’impianto nell’app con il PIN e verifica di poterne leggere lo
stato. L’integrazione non accetta i consensi al posto dell’utente.

Un account non ancora attivato nell’app può vedere l’impianto ma non completare
la configurazione in Home Assistant, anche con credenziali corrette; può
comparire un errore di lettura o una risposta non valida (`invalid_xml`).

## Funzioni

- Pannello allarme per ogni settore, con inserimento e disinserimento.
- Modalità AVS **ON, HO, AR, PE, OFF**, con corrispondenze Home Assistant
  configurabili e possibilità di nascondere gli inserimenti non utilizzati.
- Richiesta del PIN per i comandi, attiva per default e disattivabile.
- Interruttore di esclusione/inclusione per ogni zona.
- Sensori di apertura, manomissione, batteria scarica, guasto, antimascheramento
  e memoria allarme; sensore della modalità AVS originale per ogni settore.
- Nomi di zone e settori dal cloud, quando disponibili.
- Aggiornamenti automatici configurabili e possibilità di aggiornamento manuale.
- Traduzioni italiane e inglesi.

## Installazione con HACS

1. Apri **HACS → ⋮ → Repository personalizzati**.
2. Aggiungi `https://github.com/epgdev/HA-nova-alarm`, categoria **Integrazione**.
3. Cerca **Nova Alarm**, scarica l’integrazione e riavvia Home Assistant.
4. Apri **Impostazioni → Dispositivi e servizi → Aggiungi integrazione** e cerca
   **Nova Alarm**.

Il repository va aggiunto come personalizzato: non è incluso automaticamente
nel catalogo predefinito di HACS.

## Installazione manuale

1. Scarica ed estrai lo ZIP della versione desiderata dal repository.
2. Copia `custom_components/nova_alarm` nella cartella `custom_components`
   della configurazione di Home Assistant. Il percorso finale deve essere
   `/config/custom_components/nova_alarm/manifest.json`.
3. Riavvia Home Assistant e aggiungi **Nova Alarm** da
   **Impostazioni → Dispositivi e servizi → Aggiungi integrazione**.

## Configurazione

1. Completa il primo accesso e l’accettazione dei termini nell’app ufficiale,
   come descritto in **Prima di iniziare**.
2. Inserisci username e password dell’account che vuoi usare.
3. Seleziona l’impianto e inserisci il PIN della centrale. Gli zeri iniziali
   vengono conservati.
4. Scegli se richiedere il PIN anche per inserire e disinserire da Home Assistant.

Il campo facoltativo **ID dispositivo esistente** serve a riutilizzare un ID
AVS già noto: richiede 16 caratteri esadecimali minuscoli. Se lasciato vuoto,
viene creato un ID stabile, conservato nei successivi riavvii e aggiornamenti.
Non condividere lo stesso ID tra client in esecuzione contemporaneamente.

Una nuova configurazione può registrare un dispositivo nell’account AVS.
Eliminare e ricreare ripetutamente l’integrazione può lasciare più dispositivi
registrati nel portale. Il logout chiude la sessione, non elimina la
registrazione del dispositivo. Gli aggiornamenti dell’integrazione conservano
l’ID esistente.

## Modalità e comandi

Le corrispondenze predefinite sono:

| Modalità AVS | Stato e comando Home Assistant |
| --- | --- |
| ON | Inserito fuori casa |
| HO | Inserito in casa |
| AR | Inserito personalizzato |
| PE | Inserito notte |
| OFF | Disinserito |

I nomi delle modalità possono essere personalizzati nell’impianto: verifica
nell’app ufficiale quali zone proteggono. Nelle opzioni di Nova Alarm puoi
cambiare la corrispondenza, che determina **sia lo stato visualizzato sia il
comando inviato**. Ogni modalità visibile deve avere uno stato HA distinto.
Il sensore della modalità AVS conserva il nome originale.

In **Modalità di inserimento visibili** seleziona solo quelle che utilizzi.
Per un impianto con il solo ON, lascia selezionato **ON**: rimarranno il relativo
inserimento e il disinserimento. Le modalità nascoste non sono comandabili dai
servizi HA, ma il loro stato viene comunque mostrato se attivate da un altro
client. La selezione si applica a tutti i settori dell’integrazione e non
modifica la programmazione della centrale.

I pulsanti sono limitati anche dai permessi restituiti da AVS. L’integrazione
non forza l’inserimento in presenza di un rifiuto e non esclude zone
automaticamente. Dopo ogni comando rilegge lo stato dalla centrale.

### Richiesta del PIN

L’opzione **Richiedi il PIN per inserire e disinserire** è attiva per default.
Il codice richiesto è il PIN della centrale configurato nell’integrazione.
Nelle automazioni passalo come stringa per conservare gli zeri iniziali,
ad esempio `code: "01234"` (codice fittizio).

Disattivando l’opzione, chi può controllare il pannello in Home Assistant può
inserire e disinserire senza digitare un secondo codice. Le schede compatibili
con gli attributi standard del pannello non mostreranno la richiesta del PIN.
Il PIN salvato rimane necessario per autenticare la connessione AVS.

### Esclusione delle zone

Ogni zona dispone di un interruttore **«Nome zona esclusione»**, abilitato per
default fra i controlli normali del dispositivo:

- **Acceso:** zona esclusa dalla protezione.
- **Spento:** zona inclusa nella protezione.

A impianto disinserito, escludi le zone desiderate e attendi la conferma dello
stato prima di inserire l’allarme. Per reincluderle, spegni i relativi
interruttori quando la centrale lo consente. Non viene programmata una
reinclusione automatica da Home Assistant.

Se una zona risulta attiva, i dati non sono disponibili o la centrale rifiuta
l’operazione, la modifica viene bloccata. Gli interruttori usano la sessione
autenticata con il PIN salvato, senza richiederlo a ogni cambio.
Puoi usarli anche tramite `switch.turn_on` e `switch.turn_off`.

Il sensore binario di esclusione è mantenuto per compatibilità con le
configurazioni precedenti; per modificare lo stato usa l’interruttore.
I sensori diagnostici aggiuntivi, disabilitati per default, possono essere
abilitati dalla pagina delle entità.

## Aggiornamenti e uso insieme all’app ufficiale

Nelle opzioni dell’integrazione puoi configurare:

| Opzione | Comportamento |
| --- | --- |
| Intervallo di aggiornamento | Da 30 a 600 secondi; valore predefinito 60 secondi. |
| Aggiornamenti automatici | Se disattivati, restano la lettura iniziale all’avvio o al reload, gli aggiornamenti manuali e le riletture dopo i comandi. |
| Mantieni la sessione AVS aperta | Disattivato per default: l’integrazione tenta il logout dopo ogni operazione per liberare la sessione per altri client. |

Senza aggiornamenti automatici, sensori e stati **non si aggiornano
periodicamente**. Puoi richiedere una lettura con `homeassistant.update_entity`
su un’entità dell’integrazione.

Le sessioni brevi riducono l’occupazione della connessione, ma non eliminano i
limiti AVS sugli accessi simultanei. Se l’app segnala un utente già connesso,
lascia disattivato **Mantieni la sessione AVS aperta** e valuta di disattivare
gli aggiornamenti automatici. Un intervallo più breve aumenta le richieste e,
con sessioni brevi, anche il numero di accessi e logout.

Account cloud distinti possono accedere allo stesso impianto; un account
invitato non garantisce un utente distinto nella centrale se viene usato lo
stesso PIN. Eventuali limiti della centrale e del servizio restano applicabili.

## Aggiornare l’integrazione

Da HACS apri **Nova Alarm** e installa l’aggiornamento; se non compare, usa
**⋮ → Riscarica** e seleziona la versione desiderata. Per l’installazione
manuale sostituisci l’intera cartella `custom_components/nova_alarm`.

Riavvia Home Assistant. Non occorre eliminare e ricreare l’integrazione:
credenziali, ID dispositivo ed entità vengono conservati. Se l’icona non si
aggiorna, ricarica la pagina del browser o dell’app.

## Risoluzione dei problemi

- **Impianto visibile ma configurazione non completata:** accedi prima
  dall’app ufficiale con lo stesso account, anche se invitato, accetta i
  termini richiesti e verifica l’accesso all’impianto con il PIN.
- **Utente già connesso o troppe connessioni:** controlla le altre sessioni e
  le opzioni descritte in **Aggiornamenti e uso insieme all’app ufficiale**.
  I dispositivi registrati nel portale non corrispondono necessariamente a
  sessioni attive. Gestisci registrazioni e limiti dall’app o dal portale AVS.
- **Pulsanti di inserimento mancanti:** controlla le modalità visibili e i
  permessi dell’utente nell’app ufficiale.
- **Comando non confermato:** verifica lo stato nell’app ufficiale prima di
  riprovare. L’integrazione non ripete automaticamente le scritture dopo un
  timeout o una risposta non valida.
- **Nomi non disponibili:** vengono usati nomi generici, rinominabili da Home
  Assistant.

Per altri errori apri **Impostazioni → Sistema → Registri** e cerca **Nova
Alarm**. Le voci `AVS setup failed`, `AVS read failed`, `AVS command failed` e
`AVS logout unconfirmed` indicano il passaggio interessato e la causa
riconosciuta. Per risposte non valide, `AVS invalid XML response` riporta solo
stato HTTP, dimensione e tipo della risposta, senza registrarne il contenuto.

Per segnalare un problema usa le [issue del repository](https://github.com/epgdev/HA-nova-alarm/issues),
indicando versioni di Home Assistant e dell’integrazione, comportamento atteso
e messaggi pertinenti dei registri. Non pubblicare password, PIN o token.

## Compatibilità e limiti

Nova Alarm è un progetto non ufficiale e non garantisce la compatibilità con
tutti i modelli AVS/Nova. Dipende dal servizio cloud e dal relativo protocollo,
che può cambiare. Non usa il protocollo locale EWeb.

Non sono ricostruiti gli stati di ingresso/uscita ritardati, sirena attiva e
`triggered`: **la memoria allarme di una zona non indica un allarme attualmente
in corso**. Dati mancanti o errori di aggiornamento rendono le entità
indisponibili. Non sono implementati inserimenti forzati o comandi globali
al settore aggregato con ID 0.

Le credenziali e il PIN sono conservati nella configurazione gestita da Home
Assistant; non vengono esposti nelle entità o nei registri dell’integrazione.
I token di sessione rimangono in memoria.

Le note tecniche sul protocollo sono disponibili in [PROTOCOL.md](PROTOCOL.md).
Licenza [MIT](LICENSE).
