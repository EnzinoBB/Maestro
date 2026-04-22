# Maestro

Orchestratore di deployment multi-host guidato da un agente AI, pensato per essere
più semplice di Ansible sui casi comuni e per ridurre al minimo il consumo di
token quando un agente LLM pilota le operazioni.

## Cosa fa

Un file YAML descrive hosts, componenti e assegnazioni. Un control plane Python
legge lo YAML e coordina dei daemon Go residenti su ciascun host target, che
conoscono lo stato locale, eseguono i deploy, riportano metriche e log.
Un agente AI (Claude o altro) interagisce col sistema via MCP, guidato da una
skill che codifica le convenzioni d'uso.

## Stato attuale

**Fase 1 (Prototipo) completata.** Il sistema è funzionale end-to-end su
Linux/systemd/Docker. Vedi `docs/phase-1-completion.md` per lo status
report completo; i piani Fase 2/3 sono in `docs/phase-2-beta.md` e
`docs/phase-3-production.md`.

## Quick start

### 1. Build

```bash
make build-linux          # produce dist/maestrod-linux-amd64
make build-control-plane  # sanity check del CP Python
```

### 2. Avvia il control plane

Locale (per sviluppo):

```bash
cd control-plane
python -m venv .venv
.venv/bin/pip install fastapi 'uvicorn[standard]' pydantic pyyaml jinja2 \
    sqlalchemy aiosqlite websockets httpx click mcp
.venv/bin/uvicorn app.main:app --port 8000
```

Oppure via container:

```bash
cp docker-compose.example.yml docker-compose.yml    # edit secrets inside
docker compose up -d
# UI: http://localhost:8000
```

> `docker-compose.yml`, `credentials.yaml` e `/etc/maestrod/config.yaml` contengono
> segreti e sono `.gitignore`-d. Copia i file `*.example` in `scripts/` o nella
> root del progetto e sostituisci i placeholder `CHANGE_ME` con i tuoi valori.

### 3. Installa un daemon

Su ciascun host Linux target:

```bash
scp dist/maestrod-linux-amd64 user@host:/tmp/maestrod
scp scripts/install-daemon.sh user@host:/tmp/
ssh user@host "sudo /tmp/install-daemon.sh \
  --endpoint ws://<CP_HOST>:8000/ws/daemon \
  --host-id api-server \
  --binary /tmp/maestrod"
```

### 4. Deploya

Apri la UI (`http://<CP_HOST>:8000`), incolla un `deployment.yaml`
(vedi `examples/deployment.yaml`), premi **Validate**, **Diff**, poi
**Apply**. Oppure via API:

```bash
curl -X POST http://<CP_HOST>:8000/api/config/apply \
  -H 'content-type: text/yaml' \
  --data-binary @examples/deployment.yaml
```

## Struttura del repository

```
.
├── docs/                  Documentazione di architettura, schema, roadmap
├── control-plane/         Servizio Python (FastAPI + WebSocket hub + MCP)
│   ├── app/               Codice applicativo
│   ├── tests/             Test unitari e d'integrazione
│   └── web/               UI web per l'utente (HTMX)
├── daemon/                Agente host in Go (maestrod)
│   ├── cmd/maestrod/      Entry point
│   ├── internal/          Pacchetti interni
│   └── test/integration/  Test d'integrazione del daemon
├── tests/                 Test end-to-end cross-componente
│   ├── e2e/
│   └── fixtures/
├── skill/                 Skill per agenti che usano l'MCP del CP
├── examples/              Esempi di deployment.yaml
├── scripts/               Script di installazione
└── dist/                  Build artifacts (non versionato)
```

## Documenti chiave

| File | Scopo |
|------|-------|
| `docs/architecture.md` | Architettura generale, scelte tecniche, modello di stato |
| `docs/yaml-schema.md` | Schema formale del file `deployment.yaml` |
| `docs/protocol.md` | Protocollo WebSocket control plane ↔ daemon |
| `docs/roadmap.md` | Panoramica delle tre fasi di sviluppo |
| `docs/phase-1-completion.md` | Report Fase 1: cosa è stato costruito + criteri soddisfatti |
| `docs/phase-1-prototype.md` | Istruzioni originali per la Fase 1 |
| `docs/phase-2-beta.md` | Istruzioni per la Fase 2 |
| `docs/phase-3-production.md` | Istruzioni per la Fase 3 |

## Test

```bash
make test-unit         # unit Python + Go
make test-integration  # integration Go (richiede docker)
make test-e2e          # e2e cross-componente (richiede docker)
```

## Licenza

Apache-2.0.
