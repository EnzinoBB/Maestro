# Fase 1 — Completion Report

Questa Fase 1 (Prototipo) produce uno **slice verticale** completo: un utente
carica un `deployment.yaml`, preme "Apply" nella UI (o chiama l'API) e il
control plane ordina a un daemon `maestrod` di deployare un componente Docker
reale su un host Linux. Lo stesso flusso è esposto via MCP-compatible tools.

## 1. Cosa è stato costruito

### Control plane Python (`control-plane/`)

| Modulo | Responsabilità |
|--------|----------------|
| `app/config/` | schema Pydantic, loader YAML, validator (integrità referenziale + cicli), renderer Jinja2 |
| `app/ws/hub.py` | Registry di daemon connessi, request/response con `id`, timeout, heartbeat |
| `app/orchestrator/` | Engine sequenziale con toposort delle dipendenze + diff desired/observed |
| `app/api/router.py` | Endpoint REST (`/api/healthz`, `/api/hosts`, `/api/config/{validate,diff,apply}`, `/api/state`, `/api/components/{id}/{start,stop,restart}`, `/api/components/{id}/logs`, `/api/deploys`) |
| `app/api/ui.py` | Frammenti HTMX della UI |
| `app/mcp/tools.py` | Implementazioni strutturate dei verbi MCP (con `code`/`suggested_fix`) |
| `app/mcp/server.py` | Server MCP stdio che inoltra via HTTP al control plane |
| `app/storage.py` | SQLite: ultima config applicata + history |
| `web/index.html` | UI HTMX: dashboard, editor YAML, history |

### Daemon Go (`daemon/`)

| Modulo | Responsabilità |
|--------|----------------|
| `cmd/maestrod/main.go` | Entry point con flag `--config`, `--version`, `--debug` |
| `internal/config/` | Caricamento `config.yaml` (+ env override) |
| `internal/state/` | Store SQLite (tabelle `components`, `history`) con migrazione |
| `internal/ws/` | Client WebSocket Gorilla, handshake, reconnect con backoff+jitter, heartbeat 15s |
| `internal/runner/runner.go` | Interfaccia `Runner` (Deploy/Start/Stop/Status/Logs) |
| `internal/runner/docker.go` | Runner Docker via CLI (pull/run/stop/logs/inspect) |
| `internal/runner/systemd.go` | Runner systemd: renderizza unit file, scrive config, `systemctl enable/restart` |
| `internal/runner/healthcheck.go` | Healthcheck http/tcp/command con retry/interval/timeout |
| `internal/orchestrator/` | Wire WS ↔ state ↔ runner; handler per `request.*`; persiste ContainerName/Hash |
| `internal/metrics/` | Ticker `event.metrics` periodico |

### Pacchettizzazione

- `Makefile` root con target `build-linux`, `build-control-plane`, `test-unit`, `test-integration`, `test-e2e`, `dev`, `clean`, `lint`.
- `control-plane/Dockerfile` + `docker-compose.yml` per avviare il CP in container.
- `scripts/install-daemon.sh` installa `maestrod` come unit systemd.
- `dist/maestrod-linux-amd64` prodotto con `make build-linux` (binario ~11 MB, statico, CGO=0).

### Skill

`skill/SKILL.md` contiene lo skeleton che guida l'agente (flusso
validate → diff → confirm → apply → watch → verify) e la tassonomia errori.

## 2. Fixture e test

- `tests/fixtures/deployment-simple.yaml` — single-host nginx, Fase 1.
- `tests/fixtures/deployment-multicomponent.yaml` — redis + nginx.
- `tests/fixtures/deployment-multihost.yaml` — redis su host1, nginx su host2.
- `tests/fixtures/bad-cycle.yaml` — ciclo A↔B.
- `tests/fixtures/bad-ref.yaml` — host/componente mancanti.
- `tests/e2e/test_mcp_integration.py` — round-trip MCP-equivalente (hosts → validate → apply → state → logs → stop/start/restart → idempotency).

**Python unit (17 test)**
- `test_config_parser.py` — parsing, validazione, render (vars, source image fallback, errori).
- `test_diff.py` — hash stabile; create/update/unchanged/remove.
- `test_hub.py` — handshake + request/response + list_hosts.
- `test_api.py` — healthz, validate OK/KO, apply senza daemon, dry_run.

**Go unit (5 pacchetti)**
- `config` — parsing + env override + validate.
- `state` — CRUD componenti, history, delete, migrazione colonna.
- `ws` — handshake completo + request dal server + reply da handler.
- `runner` — healthcheck http/tcp/command, render unit systemd, writeConfigFiles.

Tutti i test passano: `go test ./... → ok` su tutti i pacchetti, `pytest
tests/unit → 17 passed`.

## 3. Risultati sui test di accettazione

Eseguiti contro due host Ubuntu reali (server1 = Ubuntu 24.04,
server2 = Ubuntu 20.04, entrambi con utente `deploy` + sudo, accessibili via
SSH). Il control plane è girato su server1; i daemon su entrambi i server.
IP/hostname sono stati anonimizzati in questo report.

| # | Criterio | Esito |
|---|----------|-------|
| A1 | Bootstrap: CP up + `/api/hosts` popolato | ✅ 2 host online |
| A2 | Deploy nginx da `deployment-simple.yaml` | ✅ `/18080 → 200`, container `maestro-test-web` running |
| A3 | Idempotenza: re-apply = `unchanged` | ✅ `0 ms`, 0 restart |
| A4 | Validazione: `bad-cycle.yaml` → errori strutturati con path | ✅ `components` + "dependency cycle" |
| A5 | MCP round-trip (validate/apply/state/start/stop/restart/logs/idempotency) | ✅ 9/9 step |
| A6 | `go test ./...` + `pytest tests/unit` verdi | ✅ |
| A7 | Kill daemon host2 → host2 `online=false` entro 2 s; restart → `online=true` entro 4 s | ✅ |
| A8 | `get_state` JSON < 4 KB per 3 componenti; errori con `code`/`suggested_fix` | ✅ |

Extra:
- **Multi-host**: `deployment-multihost.yaml` deploya redis su host1 e nginx
  su host2 rispettando `depends_on_hosts`. Entrambi i container rispondono.
- **Lifecycle**: stop/start/restart su container già deployato (risolto il
  bug di reconstruction del `container_name` dallo store).

## 4. Deviazioni dal piano

Minime:

1. **MCP server**: in Fase 1 la skeleton è un forwarder HTTP verso il CP
   invece di un binding in-process. Mantiene il server MCP stateless e
   semplifica il test integrato (tutti i tool passano per l'HTTP API).
   La transizione a server embedded è triviale in Fase 2.
2. **SCP/SFTP**: non è codice di progetto, ma per sviluppo serve `ssh-key`
   auth: il plugin paramiko SFTP fallisce in alcune configurazioni; gli
   script di installazione usano `scp` nativo dopo registrazione chiave.
3. **Docker runner**: usa `docker` CLI anziché il client Go ufficiale, per
   non linkare 40+ MB di dipendenze. L'interfaccia è pronta per lo swap.
4. **Credentials**: niente vault in Fase 1 (solo `vars` + file `.env`
   template). `secrets` nello YAML viene parsato ma ignorato. Fase 2 porta il backend file cifrato.

## 5. Guida al prossimo agente

Per proseguire in Fase 2, leggi:

- `docs/phase-2-beta.md` — prompt autosufficiente.
- `docs/architecture.md` — invariato.
- `docs/protocol.md` — aggiungerà messaggi `request.tests.run`, `request.rollback`, streaming log.

Stato noto del repository al termine della Fase 1:

- Il daemon mantiene history di 10 hash per componente (usato in Fase 2 per rollback).
- Lo store daemon ha già `ContainerName` / `UnitName` per riconduzione sicura.
- Il server MCP è un forwarder; quando si implementa il vero binding in-process, basta sostituire `mcp/server.py` mantenendo gli stessi tool definiti in `mcp/tools.py`.

## 6. Note operative

### Start rapido locale (solo CP)

```bash
cd control-plane
python -m venv .venv && .venv/bin/pip install -e .
.venv/bin/uvicorn app.main:app --reload --port 8000
```

### Installazione daemon su host Linux

```bash
# build
make build-linux

# sulla macchina target (con sudo):
scp dist/maestrod-linux-amd64 user@host:/tmp/
scp scripts/install-daemon.sh user@host:/tmp/
ssh user@host "chmod +x /tmp/install-daemon.sh && sudo /tmp/install-daemon.sh \
  --endpoint ws://<cp-address>:8000/ws/daemon \
  --host-id <host-id> \
  --binary /tmp/maestrod-linux-amd64"
```

### Docker compose stack

```bash
docker compose up -d
# Il CP è su http://localhost:8000
# Aggiungi un daemon installando maestrod su un host Linux.
```
