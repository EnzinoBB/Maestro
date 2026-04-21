# Protocollo Control Plane ↔ Daemon

Questo documento descrive il protocollo di comunicazione fra il control plane
e i daemon `rcad`. Il trasporto è WebSocket su TLS (in produzione). Il formato
dei messaggi è JSON.

## 1. Stabilimento della connessione

### Fase di handshake

Il daemon apre una connessione WebSocket verso l'endpoint del control plane
(default `wss://<control-plane>/ws/daemon`) includendo i seguenti header HTTP:

```
Authorization: Bearer <daemon_token>
X-RCA-Daemon-Id: <id_univoco_del_daemon>
X-RCA-Daemon-Version: <version_string>
X-RCA-Host-Info: <base64(json con hostname, os, arch, kernel)>
```

Il control plane valida il token, registra il daemon nell'hub e risponde
con upgrade WebSocket riuscito. Se l'auth fallisce, risposta 401 e il daemon
riprova dopo backoff.

Dopo l'upgrade, il primo messaggio è un `hello` inviato dal control plane:

```json
{
  "id": "ctl-0001",
  "type": "hello",
  "payload": {
    "server_version": "1.0.0",
    "assigned_host_id": "api-server",
    "heartbeat_interval_sec": 15,
    "session_id": "s-c3f1..."
  }
}
```

Il daemon risponde con `hello_ack` che include lo stato corrente sintetico:

```json
{
  "id": "dmn-0001",
  "type": "hello_ack",
  "in_reply_to": "ctl-0001",
  "payload": {
    "daemon_version": "1.0.0",
    "runners_available": ["systemd", "docker"],
    "components_known": [
      {"id": "api", "component_hash": "a1b2...", "status": "running"},
      {"id": "db",  "component_hash": "f9e8...", "status": "running"}
    ],
    "system": {"cpu_count": 4, "total_mem_mb": 8192}
  }
}
```

## 2. Envelope dei messaggi

Ogni messaggio ha la forma:

```json
{
  "id": "<string univoco del messaggio>",
  "type": "<string: categoria.nome>",
  "in_reply_to": "<id del messaggio richiesto, se risposta>",
  "payload": { ... },
  "ts": "2026-04-21T10:23:00Z"
}
```

Regole:

- `id` è UUIDv4 o stringa monotona, a scelta del mittente.
- Le risposte sincrone impostano `in_reply_to`.
- Gli eventi asincroni (push da daemon) non impostano `in_reply_to`.
- `ts` è opzionale ma raccomandato in ISO 8601 UTC.

## 3. Tassonomia dei `type`

I tipi seguono la convenzione `direction.category.name`:

- `request.*` — richiesta che attende risposta
- `response.*` — risposta sincrona
- `event.*` — notifica asincrona
- `ping`, `pong` — heartbeat
- `hello`, `hello_ack`, `bye` — lifecycle

## 4. Richieste dal control plane al daemon

### `request.state.get`

```json
{
  "id": "ctl-0010",
  "type": "request.state.get",
  "payload": {
    "components": ["api"]    // opzionale; se assente, tutti
  }
}
```

Risposta:

```json
{
  "id": "dmn-0042",
  "in_reply_to": "ctl-0010",
  "type": "response.state.get",
  "payload": {
    "components": [
      {
        "id": "api",
        "status": "running",         // running | stopped | failed | deploying | unknown
        "component_hash": "a1b2...",
        "git_commit": "c9d4e2f",
        "runner": "systemd",
        "pid": 12345,
        "started_at": "2026-04-20T09:00:00Z",
        "last_healthcheck": {
          "ok": true,
          "ts": "2026-04-21T10:22:45Z"
        },
        "metrics": {
          "cpu_pct": 2.1,
          "rss_mb": 128,
          "restarts_since_deploy": 0
        }
      }
    ]
  }
}
```

### `request.deploy`

Il messaggio più importante. Il control plane fornisce al daemon tutto il
necessario per deployare un componente.

```json
{
  "id": "ctl-0020",
  "type": "request.deploy",
  "payload": {
    "component_id": "api",
    "target_hash": "7a9b...",
    "deploy_mode": "cold",
    "source": {
      "type": "inline_tarball",     // tarball del codice, base64
      "data": "H4sIAAAAAAA..."
      // oppure type=git e credenziali per clone lato daemon
      // oppure type=docker_image e tag
    },
    "build_steps": [
      {"command": "npm ci", "working_dir": ".", "env": {}}
    ],
    "config_files": [
      {"dest": "/opt/demo-api/.env", "mode": 420, "content_b64": "..."}
    ],
    "run": { ... },              // ComponentSpec.run intero
    "secrets": {                 // volatili, mai persistiti su disco dal daemon
      "DB_PASSWORD": "xxx"
    },
    "healthcheck": { ... },
    "timeout_sec": 900
  }
}
```

Risposta (sincrona, può arrivare al termine del deploy):

```json
{
  "in_reply_to": "ctl-0020",
  "type": "response.deploy",
  "payload": {
    "ok": true,
    "component_id": "api",
    "new_hash": "7a9b...",
    "duration_ms": 45200,
    "phases": [
      {"name": "fetch",    "ok": true, "duration_ms": 3100},
      {"name": "build",    "ok": true, "duration_ms": 38000},
      {"name": "stop_old", "ok": true, "duration_ms": 800},
      {"name": "swap",     "ok": true, "duration_ms": 1200},
      {"name": "start",    "ok": true, "duration_ms": 600},
      {"name": "health",   "ok": true, "duration_ms": 1500}
    ]
  }
}
```

In caso di errore:

```json
{
  "in_reply_to": "ctl-0020",
  "type": "response.deploy",
  "payload": {
    "ok": false,
    "component_id": "api",
    "error": {
      "code": "build_failed",
      "phase": "build",
      "message": "npm ci exited with code 1",
      "details": {
        "stderr_tail": "npm ERR! could not resolve package...",
        "missing_dependency": "libpq-dev"
      },
      "suggested_fix": "install libpq-dev on host and retry"
    }
  }
}
```

### Codici errore standard

| Code | Significato |
|------|-------------|
| `validation_error` | Payload non conforme allo schema atteso |
| `auth_error` | Problemi di autenticazione verso registry/git |
| `fetch_failed` | Impossibile scaricare sorgenti/immagini |
| `build_failed` | Errore durante build |
| `dependency_missing` | Dipendenza di sistema assente |
| `config_error` | Template config non valido o variabile non risolta |
| `runtime_error` | Errore all'avvio del componente |
| `healthcheck_failed` | Componente avviato ma healthcheck fallito |
| `timeout` | Operazione scaduta |
| `conflict` | Stato corrente incompatibile con l'azione |
| `not_found` | Componente non esiste |
| `internal` | Errore interno del daemon |

### Altre richieste

- `request.start` — avvia un componente già installato
  ```json
  { "payload": {"component_id": "api"} }
  ```
- `request.stop` — ferma un componente
  ```json
  { "payload": {"component_id": "api", "graceful_timeout_sec": 30} }
  ```
- `request.restart` — stop + start
- `request.rollback` — torna al precedente hash salvato
  ```json
  { "payload": {"component_id": "api", "steps_back": 1} }
  ```
- `request.logs.tail` — chiede log recenti
  ```json
  { "payload": {"component_id": "api", "lines": 200, "since": "2026-04-21T09:00:00Z"} }
  ```
- `request.logs.stream` — inizia uno stream (vedi §7)
- `request.healthcheck.run` — forza un healthcheck immediato
- `request.tests.run` (Fase 2) — esegue i test dichiarati
- `request.metrics.snapshot` — chiede un sample istantaneo

## 5. Eventi asincroni dal daemon

Pubblicati senza `in_reply_to`. Il control plane li dispatcha agli
osservatori (UI, orchestrator, storage).

### `event.metrics`

Inviato periodicamente (default ogni 30s) con snapshot delle metriche per tutti
i componenti:

```json
{
  "type": "event.metrics",
  "payload": {
    "ts": "2026-04-21T10:23:00Z",
    "components": [
      {"id": "api", "cpu_pct": 2.1, "rss_mb": 128, "fd": 42},
      {"id": "db",  "cpu_pct": 1.3, "rss_mb": 512, "fd": 89}
    ],
    "host": {"load_avg_1m": 0.4, "disk_usage_pct": 63}
  }
}
```

### `event.status_change`

```json
{
  "type": "event.status_change",
  "payload": {
    "component_id": "api",
    "from": "running",
    "to": "failed",
    "reason": "process exited with code 137"
  }
}
```

### `event.healthcheck_failed`

```json
{
  "type": "event.healthcheck_failed",
  "payload": {
    "component_id": "api",
    "consecutive_failures": 3,
    "last_check": {
      "type": "http",
      "url": "http://localhost:3000/health",
      "error": "connection refused"
    }
  }
}
```

### `event.drift_detected` (Fase 2)

Emesso quando il daemon nota che qualcosa è cambiato fuori dal suo controllo
(es. qualcuno ha fatto `systemctl stop` manualmente).

```json
{
  "type": "event.drift_detected",
  "payload": {
    "component_id": "api",
    "expected": "running",
    "observed": "stopped"
  }
}
```

### `event.log`

Solo durante stream attivo. Un messaggio per linea (o batch).

```json
{
  "type": "event.log",
  "payload": {
    "stream_id": "s-1234",
    "component_id": "api",
    "lines": [
      {"ts": "2026-04-21T10:23:00.123Z", "level": "INFO", "msg": "listening on :3000"}
    ]
  }
}
```

## 6. Heartbeat e riconnessione

- Entrambi i lati inviano `ping` ogni `heartbeat_interval_sec` (default 15s).
- Il ricevente risponde con `pong` sullo stesso id.
- Se non arriva `pong` per 3 intervalli consecutivi, la connessione è
  considerata morta e chiusa.

Quando il daemon perde la connessione:

1. Marca internamente lo stato come "offline" (ma continua a gestire i
   processi locali).
2. Tenta la riconnessione con backoff esponenziale: 1s, 2s, 4s, 8s, ..., cap a
   60s. Jitter ±20%.
3. Al riaggancio, ripete l'handshake. Se il `component_hash` locale diverge
   da quello che il control plane ha in memoria (perché qualcosa è successo
   offline), si riconcilia: il control plane considera autoritativo lo stato
   del daemon.

## 7. Streaming

Alcune operazioni ammettono streaming (logs, output di build in tempo reale).
Il protocollo:

1. Control plane invia `request.logs.stream` con un `stream_id` nel payload.
2. Daemon risponde immediatamente con `response.logs.stream.started`.
3. Daemon pubblica `event.log` con lo stesso `stream_id` fino a:
   - `request.logs.stream.cancel` dal control plane, oppure
   - `event.log.stream_ended` dal daemon (componente terminato)

## 8. Dimensione dei messaggi

- Limite hard: 4 MB per messaggio.
- Tarball di deploy più grandi → usare `source.type: git` (clone lato daemon)
  o upload fuori banda via HTTP con URL firmato (Fase 2).
- Streaming log: batch ogni 500ms o ogni 100 righe.

## 9. Versionamento del protocollo

L'handshake include `server_version` e `daemon_version`. Regole:

- Major version uguale → compatibilità garantita.
- Major version differente → connessione rifiutata con messaggio chiaro.
- Minor version differente → consentita; le feature non supportate dalla parte
  più vecchia ritornano `unsupported_operation`.

Campi nuovi vanno aggiunti in modo additivo; rimozioni richiedono bump major.

## 10. Sicurezza

- TLS sempre, tranne in sviluppo locale esplicito (`--insecure`).
- Token pre-shared gestito dal control plane; può essere revocato.
- In produzione (Fase 3): mutual TLS con certificati per-daemon.
- Tutti i secret nel payload `request.deploy` sono considerati volatili; il
  daemon non li scrive mai su disco persistente, li passa solo come env var ai
  processi figli.
- Audit log di tutti i messaggi inviati/ricevuti lato control plane.
