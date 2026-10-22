# Note di protocollo — versione 0.1.0

Ricostruzione statica dall'APK Mio Antifurto fornito dall'utente, con prima
verifica effettiva dell'accesso e delle letture tramite lo script Python.
Non sono inclusi APK, Java decompilato, credenziali o token nel progetto.

## Trasporto

HTTPS, metodo POST, `Content-Type: application/x-www-form-urlencoded`.
I valori sono sottoposti una sola volta a trim e codifica UTF-8 in stile
`URLEncoder` Android; gli spazi diventano `%20`. Le risposte sono XML.
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

