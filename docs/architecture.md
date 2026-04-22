# Architettura

Questo documento descrive l'architettura generale di Maestro.
È il riferimento primario per chiunque — umano o agente — lavori sul codice.

## 1. Obiettivi e non-obiettivi

### Obiettivi

- Permettere a un agente AI di pilotare il deployment, la configurazione e
  l'avvio di progetti multi-componente su più macchine tramite uno schema YAML
  semplice.
- Ridurre il consumo di token dell'agente esponendo primitive di alto livello
  (verbi ben definiti, risposte strutturate, errori classificati) invece di
  richiedere ragionamento su output shell grezzi.
- Supportare deploy idempotenti: solo i componenti variati vengono ridistribuiti
  o riavviati.
- Supportare più tipologie di runtime: processi gestiti da systemd, container
  Docker, manifest Kubernetes (dalla Fase 3).
- Integrarsi con Git per un flusso CI/CD reattivo (Fase 2).
- Esporre un'interfaccia utente web per modifica della configurazione e
  osservazione dello stato.
- Esporre un server MCP così che qualsiasi agente compatibile possa operare sul
  sistema.

### Non-obiettivi

- Non vuole sostituire Ansible, Terraform, Puppet, Chef su progetti enterprise
  complessi. L'obiettivo è coprire comodamente progetti di piccola-media scala.
- Non vuole essere un sistema multi-tenant SaaS. È pensato per essere installato
  e usato da una singola organizzazione.
- Non gestisce il provisioning delle macchine stesse (creazione VM, networking,
  firewall). Presuppone macchine già raggiungibili via rete.

## 2. Architettura a tre piani

```
                    ┌─────────────────────────────────────┐
                    │          Utente / Agente AI         │
                    └────┬────────────┬───────────────────┘
                         │            │
                 HTTP/WS │            │ MCP (JSON-RPC)
                         │            │
                    ┌────▼────────────▼───────────────────┐
                    │         Control Plane (Python)      │
                    │                                     │
                    │  ┌───────────┐  ┌─────────────────┐ │
                    │  │  Web UI   │  │   MCP Server    │ │
                    │  └─────┬─────┘  └────────┬────────┘ │
                    │        │                 │          │
                    │  ┌─────▼─────────────────▼────────┐ │
                    │  │   Orchestrator & State Hub     │ │
                    │  └────────────────┬───────────────┘ │
                    │                   │                 │
                    │  ┌────────────────▼───────────────┐ │
                    │  │   WebSocket Hub (per daemon)   │ │
                    │  └────────────────┬───────────────┘ │
                    └───────────────────┼─────────────────┘
                                        │
                         WebSocket (TLS, mutual-auth token)
                                        │
        ┌───────────────────────────────┼────────────────────────────┐
        │                               │                            │
   ┌────▼────┐                    ┌─────▼────┐                 ┌─────▼────┐
   │maestrod │                    │ maestrod │                 │ maestrod │
   │ host A  │                    │  host B  │                 │ host C   │
   └────┬────┘                    └─────┬────┘                 └─────┬────┘
        │                               │                            │
   ┌────▼──────────┐              ┌─────▼─────────┐           ┌──────▼────┐
   │ systemd units │              │  containers   │           │ systemd + │
   │               │              │   (Docker)    │           │  docker   │
   └───────────────┘              └───────────────┘           └───────────┘
```

### Control plane

Servizio Python (FastAPI). Responsabilità:

- Leggere, validare, rendere persistenti e versionare i file `deployment.yaml`.
- Mantenere il registro degli host connessi e dei componenti desiderati.
- Calcolare il diff fra stato desiderato e stato osservato.
- Orchestrare i deploy con la strategia configurata (sequenziale nella Fase 1,
  canary/blue-green dalla Fase 2).
- Esporre una REST API per la UI e un server MCP per gli agenti.
- Gestire l'hub WebSocket verso i daemon.
- Centralizzare log e metriche ricevuti dai daemon.

### Daemon (maestrod)

Binario Go statico installato come servizio systemd su ogni host. Responsabilità:

- Stabilire la connessione WebSocket in uscita verso il control plane appena
  avviato, autenticandosi con un token.
- Mantenere uno store locale (SQLite) con lo stato corrente: componenti
  installati, revisione deployata, config applicata, PID/container ID, stato
  runtime, ultimo healthcheck.
- Eseguire le azioni richieste dal control plane tramite i runner appropriati.
- Pubblicare eventi non sollecitati (drift, crash, healthcheck falliti) e
  metriche periodiche.
- Gestire localmente il ciclo di vita dei processi, inclusi retry su errori
  transitori.

### Agente AI

Non è parte del codice che produciamo — è Claude (o un altro LLM) che parla al
control plane via MCP. Il suo comportamento è guidato dalla skill in `skill/`,
che lo istruisce sul flusso corretto (validate → diff → conferma → apply →
watch → verify) e sulla gestione degli errori classificati.

## 3. Modello di comunicazione

### Control plane ↔ daemon

Il daemon apre una singola WebSocket in uscita verso il control plane. Questo
elimina la necessità di aprire porte in ingresso sugli host ed è amichevole
con firewall/NAT.

Protocollo dettagliato in `protocol.md`. In sintesi:

- Messaggi JSON con envelope `{id, type, payload}`.
- Richieste dal control plane con id univoco; il daemon risponde con lo stesso id.
- Il daemon pubblica eventi asincroni (`event.drift`, `event.healthcheck_failed`,
  `event.metrics`) con tipo dedicato.
- Heartbeat bidirezionale ogni 15 secondi; timeout a 45 secondi.
- Riconnessione automatica con backoff esponenziale e jitter.

### Agente ↔ control plane (MCP)

Server MCP esposto dal control plane con i verbi:

- `list_hosts`, `get_host_state`
- `list_components`, `get_component_state`
- `get_config`, `validate_config`, `apply_config`
- `deploy` (con target: host, componente o intero progetto), `rollback`
- `start`, `stop`, `restart`
- `run_tests`
- `tail_logs`, `get_metrics`
- `get_deployment_history`

Tutti i verbi ritornano oggetti strutturati. Gli errori hanno una tassonomia
(`validation_error`, `dependency_missing`, `auth_error`, `runtime_error`,
`timeout`, `conflict`, `not_found`) con `suggested_fix` dove applicabile.

### Utente ↔ control plane

- UI web (browser): pagine per dashboard, editor YAML, log streaming,
  storico deploy.
- REST API parallela alla MCP, usata dalla UI.

## 4. Modello di stato e idempotenza

Lo stato di un componente deployato è una tripla:

```
component_hash = sha256(git_commit || rendered_config || build_artifact_hash)
```

Ogni deploy:

1. Il control plane calcola il `component_hash` desiderato.
2. Chiede al daemon il `component_hash` corrente.
3. Se coincidono, no-op (il componente è stabile).
4. Se differiscono, il daemon esegue il deploy secondo il `deploy_mode`
   dichiarato nello YAML (`hot`, `cold`, `blue_green`), poi aggiorna il suo
   store con il nuovo hash.

Questo garantisce:

- **Idempotenza**: un secondo run a parità di input non produce effetti.
- **Deploy selettivo**: solo i componenti con hash cambiato vengono toccati.
- **Rollback deterministico**: il daemon tiene lo storico degli ultimi N hash
  e può tornare a uno precedente.

## 5. Tipologie di deploy per componente

```yaml
deploy_mode: hot | cold | blue_green
```

- **hot**: update senza downtime. Il runner sa come ricaricare senza fermare
  (es. `systemctl reload`, container con `--recreate` e healthcheck, binario
  che gestisce `SIGHUP`). Possibile solo se dichiarato dal componente.
- **cold**: stop → deploy → start. Comporta downtime ma è universale.
- **blue_green**: il nuovo è installato in parallelo, healthcheck, poi switch
  del traffico e teardown del vecchio. Richiede load balancer o proxy davanti.

## 6. Credenziali e sicurezza

### Fase 1

Credenziali in un file `credentials.yaml` cifrato con una master key derivata
da passphrase utente (scrypt), memorizzata in chiaro solo in RAM nel control
plane. Le credenziali supportate sono:

- SSH/token per accesso a Git (usato dal control plane per il clone dei repo).
- Secrets per componenti (env vars) — trasmessi ai daemon via WebSocket al
  momento del deploy, mai persistiti in chiaro su disco lato daemon.
- Token di registrazione del daemon (pre-shared).

### Fase 2+

Modulo `credentials` con interfaccia pluggable:

- File cifrato locale (default).
- Integrazione con HashiCorp Vault.
- Integrazione con AWS Secrets Manager / GCP Secret Manager / Azure Key Vault.

Le credenziali Git e i secrets applicativi sono concettualmente distinti ma
passano attraverso la stessa interfaccia.

## 7. Integrazione Git / CI-CD

Dalla Fase 2, un componente interno del control plane chiamato **git-sync**:

- Riceve webhook (GitHub, GitLab, Gitea, Bitbucket) configurati per i repo
  dei componenti.
- In alternativa, esegue polling configurabile (default 5 minuti).
- Alla ricezione di un nuovo commit sul ref tracciato, segna il componente
  come "drift detected" e, in base alla policy, esegue automaticamente il
  deploy o notifica l'agente/utente.
- Risolve `ref: main` a commit hash concreto prima di passarlo al daemon.

## 8. Test e verifica

### Test framework (Fase 2)

Ogni componente nello YAML può dichiarare test:

```yaml
tests:
  unit:
    command: npm test
    when: pre_deploy      # blocca il deploy se falliscono
  integration:
    command: npm run test:integration
    when: post_deploy
    requires: [db, redis]
  smoke:
    http: GET /health
    expect: 200
    when: post_deploy
```

Il daemon esegue i test nella directory di lavoro del componente e riporta il
risultato come evento strutturato. In caso di fallimento di un test bloccante,
il control plane avvia il rollback.

### Test del prodotto stesso

Stratificati su tre livelli:

- **Unit test control plane**: `pytest`, mock dei client WebSocket, copertura
  dei moduli parser YAML, orchestrator, validator.
- **Unit test daemon**: test Go standard (`go test`), con runner mock.
- **Integration test**: test che avviano control plane + daemon (o più daemon)
  reali in processo, usano container Docker di supporto, verificano flussi end-to-end
  (validate → apply → deploy → healthcheck → rollback).

Ogni documento di fase include una sezione "Test di accettazione" che l'agente
incaricato dello sviluppo deve eseguire autonomamente prima di dichiarare la
fase completa.

## 9. Scelte tecniche motivate

| Area | Scelta | Motivazione |
|------|--------|-------------|
| Daemon | Go | Binario statico single-file, facile distribuzione su qualsiasi Linux, basso consumo RAM, goroutine ottimali per WS + processi gestiti |
| Control plane | Python (FastAPI) | Ecosistema maturo per MCP, integrazione Claude SDK, sviluppo rapido, UI stack flessibile |
| Store daemon | SQLite | Zero dipendenze, transazionale, adatto a piccoli dataset locali |
| Store control plane | SQLite (Fase 1) → PostgreSQL (Fase 3) | Migrazione banale via SQLAlchemy; SQLite basta per iterare |
| Trasporto | WebSocket su TLS | Bidirezionale, NAT-friendly, gestito bene da entrambi gli ecosistemi |
| UI | React + Vite (Fase 2) / HTMX (Fase 1) | Fase 1 minima e leggera; Fase 2 introduce componenti ricchi |
| Auth MCP | Token bearer per client | Standard MCP, semplice da gestire |
| Auth daemon | Token pre-shared + mutual TLS (Fase 3) | Pre-shared basta a Fase 1/2; mTLS aggiunto a Fase 3 per produzione |

## 10. Struttura del codice

### Control plane (`control-plane/`)

```
app/
├── main.py               FastAPI app, startup, uvicorn entry
├── api/                  Endpoint REST per la UI
│   ├── hosts.py
│   ├── components.py
│   ├── config.py
│   └── deploy.py
├── ws/                   WebSocket hub
│   ├── hub.py            Registry di connessioni attive
│   ├── protocol.py       Definizione messaggi (pydantic models)
│   └── handler.py        Dispatch di messaggi entranti
├── mcp/                  Server MCP
│   ├── server.py
│   └── tools.py          Mapping verbi → funzioni orchestrator
├── orchestrator/         Logica di business
│   ├── engine.py         Motore deploy, gestione rollout
│   ├── diff.py           Calcolo diff stato desiderato vs osservato
│   ├── rollback.py
│   └── tests_runner.py   (Fase 2)
├── config/               Parser YAML
│   ├── schema.py         Pydantic models dello schema
│   ├── loader.py
│   ├── validator.py
│   └── renderer.py       Template rendering (Jinja2)
└── credentials/          Store credenziali
    ├── vault.py          Interfaccia
    └── file_backend.py   Backend file cifrato

tests/
├── unit/
│   ├── test_config_parser.py
│   ├── test_diff.py
│   ├── test_orchestrator.py
│   └── test_credentials.py
└── integration/
    ├── test_ws_handshake.py
    ├── test_deploy_flow.py
    └── test_mcp_tools.py
```

### Daemon (`daemon/`)

```
cmd/maestrod/
└── main.go               Entry point, parsing flag, lifecycle

internal/
├── config/               Config locale del daemon (endpoint, token)
├── ws/                   Client WebSocket
│   ├── client.go
│   ├── protocol.go
│   └── reconnect.go
├── state/                Store locale
│   ├── store.go          Interfaccia
│   └── sqlite.go
├── runner/               Esecutori per tipologia
│   ├── runner.go         Interfaccia
│   ├── systemd.go
│   └── docker.go
├── metrics/              Collettore metriche
│   ├── collector.go
│   └── system.go
└── orchestrator/         Mini-orchestratore locale (retry, lifecycle)
    └── lifecycle.go

test/integration/
├── systemd_runner_test.go
├── docker_runner_test.go
└── ws_roundtrip_test.go
```

I test unitari Go stanno accanto al codice (`foo_test.go` vicino a `foo.go`)
per convenzione.

### Test cross-componente (`tests/`)

```
e2e/
├── test_full_deploy.py        Avvia control plane + un daemon reale, deploy completo
├── test_idempotency.py        Verifica che un secondo apply sia no-op
├── test_rollback.py           Simula fallimento e verifica rollback
└── test_multi_host.py         Due daemon, componenti distribuiti

fixtures/
├── deployment-simple.yaml
├── deployment-multihost.yaml
└── components/                Repository fake usati nei test
```

## 11. Ciclo di vita di un deploy tipo

1. Utente modifica `deployment.yaml` via UI.
2. UI chiama `POST /config/validate` → control plane valida lo schema e
   ritorna eventuali errori.
3. Se valido, UI chiama `POST /config/diff` → control plane mostra quali
   componenti cambieranno.
4. Utente conferma, UI chiama `POST /deploy`.
5. Orchestrator determina l'ordine (topologico sulle dipendenze) e per
   ciascun componente:
   a. Risolve le credenziali necessarie.
   b. Se serve clone Git, lo fa nel workspace del control plane.
   c. Renderizza template di config con le variabili.
   d. Invia al daemon target il messaggio `deploy` con payload completo.
   e. Attende risposta; il daemon esegue, testa localmente, risponde.
   f. Attende healthcheck positivo.
6. Quando tutti i componenti sono green, l'operazione è marcata complete.
7. In caso di fallimento di uno step, il control plane tenta rollback dei
   componenti già deployati nella stessa sessione.

## 12. Osservabilità

- Log strutturati (JSON) su stdout per daemon e control plane.
- Metriche Prometheus esposte dal control plane (deploy per minuto, durata,
  tasso di fallimento, numero host connessi).
- Metriche per-componente raccolte dai daemon (CPU, RAM, restart count,
  uptime) e pubblicate sul canale WebSocket.
- Audit log persistente di tutte le azioni umane e agenti sul control plane.

## 13. Evoluzione prevista

Vedi `roadmap.md` per la suddivisione in fasi. In sintesi:

- **Fase 1 (Prototipo)**: slice verticale funzionante, Linux/systemd/Docker,
  YAML v1, UI minimale, MCP base, no Git-sync, no K8s.
- **Fase 2 (Beta)**: Git-sync, test framework, credential vault, rollback/hot,
  MCP completo, UI ricca, skill matura.
- **Fase 3 (Production)**: Kubernetes, osservabilità avanzata, HA, CLI,
  pacchettizzazione, documentazione utente completa.
