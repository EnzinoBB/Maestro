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

### 1. Avvia il control plane (una macchina)

```bash
curl -fsSL https://github.com/EnzinoBB/Maestro/releases/latest/download/install-cp.sh \
  | sudo bash
```

L'installer verifica/installa Docker, avvia il container, attende l'healthcheck.
Recupera il token generato al primo avvio:

```bash
docker compose -f /opt/maestro-cp/docker-compose.yml logs control-plane \
  | grep -A1 "GENERATED MAESTRO DAEMON TOKEN"
```

UI: `http://<cp-host>:8000`.

### 2. Installa un daemon (su ciascun host target)

Se il CP ha un dominio raggiungibile dall'host target:

```bash
curl -fsSL https://<cp-host>/install-daemon.sh | sudo bash -s -- \
  --host-id api-01 --token <TOKEN>
```

Oppure da GitHub (con `--cp-url` esplicito):

```bash
curl -fsSL https://github.com/EnzinoBB/Maestro/releases/latest/download/install-daemon.sh \
  | sudo bash -s -- --cp-url https://<cp-host> --host-id api-01 --token <TOKEN>
```

Supportato: Linux x86_64/arm64 (systemd), macOS x86_64/arm64 (launchd).

Il daemon scarica il binario dal CP (fallback GitHub), verifica lo SHA256,
installa il service systemd/launchd e si connette al CP.

### 3. Deploya

Apri la UI, incolla un `deployment.yaml` (vedi `examples/deployment.yaml`),
premi **Validate**, **Diff**, poi **Apply**. Oppure via API:

```bash
curl -X POST http://<cp-host>:8000/api/config/apply \
  -H 'content-type: text/yaml' \
  --data-binary @examples/deployment.yaml
```

### Per contributori — build da sorgente

```bash
make build-all              # cross-compile maestrod (linux+darwin × amd64+arm64)
make build-image            # build locale dell'immagine CP
make build-control-plane    # sanity check del CP Python
```

Per lo sviluppo locale del CP senza Docker:

```bash
cd control-plane
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/uvicorn app.main:app --port 8000 --reload
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
