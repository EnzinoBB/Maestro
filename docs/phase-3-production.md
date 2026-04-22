# Fase 3 — Produzione

> **Istruzioni per l'agente che legge questo documento.**
> Presuppone che la Fase 2 sia completa e verificata. Prima di iniziare,
> leggi:
> - `docs/architecture.md`
> - `docs/yaml-schema.md` (campi Fase 3 — Kubernetes)
> - `docs/protocol.md`
> - `docs/phase-1-completion.md` e `docs/phase-2-completion.md`
> - Questo documento
>
> **Non deve esserci regressione**: esegui l'intera suite di accettazione
> delle Fasi 1 e 2 come primo passo e come passo finale.

## 1. Obiettivo della Fase 3

Portare il sistema da beta a stato "installabile presso un'organizzazione
con fiducia": aggiungere Kubernetes, osservabilità, sicurezza di livello
produttivo, HA, CLI, packaging e documentazione utente.

**In scope:**
- Runner Kubernetes (Deployment, StatefulSet, Helm).
- Metriche Prometheus esposte dal control plane e dai daemon.
- Tracing OpenTelemetry con propagazione fra control plane e daemon.
- Audit log strutturato di tutte le azioni umane e degli agenti.
- Migrazione a PostgreSQL del control plane (con path di upgrade da SQLite).
- High Availability: più istanze del control plane dietro un LB, leader
  election per l'orchestrator, sessioni WS "sticky" o rebalanciabili.
- mTLS daemon ↔ control plane con CA interna.
- Autenticazione utente sulla UI e sull'API (OIDC + API token), RBAC
  (ruoli: admin, operator, viewer) con permessi granulari su progetti.
- CLI `maestro` per operazioni da terminale (deploy, status, logs, tests,
  rollback).
- Packaging: Docker image del control plane pubblicata su registry, pacchetti
  .deb e .rpm del daemon, chart Helm del control plane opzionale.
- Documentazione utente: guide installazione, tutorial, reference API/MCP,
  troubleshooting.

## 2. Prerequisiti

- Repository al completamento Fase 2 con tutti i test passanti.
- Cluster Kubernetes di test disponibile (kind/k3d vanno bene).
- Account su un registry (Docker Hub, GHCR, ECR…) per le immagini.
- OpenSSL disponibile (per la CA interna).

## 3. Checklist operativa

### Gruppo A — Runner Kubernetes

A1. Nuovo tipo di host in `yaml-schema.md`:
    ```yaml
    hosts:
      k8s-prod:
        type: kubernetes
        kubeconfig_ref: vault://kube/prod
        context: production
        namespace: default
    ```

A2. Strategia architetturale: per i target Kubernetes, non c'è un daemon
    residente nel cluster. Il control plane instanzia un "K8s executor"
    che parla via API Kubernetes (client-go in un microservizio Go
    dedicato invocato dal control plane, oppure `kubernetes` Python client
    direttamente nel control plane). Valuta le due opzioni e scegli in
    base a dove è più naturale posizionare la logica; documenta la scelta
    in `phase-3-completion.md`.

A3. `components.<id>.run.type: kubernetes` supporta due sottoforme:
    - `manifest_template`: percorso a un template Jinja2 che produce uno o
      più manifest YAML. Il control plane renderizza, applica con
      `kubectl apply` (o API) e attende ready.
    - `helm`: chart path o reference, values inline o file. Il control
      plane usa `helm upgrade --install` via subprocess o Python SDK.

A4. `healthcheck` per target K8s: leggere `.status.readyReplicas` e
    confrontare con `spec.replicas`. Per StatefulSet, anche ordinamento.

A5. Rollback K8s:
    - Per manifest: reapply della versione precedente.
    - Per Helm: `helm rollback`.

A6. Logs: seguire i pod; aggregare log di tutti i pod dello stesso
    Deployment nel tail restituito.

A7. Estensione dei messaggi protocol: il K8s executor non usa WebSocket
    (è in-process al control plane); ma espone la stessa interfaccia
    `Runner` in modo che l'orchestrator possa trattare K8s come un host
    qualunque.

**Test:**
- `test_k8s_runner_unit.py`: mock del client K8s, verifica traduzione
  manifest e gestione degli stati.
- `test_k8s_integration.py`: con kind cluster, deploy reale di un nginx
  Deployment (1 replica), healthcheck, rollback.

### Gruppo B — Osservabilità

B1. Metriche Prometheus esposte da control plane su `/metrics`:
    - `maestro_deploys_total{project, status}`
    - `maestro_deploy_duration_seconds{project, component}`
    - `maestro_hosts_connected`
    - `maestro_components_running{project, host}`
    - `maestro_rollbacks_total{reason}`
    - `maestro_ws_messages_total{direction, type}`
    - Histogram dei tempi di healthcheck.

B2. Metriche esposte dai daemon su `/metrics` (porta opzionale, disabilitata
    di default per non aprire porte in ingresso; attivabile via config):
    - Metriche di sistema per-componente già raccolte.
    - Metriche del daemon stesso (uptime, reconnections, queue depth).

B3. Tracing OpenTelemetry:
    - OTLP export configurabile.
    - Propagazione trace context attraverso i messaggi WebSocket (campo
      `trace_context` nell'envelope, opzionale).
    - Span principali: `config.validate`, `deploy.component`, `build`,
      `runner.start`, `healthcheck.wait`.

B4. Audit log strutturato in `audit.log` (file JSONL ruotato) con:
    - `actor_type: user|agent|system`
    - `actor_id`
    - `action`
    - `target`
    - `result: ok|error`
    - `ts`
    - `request_id`

B5. UI: nuova pagina "Observability" con link alle dashboard Prometheus
    esterne o embed di Grafana se disponibile. Audit log searchable via
    filtri.

**Test:**
- `test_metrics_exposition.py`: avvia control plane, fa delle operazioni,
  verifica che `/metrics` contenga le counter attese con incrementi
  corretti.
- `test_tracing_propagation.py`: genera un trace, verifica span sul
  control plane E sul daemon (collector mock).
- `test_audit_log.py`: ogni azione di un utente/agente produce record
  audit completo.

### Gruppo C — Migrazione a PostgreSQL

C1. Astrarre l'accesso DB tramite repository/DAO. Nessun uso diretto di
    SQLAlchemy sparso nei moduli (se c'è, rifattorizzare).

C2. Aggiungere backend PostgreSQL mantenendo il backend SQLite per dev.
    Selezione via config: `database.url: postgresql://...` o
    `sqlite:///...`.

C3. Script di migrazione `scripts/migrate-sqlite-to-postgres.py` che
    copia tutti i dati preservando lo schema.

C4. Alembic per le migrazioni schema in futuro; introdurlo adesso con la
    baseline corrente.

**Test:**
- `test_db_backends.py`: stessi test eseguiti sia su SQLite che su
  PostgreSQL (via testcontainers). Parità funzionale.
- `test_migration.py`: dump SQLite, migrate, verifica dati in PostgreSQL
  identici.

### Gruppo D — High Availability

D1. Control plane può girare con più istanze dietro un load balancer.
    Problemi da risolvere:
    - **Sessioni WS sticky o rebalanciabili**: scegli una strategia. La
      più semplice: ogni daemon è "di proprietà" di una specifica istanza
      (identificata via consistent hashing su `daemon_id` → instance_id);
      se l'istanza muore, il daemon riconnette e un altro nodo lo prende.
    - **Leader election per operazioni stateful**: usa un lease su DB
      (PostgreSQL advisory lock o tabella `leader_lease`). Solo il leader
      esegue git-sync poller globale, pulizie periodiche, scadenze.
    - **Condivisione stato**: tutto lo stato persistente va sul DB; niente
      in memoria locale se non cache.

D2. Health endpoint `/healthz` che considera l'istanza "ready" solo se:
    - DB raggiungibile.
    - Hub WS locale operativo.
    - (Per il leader) leader lease rinnovato.

D3. Graceful shutdown:
    - Smetti di accettare nuove richieste.
    - Chiudi WS e istruisci i daemon a riconnettersi.
    - Completa orchestrazioni in corso o cedi il lease.

**Test:**
- `test_ha_failover.py`: avvia 2 istanze + 1 daemon; ferma l'istanza che
  possiede la connessione; il daemon riconnette all'altra entro 10s;
  operazioni riprendono.
- `test_leader_election.py`: 2 istanze; una sola esegue i cron; su kill
  del leader, l'altra prende il lease entro 30s.

### Gruppo E — Sicurezza

E1. Mutual TLS daemon ↔ control plane:
    - Script `maestro ca init` che genera una CA privata e un certificato
      server per il control plane.
    - `maestro ca issue-daemon <host_id>` produce keypair firmato per un
      daemon.
    - **Canale di distribuzione del certificato al daemon: enrollment protocol**
      (vedi `docs/superpowers/specs/2026-04-22-installer-scripts-design.md`,
      Strato 2). Lo Strato 1 di quel design — implementato prima di Fase 2 —
      distribuisce al daemon un token condiviso via `POST /api/enroll/<token>/consume`;
      in Fase 3 la risposta del consume si estende da `{daemon_token}` a
      `{daemon_cert, daemon_key, ca_cert}`. L'admin usa lo stesso flusso UI
      "Add host" → enroll URL → `curl … | sudo bash` già disponibile.
    - Rotazione: il control plane può revocare (CRL in DB) e ri-emettere.
    - Fallback TLS + token rimane disponibile per retrocompatibilità,
      deprecato ma funzionante.

E2. Autenticazione utente sulla UI/API:
    - OIDC (supporto per un provider: Keycloak, Auth0, Google… —
      configurabile). Almeno una implementazione funzionante.
    - API token statici per integrazioni (MCP incluso). Token legati a
      ruolo.

E3. RBAC:
    - Ruoli predefiniti: `admin`, `operator`, `viewer`.
    - Permessi per risorsa: `project.read`, `project.write`,
      `component.deploy`, `component.rollback`, `vault.read`,
      `vault.write`, `audit.read`.
    - Autorizzazione enforced in ogni endpoint API e ogni tool MCP.

E4. Hardening:
    - Headers di sicurezza sulla UI (CSP, HSTS, X-Content-Type-Options).
    - Rate limiting base sugli endpoint pubblici.
    - Secrets mai loggati (allow-list dei campi loggabili).

E5. Enrollment backend (Strato 2 del design 2026-04-22):
    - Implementare tabella `host_enrollments` e migrations Alembic.
    - Implementare endpoint `POST /api/enrollments`,
      `GET /api/enrollments`, `DELETE /api/enrollments/<token>`,
      `GET /enroll/<token>`, `POST /api/enroll/<token>/consume`.
      Specifica completa in `docs/superpowers/specs/2026-04-22-installer-scripts-design.md`
      §5.1-5.2.
    - Estendere il consume response per includere
      `{daemon_cert, daemon_key, ca_cert}` oltre a (o al posto di)
      `daemon_token` (integra con E1).
    - UI `/hosts` con "Add host" modal (design §5.3).
    - `install-daemon.sh` aggiornato al flusso `curl …/enroll/<t> | sudo bash`
      come canale canonico (design §5.4, variante full).
    - Autorizzazione: `POST /api/enrollments` e `DELETE /api/enrollments/<t>`
      richiedono permesso `host.create` / `host.revoke` (integra con E3 RBAC).
    - Audit: ogni creazione / consume / revoca registrata (integra con B4).
    - Retrocompatibilità: installazioni esistenti che usano `--token`
      condiviso continuano a funzionare; nuovo canale enrollment è additivo.

**Test:**
- `test_mtls.py`: handshake con cert valido, handshake rigettato con cert
  non firmato dalla CA, revoca funzionante.
- `test_authn.py`: flusso OIDC con provider mock, token jwt validato.
- `test_rbac.py`: viewer non può deployare, operator può deployare ma non
  gestire vault, admin può tutto.
- `test_enrollment.py`: crea enrollment, consume happy path, token scaduto
  → 410, token già consumato → 410, `host_id_pattern` mismatch → 403,
  revoca funzionante, audit record completo.

### Gruppo F — CLI

F1. `maestro` binario (in Go per coerenza col daemon, oppure un wheel Python
    installabile — scegli e documenta). Comandi:
    - `maestro config validate <file>`
    - `maestro config apply <file>`
    - `maestro deploy [--component X]`
    - `maestro status [--project P]`
    - `maestro logs <component> [--follow] [--lines N]`
    - `maestro rollback <component> [--steps N]`
    - `maestro tests run <component> [--type unit|integration|smoke|all]`
    - `maestro vault set/get/list/delete`
    - `maestro hosts list`

F2. Configurazione via `~/.config/maestro/config.yaml` (endpoint control
    plane, token).

F3. Output: testo leggibile di default, `--json` per output strutturato.

**Test:**
- `test_cli_unit.py` (o `cli_test.go`): parsing argomenti, generazione
  richieste.
- `test_cli_e2e.py`: avvia stack, CLI esegue flusso base end-to-end
  equivalente all'UI.

### Gruppo G — Packaging e distribuzione

G1. CI (GitHub Actions o equivalente) che:
    - Esegue tutti i test.
    - Builda e pubblica `ghcr.io/<org>/maestro-control-plane:<version>`. **[Già implementato in Strato 1 del design 2026-04-22 come `ghcr.io/enzinobb/maestro-cp`.]**
    - Builda binari `maestrod` per linux/amd64 e linux/arm64, pubblica release.
      **[Già implementato in Strato 1; Strato 1 include anche darwin/amd64 e darwin/arm64.]**
    - Costruisce pacchetti `.deb` e `.rpm` per il daemon (via `nfpm` o
      `goreleaser`). **[Nuovo lavoro di Fase 3.]**

G2. Chart Helm in `deploy/helm/maestro-control-plane/` per installare il
    control plane su Kubernetes con PostgreSQL sidecar o connessione
    esterna.

G3. Template `docker-compose.prod.yml` come alternativa al chart.

G4. Script `scripts/upgrade.sh` che aggiorna installazioni esistenti
    (control plane in place + invocazione di daemon self-update se
    richiesto). **[Le primitive `install-cp.sh --upgrade` e
    `install-daemon.sh --upgrade` sono già disponibili dallo Strato 1 del
    design 2026-04-22; `upgrade.sh` in Fase 3 le orchestra su fleet.]**

### Gruppo H — Documentazione utente

H1. `docs/user/` contiene:
    - `installation.md` (single-node, HA, Kubernetes).
    - `quickstart.md` (da zero a primo deploy in 10 minuti).
    - `yaml-reference.md` (copertura completa dello schema, esempi).
    - `mcp-reference.md` (tutti i verbi MCP con esempi).
    - `api-reference.md` (OpenAPI generata + note).
    - `cli-reference.md`.
    - `troubleshooting.md` (guida agli errori comuni con `code` →
      soluzione).
    - `security.md` (modello di sicurezza, mTLS setup, rotazione
      certificati).
    - `observability.md` (metriche, tracing, audit).

H2. Sito documentazione statico generato con MkDocs o Docusaurus,
    pubblicato via CI.

### Gruppo I — Hardening della skill

I1. Aggiornare `skill/SKILL.md` con:
    - Sezione Kubernetes: come ragionare su target K8s vs Linux.
    - Sezione RBAC: come il permesso dell'agente può limitare le azioni
      disponibili.
    - Esempi di errori prodotti dalle nuove funzionalità con azioni
      raccomandate.
    - Pattern per operazioni cross-ambiente (dev/staging/prod) quando
      l'utente ha più progetti.

## 4. Fixture aggiuntive

- `tests/fixtures/deployment-k8s.yaml`
- `tests/fixtures/k8s-manifest-api.yaml.j2`
- `tests/fixtures/helm-chart-demo/` (chart minimale)
- `tests/fixtures/oidc-mock-config.yaml`

## 5. Suite di accettazione Fase 3

### Accettazione 1 — Regressione

Tutti i test di accettazione Fase 1 e Fase 2 passano.

### Accettazione 2 — Deploy Kubernetes

- Cluster kind attivo.
- `deployment-k8s.yaml` applicato.
- Deployment creato, pod ready, healthcheck positivo.
- Rollback funzionante.
- Logs leggibili via API/UI/CLI.

### Accettazione 3 — Osservabilità

- `curl /metrics` del control plane include tutte le metriche attese.
- Un deploy genera trace completo visibile nel collector di test.
- Audit log contiene record per ogni azione simulata.

### Accettazione 4 — HA

- Failover dimostrato (vedi test gruppo D).
- Leader election dimostrata.

### Accettazione 5 — Sicurezza

- mTLS enforced (rifiuta daemon senza cert valido).
- RBAC enforced (viewer non può deployare; test fallisce con 403).
- OIDC flow funziona con provider mock.
- Enrollment: dalla UI `/hosts` un admin crea un enroll URL, un host nuovo
  esegue il one-liner `curl …/enroll/<t> | sudo bash`, il daemon si registra
  con mTLS cert ricevuto via consume, appare in `GET /api/hosts` come `active`;
  un secondo tentativo con lo stesso token ritorna 410.

### Accettazione 6 — PostgreSQL

- Stack avviato con `DATABASE_URL=postgresql://...` invece di SQLite.
- Tutti i test di accettazione Fase 1 e 2 continuano a passare.

### Accettazione 7 — CLI

- Tutti i comandi CLI documentati eseguono correttamente.
- Output `--json` parsabile.
- Permessi rispettati (CLI con token viewer non può deployare).

### Accettazione 8 — Packaging

- Immagine Docker del control plane avviabile con `docker run`.
- Binario del daemon installabile da `.deb` su Ubuntu 22.04 test.
- Chart Helm installabile su kind con `helm install`.

### Accettazione 9 — Documentazione

- Sito docs build pulita, zero link rotti (link checker in CI).
- Ogni codice errore documentato in `troubleshooting.md`.
- Almeno un tutorial e2e (quickstart) testato passo-passo da un umano.

### Accettazione 10 — Performance e scala

- Deploy idempotente di 20 componenti distribuiti su 3 host completa in
  ≤ 3 minuti.
- Control plane sostiene 50 daemon connessi simultaneamente con uso memoria
  < 512 MB.
- `get_state` per progetto con 20 componenti ritorna in ≤ 200 ms.

### Accettazione 11 — Consumo di token (agenti)

- Test automatico che misura: numero di token medi richiesti a un agente
  per portare a termine un workflow tipo ("aggiorna API al commit X, verifica
  healthcheck, rollback se fallisce"). Benchmark documentato; obiettivo
  ≤ 30% rispetto a una baseline di "shell libera" (indicativo; la misura
  è comparativa).

## 6. Documenti finali

- `docs/phase-3-completion.md`: deviazioni, scelte architetturali
  effettuate (es. K8s in-process vs microservizio).
- `README.md` aggiornato con badge CI, link docs, quickstart.
- `CHANGELOG.md` con tutte le versioni rilasciate durante la fase.

## 7. Cose da evitare in Fase 3

- Non aggiungere feature non elencate qui; eventuali estensioni (runner
  aggiuntivi, multi-region, ecc.) vanno in una fase successiva.
- Non compromettere la semplicità dello YAML core per supportare K8s.
- Non rompere la compatibilità dei file YAML Fase 1/2.

## 8. Criteri di qualità

- Copertura test ≥ 85% Python, ≥ 80% Go.
- Zero warning da linter in CI.
- Zero dipendenze con CVE note di livello High o Critical (scan con
  `trivy` o equivalente su immagine finale).
- Documentazione con spell check pulito.
- Tutte le API pubbliche con OpenAPI e ogni tool MCP con schema
  input/output documentato.
