# Note di protocollo — versione 0.5.0

Ricostruzione statica dall'APK Mio Antifurto fornito dall'utente, con prima
verifica effettiva dell'accesso e delle letture tramite lo script Python.
Non sono inclusi APK, Java decompilato, credenziali o token nel progetto.

## Trasporto

HTTPS, metodo POST, `Content-Type: application/x-www-form-urlencoded`.
Le credenziali sono sottoposte una sola volta a trim e codifica UTF-8 in stile
`URLEncoder` Android; gli spazi diventano `%20`. `Utils.getPostDataString`
unisce invece i valori già preparati, senza applicare ulteriore URL encoding.
`SetSectorsJob` e `SetZonesJob` passano le coppie numeriche direttamente:
nel corpo HTTP `sectors=1,0` e `zones=6,1` mantengono la virgola letterale.
La 0.3.2 preserva questa virgola solo nelle coppie singole validate; credenziali,
token e altri campi conservano l’escaping. Le risposte sono XML.
La trasformazione delle credenziali del sito EWeb locale è un altro protocollo
e non è applicata alle chiamate cloud.

La discovery `/avs/felist` su `dr.myavsalarm.com:443` restituisce elementi
`SERVER` con attributo `hostname`. Il client accetta solo hostname
`fe<numero>.myavsalarm.com` e usa HTTPS sulla porta 443. Se la discovery
non è disponibile, il fallback iniziale è `fe1.myavsalarm.com:443`.
Non vengono seguiti redirect contenenti credenziali.

## Autenticazione

Campi comuni: `devtype=3`, `appfev=43`, `systype=1`, `mac=<ID stabile>`.
Queste costanti descrivono il client analizzato e non sono una dichiarazione
di versione o di compatibilità con API pubbliche del produttore.

| Endpoint | Campi oltre a quelli comuni | Risposta utilizzata |
| --- | --- | --- |
| `/avs/portal_auth` | username, password, lang=IT | PLANT: idavs, name |
| `/avs/auth_ex` | username, password, aid, tokenid, aux, name, devicename, pin, localaid | AUTH_EX: auth; LOGIN: session |

`auth_ex` può registrare il dispositivo. Il client non invia `replaceiddevice`
né `disclaimer`. Password e PIN rimangono parametri in memoria; gli errori
restituiti all'integrazione non contengono la risposta XML originale.

## Letture e chiusura

| Endpoint | Parametri | Dati |
| --- | --- | --- |
| `/avs/get_sectors` | auth, session | GET_SECTORS/ITEM: id, type |
| `/avs/get_zones` | auth, session | GET_ZONES/ITEM: id, flags |
| `/avs/get_desc` | auth, session, id, type, appfev=43 | GET_DESC: desc; type=1 zona, type=4 settore |
| `/avs/logout` | auth, session | Conferma chiusura |

Le descrizioni sono metadati facoltativi: un loro errore non cancella uno
stato valido. Vengono richieste una volta per oggetto e sessione del client,
poi conservate fino al reload. La lettura dello stato invece è periodica.

Una risposta `ERROR` con `SESSION_EXPIRED` o `HTTP_UNAUTHORIZED` durante una
lettura provoca un solo nuovo login e un solo nuovo tentativo del gruppo di
letture. Errori delle credenziali richiedono intervento dell'utente tramite
reauth. Errori di connessione rendono indisponibili le entità. I limiti
dispositivi/abbonamento sono segnalati, senza tentativi di sostituzione.

## Evidenza disponibile

- Verificato sul campo: autenticazione account/PIN, lettura settore e sei zone,
  logout, `flags=1` corrispondente alla zona effettivamente aperta.
- Verificato sul campo e nel codice dell'app: `16777236 & 15 = 4`, OFF,
  allarme disinserito.
- Ricavato dal codice e verificato con fixture: bit delle zone, maschera delle
  modalità, campi delle descrizioni, errori e rinnovo delle sessioni.
- Da verificare sul campo: transizioni fisiche, altre modalità, descrizioni,
  scadenza effettiva della sessione, durata e limiti del polling continuo.
- Non ricostruiti: stato sirena attiva e temporizzazioni. Il bit memoria allarme
  non rappresenta da solo lo stato `triggered`.


## Comandi del settore (0.2.0)

Analisi statica dell’APK Mio Antifurto fornito per questa implementazione:
`SetSectorsJob.run`, `XMLSetSectorsParser.Handler.startElement`,
`plantSectors.changeStatus` e `XMLGetSectorsParser.Handler.startElement`.
Non vengono inclusi nel repository APK o sorgenti decompilati.

`POST /avs/set_sectors` invia `auth`, `session`, `sectors=<id>,<modo>`,
`check=1`, `checkzone=1`. Le modalità del comando singolo sono 0=ON, 1=HO,
2=AR, 3=PE, 4=OFF. L’app invia la stessa coppia settore/modalità anche per OFF.
Il PIN autentica la sessione in `auth_ex`; non è un parametro di `set_sectors`.
In Home Assistant viene inoltre richiesto e confrontato localmente con il PIN
configurato, senza convertirlo in numero.

I campi `on`, `ho`, `ar`, `pe`, `off` di `GET_SECTORS/ITEM` sono permessi:
l’app offre il relativo comando quando il campo è esattamente 1.
Il client rilegge stato e permessi sotto lo stesso lock della scrittura,
quindi invia un solo comando per un settore noto con ID numerico non zero.
Il settore aggregato 0 e le altre azioni numeriche dell’app non sono implementati.

La risposta deve contenere un unico `SET_SECTORS status="0"`.
L’app tratta status 1, 2 e 3 come rifiuti e usa anche `idzone` e `errstr`
(per esempio `no_zones`) per spiegare il blocco. Il client non espone il testo
remoto e rifiuta anche status mancanti, -1 o sconosciuti. Non implementa
la conferma dell’app che reinvia con `checkzone=0`.

Solo le letture possono rinnovare la sessione e ritentare automaticamente.
Le scritture non vengono ripetute dopo errori, sessione scaduta o timeout.
Home Assistant rilegge lo stato anche dopo un errore del comando; non pubblica
uno stato di inserimento o disinserimento basato sulla sola richiesta.
Queste richieste sono verificate con test simulati, non ancora sul campo.

## Esclusione/inclusione zone (0.3.0)

Evidenza statica: `SetZonesJob.run`, `XMLSetZonesParser.Handler.startElement`,
`plantZonesDetail.include`, `plantZonesDetail.esclude`, `Zone.setFlags`.

`POST /avs/set_zones` invia `auth`, `session`, `zones=<id>,<esclusione>`:
1 esclude, 0 reinclude. L’app blocca entrambe le modifiche quando `isActive()`
è vero, che corrisponde al bit 3 (`flags & 8`) della zona. Il client verifica
lo stesso bit su una lettura fresca sotto il lock condiviso; zona mancante,
flags sconosciuti e ID aggregati/non numerici non sono comandabili.
Se il bit di esclusione (2) è già quello richiesto non viene inviata la scrittura.
La risposta deve avere un unico `SET_ZONES status="0"`; status mancanti,
sconosciuti o non zero sono rifiutati. Non si espongono risposte remote o segreti.
Dopo la scrittura si rilegge lo stato; per le zone un bit di esclusione non
corrispondente al valore richiesto produce un esito non confermato.
Nessuna scrittura viene ripetuta automaticamente, nemmeno dopo timeout.
Il collaudo è simulato: nessun comando è stato inviato all’impianto reale.

## Correzione della serializzazione (0.3.2)

Segnalazione sul campo nella 0.3.1: `/avs/set_sectors` restituisce
`BAD-ARGUMENT`. Il confronto con `Utils.getPostDataString`, `SetSectorsJob`
e `SetZonesJob` ha rilevato una differenza: il client inviava `%2C` dove l’app
invia una virgola letterale. La correzione è verificata sul corpo HTTP esatto,
non solo tramite `parse_qs` che rende indistinguibili le due rappresentazioni.
Il legame con il rifiuto osservato resta da confermare sull’impianto reale.
Non vengono disabilitati controlli né ripetute scritture automaticamente.

## Durata delle sessioni (0.4.0)

`LogoutJob.run` dell’APK invia solo `auth` e `session` a `/avs/logout`.
La modalità predefinita ora racchiude ogni lettura/comando e il relativo logout
nel medesimo lock. Il login non viene duplicato fra prelettura e scrittura;
la conferma coordinata successiva è una lettura con una nuova sessione breve.
Il rilascio avviene nel `finally` anche su rifiuto o annullamento. Non vengono
chiuse sessioni di altri client. L’opzione `keep_session=true` ripristina
esplicitamente il riuso precedente; `automatic_updates=false` disabilita il
polling coordinato, non gli aggiornamenti iniziali/manuali/dopo comando.
La risposta `TOO-MANY-USERS` resta un errore da rispettare, senza tentativi di
forzatura; la reale politica di concorrenza del server non è stata verificata.

## Validazione e recupero (0.5.0)

`LOGIN.status` di `auth_ex` è obbligatorio: 0 autorizza l’adozione dei token;
2 indica PIN rifiutato; 4 utente già connesso; 5 troppi utenti; 7 accesso
inibito; 100 programmazione; 101 centrale occupata. Stato assente o non noto
produce un errore di protocollo. Le associazioni derivano da
`main_activity.AuthExHandler` e dalle stringhe dell’APK. I token di un login
rifiutato non vengono memorizzati e non vengono usati per letture o logout.

La discovery fallita o senza hostname ammessi non viene più considerata
completata. Viene ritentata dopo almeno 60 secondi; un errore di trasporto o
HTTP 500/502/503/504 sull’endpoint operativo invalida la cache della discovery
per un’operazione successiva. Nessuna richiesta di scrittura viene ripetuta.

Un logout senza conferma mantiene le credenziali della sola sessione posseduta
in memoria e imposta uno stato di rilascio pendente. L’operazione successiva
ritenta il logout prima di consentire un nuovo login, anche in modalità
persistente. `SESSION_EXPIRED` equivale a sessione già rilasciata; altrimenti
serve un elemento `LOGOUT` nella risposta. Errori e annullamenti non cancellano
le credenziali necessarie al recupero, né mascherano l’errore della scrittura.

Il coordinatore serializza ogni comando e la relativa conferma. L’operazione
ritorna successo solo quando le letture confermano la modalità del settore
o il bit di esclusione richiesti: al massimo tre letture, intervallate da due
secondi, con timeout di conferma di 20 secondi (l’eventuale cleanup della
sessione può richiedere tempo aggiuntivo). Un errore di lettura interrompe la
conferma. Lo stato pubblicato resta quello osservato, senza aggiornamenti
ottimistici. L’azione non confermata può essere già stata eseguita: non viene
reinvocata automaticamente.
