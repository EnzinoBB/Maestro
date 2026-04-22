# Fase 1 — Prototipo

> **Istruzioni per l'agente che legge questo documento.**
> Sei incaricato di sviluppare la Fase 1 di Maestro. Prima di
> scrivere codice, leggi:
> - `README.md`
> - `docs/architecture.md` (architettura complessiva — obbligatorio)
> - `docs/yaml-schema.md` (sottoinsieme da implementare è indicato sotto)
> - `docs/protocol.md` (sottoinsieme dei messaggi è indicato sotto)
> - `examples/deployment.yaml`
> - `skill/SKILL.md` (per sapere cosa l'agente consumer si aspetta)
>
> Segui la checklist operativa in §4. Dopo ogni gruppo di task, esegui i
> test del gruppo prima di passare al successivo. Al termine, esegui la
> **suite di accettazione** in §6. La Fase 1 si considera completa solo se
> tutti i test di accettazione passano.

## 1. Obiettivo della Fase 1

Consegnare uno **slice verticale funzionante**: un utente deve poter
modificare un `deployment.yaml`, caricarlo nella UI del control plane,
cliccare "Deploy" e vedere un componente Docker reale avviato su un host
Linux su cui è in esecuzione `maestrod`. Lo stesso risultato deve essere
ottenibile via server MCP.

Questa fase **non** include: Git-sync automatico, test framework per i
componenti, hot deploy, Kubernetes, canary, vault di produzione, UI ricca.

## 2. Prerequisiti dell'ambiente di sviluppo

- Linux (Ubuntu 22.04+ raccomandato) o macOS.
- Go 1.22+.
- Python 3.11+.
- Docker 24+ con permesso utente (`docker` group).
- `systemd` su un host di test (può essere una VM o container privilegiato).
- `make`, `git`, `curl`, `jq`.
- Playwright o Puppeteer per eventuali test UI (opzionale in Fase 1).

## 3. Sottoinsieme di schema e protocollo da implementare

### YAML: campi minimi accettati

Dal `yaml-schema.md` implementare:

- `api_version: maestro/v1` obbligatorio.
- `project`, `description`.
- `hosts.<id>` con `type: linux`, `address`, `user`, `tags`.
- `components.<id>` con:
  - `source` tipo `git` (clone sul control plane) o `docker`.
  - `build` (lista di step con `command`, `env`, `working_dir`, `timeout`).
  - `config.templates` (solo su filesystem host, no vault references).
  - `config.vars` (interpolazione `{{ hosts[..].address }}` e vars locali).
  - `run.type: systemd` o `run.type: docker` con i campi elencati in
    `yaml-schema.md` per quei tipi.
  - `healthcheck.type: http | tcp | command`.
  - `depends_on`.
  - `deploy_mode: cold` (solo cold è richiesto).
- `deployment[].host`, `.components`, `.strategy: sequential`,
  `.depends_on_hosts`.

Non richiesti in Fase 1: `secrets`, `tests`, `canary`, `blue_green`, `hot`
deploy, `defaults`, `credentials_ref` (accetta un file YAML di credenziali
opzionale in chiaro — sì, in chiaro in Fase 1: la cifratura arriva in Fase 2).

### Protocollo WebSocket: messaggi minimi

- `hello`, `hello_ack`, `ping`, `pong`, `bye`.
- `request.state.get` / `response.state.get`.
- `request.deploy` / `response.deploy` (solo con source tipo `inline_tarball`
  e `docker_image`).
- `request.start` / `response.start`.
- `request.stop` / `response.stop`.
- `request.restart` / `response.restart`.
- `request.healthcheck.run` / `response.healthcheck.run`.
- `request.logs.tail` / `response.logs.tail` (no streaming in Fase 1).
- `event.status_change`.
- `event.metrics` (periodico).

Non richiesti: `request.rollback`, `request.tests.run`,
`event.drift_detected`, streaming di log.

## 4. Checklist operativa

Lavora nell'ordine indicato. Ogni gruppo ha i suoi test; non passare al
successivo senza averli fatti passare.

### Gruppo A — Struttura e tooling

A1. Verifica la struttura di directory. Crea i file mancanti come file
    vuoti / `.gitkeep` per avere un albero pulito.

A2. Nel `control-plane/`, inizializza un progetto Python con `pyproject.toml`
    (dipendenze: `fastapi`, `uvicorn[standard]`, `pydantic`, `pyyaml`,
    `jinja2`, `websockets`, `sqlalchemy`, `aiosqlite`, `click`,
    `pytest`, `pytest-asyncio`, `httpx`, `mcp` (Model Context Protocol SDK)).

A3. Nel `daemon/`, inizializza un modulo Go (`go mod init
    github.com/<org>/maestro-daemon`). Dipendenze iniziali: `github.com/gorilla/websocket`,
    `modernc.org/sqlite` (o `mattn/go-sqlite3`), `github.com/spf13/cobra`,
    `github.com/stretchr/testify`, `github.com/go-playground/validator/v10`.

A4. Crea un `Makefile` root con target:
    - `make build-daemon` — compila il binario `maestrod` in `dist/maestrod`
    - `make build-control-plane` — sanity check Python (ruff + mypy + pytest)
    - `make test-unit` — esegue test unitari di entrambi
    - `make test-integration` — esegue test d'integrazione
    - `make test-e2e` — esegue test end-to-end con container Docker reali
    - `make dev` — avvia control plane in modalità sviluppo

A5. Configura linting minimo: `ruff` per Python, `go vet` + `golangci-lint`
    per Go. Aggiungi un pre-commit hook opzionale.

**Test gruppo A:**
- `make build-daemon` produce un binario eseguibile `dist/maestrod` che stampa
  `--version` correttamente.
- `cd control-plane && pytest --collect-only` non riporta errori di import.
- `cd daemon && go vet ./...` passa.

### Gruppo B — Schema e parser YAML

B1. In `control-plane/app/config/schema.py`, definisci modelli Pydantic per
    l'intero sottoinsieme di schema sopra. Usa `Field` con alias e
    `model_validator` per regole non-strutturali (es. `run.type` deve
    combaciare con la capacità del componente).

B2. In `control-plane/app/config/loader.py`, funzione
    `load_deployment(path: Path) -> DeploymentSpec` che:
    - Legge YAML.
    - Normalizza (applica defaults impliciti).
    - Restituisce oggetto tipizzato.

B3. In `control-plane/app/config/validator.py`:
    - `validate(spec) -> list[ValidationError]` con controlli di integrità
      referenziale e rilevamento cicli in `depends_on`.

B4. In `control-plane/app/config/renderer.py`:
    - `render_component(spec, component_id, context) -> RenderedComponent`
      che produce un oggetto con `build_steps`, `config_files` già
      renderizzati via Jinja2 (contenuto dei template), e `run_spec`.

**Test unitari (`control-plane/tests/unit/test_config_parser.py`):**
- Parsa `examples/deployment.yaml`; tutti i campi attesi popolati.
- File con `api_version` errato → errore.
- `depends_on` con componente inesistente → errore di validazione
  con path del campo.
- Ciclo `A depends_on B, B depends_on A` → errore.
- Rendering di un template con `{{ hosts['host1'].address }}` → produce la
  stringa corretta.
- Variabile non risolvibile → errore con nome della variabile.

**Coverage target gruppo B:** ≥ 90% sui moduli `config/`.

### Gruppo C — Daemon: struttura, store e WS client

C1. `daemon/cmd/maestrod/main.go`:
    - Flag: `--config /etc/maestrod/config.yaml`, `--version`, `--debug`.
    - Legge config (endpoint control plane, token, host_id, working_dir).
    - Avvia client WS, state store, metrics collector.

C2. `daemon/internal/config/`: parsing del YAML di configurazione del
    daemon.

C3. `daemon/internal/state/`:
    - Interfaccia `Store` con metodi: `GetComponent(id)`, `UpsertComponent`,
      `ListComponents`, `DeleteComponent`, `AppendHistory`, `GetHistory`.
    - Implementazione SQLite con migrazione automatica all'avvio.

C4. `daemon/internal/ws/`:
    - `Client` con handshake, loop di read/write, heartbeat, riconnessione
      con backoff esponenziale + jitter.
    - Dispatch dei messaggi verso handler registrati per `type`.
    - Formato messaggio conforme a `docs/protocol.md`.

**Test unitari Go** (con `go test ./...`):
- `state/sqlite_test.go`: CRUD componenti, history, migrazione.
- `ws/client_test.go`: handshake con server WS mock, riconnessione dopo
  drop, timeout heartbeat.
- `config/parse_test.go`: parsing YAML daemon config.

### Gruppo D — Daemon: runner

D1. `daemon/internal/runner/runner.go`:
    ```go
    type Runner interface {
        Deploy(ctx, ComponentDeploy) (*DeployResult, error)
        Start(ctx, id string) error
        Stop(ctx, id string, graceful time.Duration) error
        Status(ctx, id string) (Status, error)
        Logs(ctx, id string, lines int, since time.Time) ([]string, error)
    }
    ```

D2. `daemon/internal/runner/systemd.go`:
    - Genera unit file da template.
    - Usa `systemctl` via `os/exec` (niente dbus in Fase 1, ma prepara
      l'interfaccia per sostituirlo).
    - Directory di deploy: `/opt/maestro/<component_id>/`.
    - Unit file in `/etc/systemd/system/maestro-<component_id>.service`.

D3. `daemon/internal/runner/docker.go`:
    - Usa il client Docker ufficiale Go (`docker/docker`).
    - Gestisce create/start/stop/remove di container.
    - Pull image se necessario.

D4. Healthchecker condiviso (`daemon/internal/runner/healthcheck.go`):
    - Tipi `http`, `tcp`, `command`.
    - Retry + timeout configurabili.

**Test unitari Go:**
- `systemd_test.go`: generazione unit file con vari spec; mock di
  `exec.CommandContext` via interfaccia iniettabile.
- `docker_test.go`: mock del client Docker (interfaccia sottile sopra il
  client ufficiale).
- `healthcheck_test.go`: HTTP con server di test, TCP con listener, command
  con `echo`.

**Test integrazione daemon (`daemon/test/integration/`):**
- `docker_runner_test.go`: deploy reale di `nginx:alpine`, verifica status,
  healthcheck HTTP su `/`, teardown. Skippato se `DOCKER_AVAILABLE=0`.
- `systemd_runner_test.go`: skippato se non in un host con systemd.
  Quando eseguito, deploya uno script shell minimo come servizio e
  verifica start/stop.

### Gruppo E — Control plane: orchestrator e API

E1. `control-plane/app/ws/hub.py`:
    - `Hub` mantiene registry di daemon connessi per `host_id`.
    - `send_request(host_id, message) -> awaitable[response]`.
    - `subscribe_events(host_id, handler)` per eventi asincroni.
    - Gestione timeout richieste.

E2. `control-plane/app/ws/protocol.py`:
    - Modelli Pydantic per tutti i messaggi supportati.
    - Helper `make_message(type, payload) -> Message`.

E3. `control-plane/app/orchestrator/engine.py`:
    - `Engine.deploy(deployment_spec, target=...)`:
      1. Carica stato corrente da ogni daemon coinvolto.
      2. Calcola diff (vedi E4).
      3. Ordina componenti per topologia.
      4. Per ogni componente da (ri)deployare:
         - Prepara payload (clone git sul control plane, pack in tarball,
           pull docker info, etc.).
         - Invia `request.deploy` al daemon.
         - Attende risposta entro timeout.
         - In caso di errore, ferma il rollout e ritorna.
    - `Engine.get_state(project_id)`: aggrega stato da tutti i daemon.

E4. `control-plane/app/orchestrator/diff.py`:
    - `compute_diff(desired_spec, observed_state) -> Diff` con liste di
      componenti `to_create`, `to_update`, `to_remove`, `unchanged`.

E5. `control-plane/app/api/`:
    - `POST /api/config/validate` — body: YAML raw; valida e ritorna errori.
    - `POST /api/config/apply` — body: YAML raw; salva e triggera deploy.
    - `GET /api/state` — stato corrente aggregato.
    - `POST /api/components/{id}/start|stop|restart`.
    - `GET /api/components/{id}/logs?lines=200`.
    - `GET /api/hosts` — lista host connessi.

E6. `control-plane/app/main.py`:
    - FastAPI app, startup event che avvia l'hub WS e l'engine.
    - Mount della UI statica su `/`.

**Test unitari:**
- `test_hub.py`: invio richiesta, risposta, timeout, disconnessione
  durante richiesta, eventi asincroni ricevuti dai subscriber.
- `test_diff.py`: diff corretto per componente nuovo, modificato,
  invariato, rimosso.
- `test_orchestrator_unit.py`: con hub mock, verifica ordine topologico e
  gestione errori.
- `test_api.py`: test di ogni endpoint con `httpx.AsyncClient` + daemon
  simulato da un task che accetta WS fake.

### Gruppo F — MCP server e UI minimale

F1. `control-plane/app/mcp/server.py`:
    - Server MCP (usa l'SDK Python ufficiale). Registra tool:
      - `list_hosts`
      - `get_state`
      - `validate_config` (input: yaml string)
      - `apply_config` (input: yaml string)
      - `deploy` (input: project_id, optional component_id)
      - `start`, `stop`, `restart` (input: component_id)
      - `tail_logs` (input: component_id, lines)
    - Ogni tool ritorna oggetti JSON strutturati.
    - Errori con codice classificato + suggested_fix.

F2. Registra il server MCP come sottotask dell'app FastAPI (stdio e/o HTTP
    SSE per sviluppo locale).

F3. `control-plane/web/`:
    - `index.html` con HTMX. Tre sezioni: Dashboard, YAML Editor, Logs.
    - Editor YAML: textarea + bottone Validate + bottone Apply.
    - Dashboard: tabella host/componenti con status e metriche base,
      auto-refresh via HTMX polling ogni 5s.
    - Logs: viewer per componente selezionato.

F4. `skill/SKILL.md`: skill skeleton documentando i verbi MCP e il flusso
    tipico (validate → diff → apply → watch).

**Test:**
- `test_mcp_tools.py`: per ogni tool, chiamata con input valido/invalido e
  verifica output strutturato.
- `test_web_smoke.py` (opzionale): avvia l'app e fa GET `/`, `/healthz`.

### Gruppo G — Installer e packaging minimo

G1. `scripts/install-daemon.sh`:
    - Scarica il binario `maestrod` dal percorso indicato (o da un path locale).
    - Crea `/etc/maestrod/config.yaml` da template.
    - Installa e avvia `maestro-daemon.service` systemd.
    - Uso: `sudo ./install-daemon.sh --endpoint wss://cp/ws/daemon --token XXX --host-id api-server`.

G2. `control-plane/Dockerfile` per eseguire il control plane in container.

G3. `docker-compose.yml` root che avvia control plane + un daemon
    containerizzato di esempio (il daemon in container gira soprattutto per
    i test e-to-e; in produzione resta systemd su host).

### Gruppo H — Test end-to-end

Scrivi test e2e in `tests/e2e/` usando `pytest` + Docker.

H1. `test_full_deploy.py`:
    - Avvia control plane + un daemon (in container) via docker-compose.
    - POST `/api/config/apply` con `fixtures/deployment-simple.yaml`.
    - Attende completamento (polling su `/api/state`).
    - Verifica che il componente (nginx) sia `running` e che una `curl` al
      port pubblicato ritorni 200.

H2. `test_idempotency.py`:
    - Stesso apply due volte → la seconda è no-op (verifica via timing o
      via log del control plane).

H3. `test_component_lifecycle.py`:
    - Apply → stop → verifica stopped → start → verifica running →
      restart → verifica running.

H4. `test_reconnect.py`:
    - Kill del daemon container → verifica che il control plane veda
      l'host offline.
    - Restart del daemon → verifica riconnessione e recupero dello stato.

H5. `test_mcp_integration.py`:
    - Client MCP Python si collega al server, esegue il flusso completo
      (validate, apply, deploy, get_state) e asserisce i risultati.

## 5. Fixture di esempio

Crea i seguenti file fixture (se non esistono già):

- `tests/fixtures/deployment-simple.yaml`: un host, un componente nginx.
- `tests/fixtures/deployment-multicomponent.yaml`: un host, due componenti
  (nginx + redis).
- `tests/fixtures/bad-cycle.yaml`: ciclo in `depends_on`, per test di
  validazione.
- `tests/fixtures/bad-ref.yaml`: `depends_on` a componente inesistente.

## 6. Suite di accettazione della Fase 1

Questi test **devono tutti passare** perché la Fase 1 sia completa. Se
falliscono, itera finché non passano.

### Accettazione 1 — Bootstrap

```bash
make build-daemon
make build-control-plane
docker compose up -d
# attendere 10s
curl -sf http://localhost:8000/healthz
curl -sf http://localhost:8000/api/hosts | jq '.|length' # >= 1
```

Atteso: il control plane è up, almeno un daemon risulta connesso.

### Accettazione 2 — Deploy nginx e verifica

```bash
cat tests/fixtures/deployment-simple.yaml | \
  curl -sf -X POST http://localhost:8000/api/config/apply \
    -H 'content-type: application/yaml' --data-binary @-

# polling fino a completamento
for i in {1..30}; do
  state=$(curl -sf http://localhost:8000/api/state | jq -r '.components[0].status')
  [[ "$state" == "running" ]] && break
  sleep 2
done
[[ "$state" == "running" ]]

# verifica che il servizio risponda
curl -sf http://localhost:18080 # porta mappata dal componente
```

### Accettazione 3 — Idempotenza

Applicare la stessa config di nuovo. L'`/api/state` deve riportare
`unchanged: true` per tutti i componenti. Nessun restart dei container.

### Accettazione 4 — Validazione

```bash
cat tests/fixtures/bad-cycle.yaml | \
  curl -s -X POST http://localhost:8000/api/config/validate \
    -H 'content-type: application/yaml' --data-binary @- | \
  jq '.errors | length' # > 0
```

### Accettazione 5 — MCP

Uno script Python in `tests/e2e/test_mcp_integration.py` che si collega al
server MCP, invoca `validate_config`, poi `apply_config`, poi `get_state`
e asserisce che il componente sia running.

### Accettazione 6 — Test suites

```bash
make test-unit        # tutti green
make test-integration # tutti green
make test-e2e         # tutti green
```

### Accettazione 7 — Resilienza connessione

- Killa il container del daemon (`docker kill <daemon>`).
- Entro 10s, `/api/hosts` riporta lo stato `offline`.
- Riavvia il container (`docker start`).
- Entro 30s, l'host torna `online` con lo stato componenti coerente.

### Accettazione 8 — Consumo di token (qualitativo)

Manualmente (o con un piccolo benchmark script):
- Chiama `get_state` via MCP. La risposta JSON deve essere ≤ 4 KB per un
  progetto con 3 componenti.
- `tail_logs` con `lines: 100` deve ritornare SOLO quelle righe, non di più.
- Tutti gli errori devono includere `code` e `suggested_fix` quando
  applicabile.

## 7. Documenti da produrre alla fine

- `docs/phase-1-completion.md`: sommario di cosa è stato costruito,
  eventuali deviazioni dal piano, e note operative per installare/usare
  la Fase 1.
- Aggiornamento di `README.md` con una sezione "Quick start".

## 8. Cose che l'agente **non** deve fare in Fase 1

- Non implementare Kubernetes.
- Non scrivere un credential vault cifrato (usa un semplice file YAML in
  chiaro per ora; la cifratura è Fase 2).
- Non implementare webhook Git.
- Non implementare hot deploy / blue_green / canary.
- Non implementare multi-tenancy o autenticazione utente sulla UI (la UI
  Fase 1 è per localhost o reti fidate).
- Non ottimizzare prematuramente (es. proto-buf invece di JSON): restiamo
  su JSON.

## 9. Criteri di qualità

- Copertura test ≥ 80% sul codice Python, ≥ 70% sul codice Go.
- Nessun warning di `ruff` o `go vet`.
- Tempo medio di deploy di un componente Docker semplice ≤ 30 secondi in
  condizioni normali (immagine già pullata).
- Tempo di riconnessione dopo drop ≤ 10 secondi.
- Messaggi di errore chiari, con `code` e `suggested_fix` dove appropriato.
