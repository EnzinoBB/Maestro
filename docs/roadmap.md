# Roadmap di sviluppo

Il progetto è pianificato in tre fasi incrementali. Ogni fase produce un
artefatto utilizzabile ed è documentata da un file dedicato (`phase-N-*.md`)
pensato per essere dato in pasto a un agente AI insieme al codice prodotto
dalle fasi precedenti, consentendo sviluppo iterativo con basso consumo di
token.

## Riassunto delle fasi

| Fase | Nome | Obiettivo | Durata stimata |
|------|------|-----------|----------------|
| 1 | Prototipo | Slice verticale funzionante: deploy reale di un componente da YAML | 1-2 settimane |
| 2 | Beta | Funzionalità complete: Git-sync, test, rollback, credential vault, hot deploy, MCP completo | 2-3 settimane |
| 3 | Produzione | Kubernetes, osservabilità avanzata, HA, CLI, packaging, documentazione utente | 2-3 settimane |

## Fase 1 — Prototipo

**In scope:**
- YAML schema v1 (sottoinsieme), parser e validator.
- Daemon Go con runner systemd e Docker, store SQLite, WebSocket client.
- Control plane Python con FastAPI, WebSocket hub, orchestrator sequenziale,
  REST API per la UI.
- UI web minimale (HTMX, una pagina: dashboard + editor YAML + log).
- Server MCP con i verbi essenziali.
- Skill skeleton.
- Test unitari di entrambe le parti + test d'integrazione end-to-end che
  deployano un componente Docker reale.

**Out of scope:**
- Kubernetes, Git-sync automatico, test framework per componenti, credential
  vault avanzato, rollout canary/blue-green, hot deploy.

**Deliverable**: repository eseguibile con `docker compose up` del control
plane + `rcad` installabile su un host Linux; deployment end-to-end di
`examples/deployment.yaml` funzionante.

## Fase 2 — Beta

**Aggiunge:**
- Git-sync component (webhook + polling) con trigger automatico su commit.
- Test framework per componenti (pre/post deploy, unit/integration/smoke).
- Credential vault con backend file cifrato e interfaccia pluggable.
- Rollback automatico su test/healthcheck falliti.
- Hot deploy e blue_green per componenti che lo supportano.
- Rollout canary.
- UI web ricca (React) con streaming log, grafici metriche, storico deploy.
- MCP server con tutti i verbi.
- Skill completa con flussi decisionali documentati.

**Deliverable**: sistema usabile quotidianamente per progetti reali
multi-componente.

## Fase 3 — Produzione

**Aggiunge:**
- Runner Kubernetes (Deployment/StatefulSet/Helm).
- Osservabilità: Prometheus metrics, tracing OpenTelemetry, audit log
  strutturato.
- High availability del control plane (PostgreSQL, cluster di istanze con
  leader election).
- mTLS daemon ↔ control plane.
- CLI `rca` per operazioni da terminale.
- Pacchettizzazione: Docker image del control plane su registry, .deb/.rpm
  del daemon, chart Helm opzionale.
- Documentazione utente completa (guida installazione, tutorial, API reference).
- RBAC di base per UI e MCP (utenti, ruoli, permessi).

**Deliverable**: prodotto pronto per installazione presso un'organizzazione.

## Regole di transizione fra fasi

Una fase si considera completa quando:

1. Tutti i task del documento di fase sono risolti.
2. Tutti i test di accettazione della fase passano.
3. Il sistema si avvia e risponde ai comandi documentati nello stesso file.
4. La documentazione di fase è aggiornata per riflettere eventuali
   divergenze rispetto al piano iniziale.

Se una scelta tecnica del piano risulta errata durante l'implementazione,
l'agente ha mandato di deviare documentando la deviazione e le motivazioni
in un file `docs/deviations.md`.

## Come dare i documenti in pasto a un agente

Per la **Fase 1**: fornire all'agente:
- `README.md`
- `docs/architecture.md`
- `docs/yaml-schema.md`
- `docs/protocol.md`
- `docs/phase-1-prototype.md`
- `examples/deployment.yaml`
- `skill/SKILL.md`

L'agente procederà dall'albero di directory vuoto al completamento della
Fase 1.

Per la **Fase 2**: fornire all'agente il repository come risulta al termine
della Fase 1, più:
- `docs/phase-2-beta.md`

Per la **Fase 3**: fornire il repository al termine della Fase 2, più:
- `docs/phase-3-production.md`

Ogni documento di fase è volutamente autosufficiente: elenca prerequisiti,
task, criteri di accettazione e test da eseguire.
