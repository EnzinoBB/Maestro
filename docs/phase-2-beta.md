# Fase 2 — Beta

> **Istruzioni per l'agente che legge questo documento.**
> Presuppone che la Fase 1 sia completa. Prima di iniziare, leggi:
> - `docs/architecture.md`
> - `docs/yaml-schema.md` (sezioni marcate Fase 2)
> - `docs/protocol.md`
> - `docs/phase-1-completion.md` (generato dall'agente di Fase 1)
> - Questo documento
>
> Segui la checklist in §3 in ordine. Ogni gruppo ha test dedicati; fai
> passare i test del gruppo prima di avanzare. Al termine esegui la suite
> di accettazione in §5.
>
> **Le funzionalità Fase 1 non devono regredire.** Esegui l'intera suite
> di accettazione di Fase 1 come primo passo e alla fine — deve continuare
> a passare.

## 1. Obiettivo della Fase 2

Portare il sistema da prototipo a beta utilizzabile in condizioni reali:

- Trigger di deploy automatico dai commit Git (CI/CD).
- Framework di test per componenti (unit pre-deploy, integration/smoke
  post-deploy).
- Rollback automatico su test/healthcheck falliti.
- Hot deploy e blue-green per componenti che lo supportano.
- Strategia di rollout canary per i binding host/componente.
- Credential vault cifrato con backend pluggable.
- Server MCP completo, con tutti i verbi documentati in `architecture.md §3`.
- UI web ricca (React/Vite) con streaming log, grafici metriche, storico
  deploy.
- Skill matura con flussi decisionali.

**Out of scope:** Kubernetes, osservabilità avanzata (Prometheus/tracing),
HA, mTLS, CLI (tutto in Fase 3).

## 2. Prerequisiti

- Repository come risulta al completamento Fase 1 (tutti i test di
  accettazione passanti).
- Node 20+ e pnpm o npm (per l'UI React).
- Disponibile un repository Git reale (anche locale bare) per i test di
  git-sync.

## 3. Checklist operativa

### Gruppo A — Schema e retro-compatibilità

A1. Estendere i modelli Pydantic in `control-plane/app/config/schema.py`
    con i campi Fase 2:
    - `deploy_mode: hot | blue_green`
    - `reload_triggers` (mappa `code/config/dependencies` → `hot|cold`)
    - `tests` (vedi `yaml-schema.md`)
    - `resources` (per Docker)
    - `canary` su `deployment[].strategy`
    - `defaults`
    - `credentials_ref` con risoluzione a vault
    - `source.type: artifact` con `artifact_id` (vedi Gruppo J)
    - `self_update: bool` su `ComponentSpec` (vedi Gruppo J)

A2. Assicurarsi che file YAML Fase 1 continuino a essere accettati senza
    modifiche (backward compatibility).

**Test:**
- `test_schema_backcompat.py`: parsa tutte le fixture Fase 1, deve
  succedere.
- `test_schema_v2_fields.py`: parsa nuove fixture con campi Fase 2,
  verifica modelli popolati correttamente.

### Gruppo B — Credential vault

B1. `control-plane/app/credentials/vault.py`: interfaccia con metodi
    `get(ref: str) -> SecretValue`, `put`, `delete`, `list`.

B2. `control-plane/app/credentials/file_backend.py`: backend su file
    cifrato. Master key derivata da passphrase (scrypt con parametri
    conservativi: N=2**15, r=8, p=1). Formato: header versione + salt +
    AES-256-GCM del JSON.

B3. CLI helper `python -m app.credentials.cli` (o script in `scripts/`):
    - `vault init` — crea vault vuoto.
    - `vault set <path> <value>` — aggiunge/aggiorna secret.
    - `vault get <path>` — stampa secret (solo in sviluppo).
    - `vault list` — lista path.

B4. Integrazione con l'orchestrator: quando un payload di deploy richiede
    secret (`{{ vault://... }}`), sono risolti just-in-time prima di
    spedire al daemon e passati nel campo `secrets` del messaggio
    `request.deploy`. Mai scritti in chiaro su disco.

B5. Gestione credenziali Git: stesso vault, path convenzionale
    `git.<alias>`. Il clone sul control plane usa le credenziali risolte.

**Test unitari (`tests/unit/test_credentials.py`):**
- Init + set + get + list + delete.
- Passphrase errata → errore (non crash).
- File corrotto → errore con codice chiaro.
- Secret referenziato in template di componente risolto correttamente.

### Gruppo C — Git-sync component

C1. Nuovo modulo `control-plane/app/gitsync/`:
    - `poller.py`: polling periodico dei ref tracciati per tutti i
      componenti `source.type: git`.
    - `webhook.py`: endpoint `POST /api/webhooks/{provider}` che accetta
      payload GitHub/GitLab/Gitea/Bitbucket, valida la firma, e notifica
      il sync.
    - `sync.py`: logica centrale. Quando rileva un nuovo commit:
      - Aggiorna lo stato "drift detected" per il componente.
      - Consulta la policy (`auto_deploy: true|false`, default false).
      - Se auto_deploy, avvia il deploy via engine.

C2. Storage dei commit tracciati (ultimo commit visto per
    `<component_id,branch>`) in tabella SQLite.

C3. Configurazione in `deployment.yaml`:
    ```yaml
    components:
      api:
        source:
          type: git
          repo: ...
          ref: main
          sync:
            poll_interval: 5m         # default
            auto_deploy: true
    ```

C4. UI: badge "drift detected" sui componenti con nuovo commit non ancora
    deployato. Bottone "Deploy latest".

**Test:**
- `test_gitsync_poller.py`: mock di un repo; verifica detect del nuovo
  commit.
- `test_webhook.py`: payload GitHub firmato e non firmato; verifica
  elaborazione o rejection.
- e2e `test_git_autodeploy.py`: repo git bare locale → push di un commit
  → verifica che il componente sia ridistribuito entro 30s.

### Gruppo D — Test framework per componenti

D1. Estendere `request.tests.run` nel protocollo: payload specifica quali
    test eseguire (`unit`, `integration`, `smoke`, `all`).

D2. Nel daemon, handler che:
    - Per test `command`: esegue nel working_dir del componente, cattura
      output, ritorna struttura `{name, ok, duration_ms, stdout_tail,
      stderr_tail, exit_code}`.
    - Per test `http`: esegue richiesta e verifica status/body.
    - Gestisce dipendenze (`requires: [db]`) solo per post_deploy: verifica
      che i componenti elencati siano running prima di eseguire.

D3. Integrazione orchestrator:
    - `pre_deploy` con `blocking: true` → se fallisce, deploy annullato
      e ritorna errore.
    - `post_deploy` con `blocking: true` → se fallisce, rollback
      automatico.
    - Risultati persistiti nello storico deploy.

D4. UI: vista "Tests" per componente con storico risultati.

**Test:**
- `test_tests_runner_daemon_test.go`: esecuzione test comandi con
  successo e fallimento; cattura output; timeout.
- `test_orchestrator_with_tests.py`: deploy con test pre fallito →
  deploy annullato. Deploy con test post fallito → rollback chiamato.

### Gruppo E — Hot deploy, blue-green, canary

E1. Daemon: per `deploy_mode: hot`, estendere i runner:
    - `systemd`: eseguire `systemctl reload <unit>` se il componente ha un
      `ExecReload` definito; altrimenti caricare la nuova versione binaria
      side-by-side e `systemctl daemon-reload && systemctl restart` con
      strategia che preserva uptime quanto possibile.
    - `docker`: avviare un nuovo container con nome temporaneo, healthcheck
      positivo, swap del `container_name` (rename del vecchio, rename del
      nuovo), remove del vecchio. Porte pubblicate: richiede o un reverse
      proxy davanti o che il componente accetti qualche secondo di
      sovrapposizione (opzione `--publish-all` durante la finestra di
      swap).

E2. Daemon: per `deploy_mode: blue_green`, variante esplicita che tiene
    due installazioni permanenti e commuta il "traffico" (che in assenza
    di load balancer significa: quale container espone le porte dichiarate).

E3. Orchestrator: per strategia `canary`:
    - Calcola le "istanze" (nel caso single-host, ≥1 host gruppo virtuale;
      nel caso multi-host, si applica al gruppo).
    - Deploya `initial_fraction` → attende `verify_duration` + healthcheck.
    - Espande di `step_fraction` fino al 100% o rollback se verifica fallisce.

E4. Nuovo campo `reload_triggers`: quando un deploy cambia solo la config
    di un componente `hot`, eseguire reload invece di restart.

**Test:**
- `test_hot_deploy_docker_test.go` (daemon): deploy hot di nginx con
  config diverso; verifica zero-downtime (richieste continue ogni 100ms
  durante lo swap → nessuna 5xx).
- `test_canary_orchestrator.py`: due host simulati, verifica rollout
  graduale e interruzione su fallimento.

### Gruppo F — Rollback automatico

F1. Daemon: mantenere storico degli ultimi N (default 5) hash deployati
    per componente, con artefatti necessari per tornarci (immagine docker
    taggata, tarball del codice precedente, config precedente).

F2. `request.rollback` payload: `{component_id, steps_back: 1}` o
    `{component_id, to_hash: "..."}`.

F3. Orchestrator: su fallimento di `healthcheck` post-deploy dopo N
    tentativi, o fallimento di test post-deploy blocking, automaticamente
    emette `request.rollback` per il componente incriminato e, se la
    strategia lo richiede, per i componenti deployati nella stessa
    sessione.

F4. API: `POST /api/components/{id}/rollback?steps=1`.

F5. UI: bottone "Rollback" nel pannello componente con selettore "quanti
    step indietro".

**Test:**
- `test_rollback_daemon_test.go`: deploy A → deploy B → rollback → stato
  torna ad A identico.
- `test_auto_rollback.py`: deploy con healthcheck volutamente fallibile →
  orchestrator rilascia rollback automatico entro timeout.

### Gruppo G — MCP completo e skill

G1. Aggiungere al server MCP i verbi mancanti:
    - `rollback`
    - `run_tests`
    - `get_deployment_history`
    - `get_metrics`
    - `tail_logs_stream` (se supportato dall'SDK MCP; altrimenti rimane
      non-stream e si documenta)
    - `drift_status`
    - `upload_artifact`, `update_component`, `remove_component`,
      `get_host_diagnostics` (vedi Gruppo J)

G2. Aggiornare `skill/SKILL.md` con:
    - Modello mentale del sistema.
    - Flusso standard: validate → diff → conferma utente → apply → watch →
      verify → (rollback se necessario).
    - Tassonomia errori e azioni corrispondenti.
    - Convenzioni YAML e anti-pattern.
    - Come leggere log/metriche in modo token-efficient.
    - Esempi di dialoghi d'uso.

**Test:**
- `test_mcp_tools_v2.py`: ogni tool invocato con input valido/invalido,
  output validato.
- `test_skill_coverage.py`: la skill documenta tutti i verbi MCP
  disponibili (grep su SKILL.md vs elenco tool).

### Gruppo H — UI ricca

H1. Riscrivere `control-plane/web/` con Vite + React + TypeScript.
    Libreria componenti: Shadcn/ui o MUI a scelta; preferire componenti
    leggeri.

H2. Pagine:
    - **Dashboard**: grid di host con componenti, stato, metriche live
      (mini-grafici sparkline).
    - **Config Editor**: editor YAML con syntax highlighting (Monaco),
      validate + diff + apply.
    - **Deploy History**: tabella cronologica, filtri, dettaglio con fasi
      ed eventuali errori.
    - **Logs**: streaming live per componente, filtri per livello.
    - **Tests**: storico risultati test per componente.
    - **Vault**: gestione secret (solo nomi/path, mai valori).
    - **Drift**: lista componenti con drift detected.

H3. WebSocket del frontend verso il control plane per updates real-time
    (stato, metriche, log).

**Test UI:**
- Test di componente con Vitest.
- Test e2e con Playwright: flusso "modifica YAML → apply → vedi
  componente running → apri log → verifica drift badge dopo commit git".

### Gruppo I — Pacchettizzazione aggiornata

I1. Dockerfile del control plane con build multi-stage.
I2. Aggiornare `docker-compose.yml` di sviluppo.
I3. Script `scripts/backup.sh` per backup dello stato del control plane
    (DB + vault).

### Gruppo J — Primitive di lifecycle granulare

Fase 1 consente di applicare un intero `deployment.yaml` ma manca di
primitive per (a) deployare un componente con un pacchetto che l'agente
ha già in locale (es. binario compilato sulla sua macchina) senza passare
da Git; (b) rimuovere un componente in modo idempotente — oggi `to_remove`
nel diff è skippato per design; (c) ispezionare lo stato di un host in un
solo round-trip. Fase 2 colma i tre gap.

#### J1 — Artifact upload + `source.type: artifact`

CP-side:
- Endpoint REST:
  - `POST /api/artifacts` (multipart o JSON con `content_b64`): upload di
    un file, ritorna `{artifact_id, sha256, size, created_at}`.
  - `GET /api/artifacts` lista, `GET /api/artifacts/{id}` metadata,
    `DELETE /api/artifacts/{id}`.
- Storage locale con deduplicazione per sha256 e TTL configurabile
  (default 24h); metadata su DB.
- Quando l'orchestrator deve deployare un componente con
  `source.type: artifact`, include i bytes nel payload `request.deploy`
  verso il daemon (riusando il sottotipo `inline_tarball` esistente per
  archivi, o nuovo `binary_executable` per eseguibili singoli).

Schema YAML (vedi `yaml-schema.md`):
```yaml
components:
  api:
    source:
      type: artifact
      artifact_id: "a-7f3a..."   # caricato via upload_artifact
    run: { ... }
```

MCP / API:
- Tool `upload_artifact(path, name?)` → `{artifact_id}`. L'agente fornisce
  il path di un file sulla sua macchina (o bytes base64); il CP lo
  registra.
- Tool `update_component(component_id, source?)` per aggiornare **un solo**
  componente senza modificare lo YAML canonico:
  - Se `source` è fornito, sostituisce temporaneamente la source e
    deploya (utile per "prova questo artifact senza committare la
    modifica").
  - Se omesso, riusa la source corrente (equivale a `deploy
    --component=X`).
- API REST analoga: `POST /api/components/{id}/update` con body opzionale
  `{source: {...}}`.

**Caso particolare — self-update del daemon** (non richiede verbo
dedicato: riusa J1):
- Il daemon viene dichiarato come componente managed nello YAML dell'host:
  ```yaml
  components:
    maestrod:
      source: { type: artifact, artifact_id: "..." }
      run:
        type: systemd
        unit_name: maestro-daemon
        command: /usr/local/bin/maestrod --config /etc/maestrod/config.yaml
      deploy_mode: blue_green
      self_update: true
  ```
- Con `self_update: true`, il daemon applica la pattern "replace-on-exit":
  scrive il nuovo binario in `/usr/local/bin/maestrod.new`, spawn di un
  processo figlio su endpoint alternativo per healthcheck, swap atomico
  del binario + `systemctl restart maestro-daemon`. Safety: il nuovo
  processo deve riconnettersi al CP entro timeout (default 60s), altrimenti
  rollback automatico ripristinando il binario precedente.

Test:
- `test_artifact_upload.py` (unit): upload + sha256 dedup + TTL + delete.
- `test_artifact_deploy_test.go` (integration): deploy di un tarball
  caricato via artifact end-to-end.
- `test_self_update.py` (e2e): compila localmente un `maestrod` con
  `Version = "0.2.0-test"`, upload, deploy come self-update, verifica
  version bump post-riconnessione e downtime ≤ 10s.

#### J2 — Rimozione di componenti

Daemon-side:
- Handler `request.component.remove` con payload
  `{component_id, keep_volumes?: bool, keep_state?: bool}`.
- Esecuzione runner-specific:
  - Docker: `docker rm -f`, rimuovi volumes dichiarati (skip se
    `keep_volumes`).
  - Systemd: `systemctl stop + disable`, rimuovi unit file, rimuovi
    `/opt/maestro/<id>/`.
- Cancella row dallo state store (salvo `keep_state` per audit).
- Emette `event.component_removed`.

Orchestrator:
- Implementare il ramo `to_remove` nel diff (oggi skippato con commento
  `Fase 1: we don't remove automatically`).
- `apply_config?prune=true` esegue effettivamente le rimozioni; default
  `prune=false` mantiene il comportamento attuale.
- MCP tool `remove_component(component_id, keep_volumes?)` per rimozione
  puntuale senza toccare lo YAML.

Test:
- `test_remove_daemon_test.go`: deploy → remove → verifica container/unit
  spariti, volumes comportamento corretto con/senza `keep_volumes`.
- `test_orchestrator_prune.py`: apply con `prune=true` rimuove i
  componenti non più in YAML.

#### J3 — Host diagnostics

Handler daemon `request.host.diagnostics` ritorna uno snapshot aggregato
(ottimizzazione token: l'agente ottiene tutto in un round-trip invece di
chiamare N volte):

```json
{
  "host_id": "host1",
  "os": { "name": "Ubuntu", "version": "24.04", "kernel": "6.8..." },
  "uptime_sec": 86400,
  "cpu": { "count": 4, "load_1m": 0.4, "load_5m": 0.3 },
  "memory_mb": { "total": 8192, "used": 2048, "available": 6144 },
  "disk": [ { "path": "/", "total_gb": 100, "used_gb": 43 } ],
  "runtimes": {
    "docker":  { "active": true, "version": "29.1.3" },
    "systemd": { "active": true, "version": "255" }
  },
  "daemon": { "version": "0.2.0", "uptime_sec": 3600, "reconnects": 0 }
}
```

MCP tool `get_host_diagnostics(host_id)`.

Test:
- `test_diagnostics_daemon_test.go`: mock dei comandi di sistema e
  verifica struttura output.
- `test_mcp_diagnostics.py`: round-trip MCP, payload < 2 KB per host con
  ≤ 5 componenti.

## 4. Fixture e dati di test

- `tests/fixtures/deployment-canary.yaml`
- `tests/fixtures/deployment-hot.yaml`
- `tests/fixtures/deployment-with-tests.yaml`
- `tests/fixtures/vault-initial.enc`
- `tests/fixtures/git-bare/` (repo bare per test git-sync)

## 5. Suite di accettazione Fase 2

### Accettazione 1 — Regressione Fase 1

Tutta la suite di accettazione della Fase 1 deve continuare a passare
senza modifiche.

### Accettazione 2 — Credential vault

- `vault init` + `vault set db/password "secret"` + deploy di un componente
  che referenzia `{{ vault://db/password }}` → componente riceve la env var
  corretta.
- Stop del control plane, riavvio con passphrase corretta → vault
  riapribile.
- Riavvio con passphrase errata → errore chiaro, no crash.

### Accettazione 3 — Git-sync

- Configurare un componente con `sync.auto_deploy: true`.
- Push di un commit sul branch tracciato.
- Entro il poll interval o immediatamente se webhook: il componente è
  ridistribuito al nuovo commit. Log audit conserva evento.

### Accettazione 4 — Test framework

- Deploy con `tests.unit.blocking: true` che fallisce (`command: false`)
  → deploy annullato, errore riportato.
- Deploy con `tests.smoke` che fallisce post-deploy → rollback automatico
  eseguito, stato finale = precedente.

### Accettazione 5 — Hot deploy

- Deploy hot di nginx → mentre avviene, un loop di `curl` alla porta
  pubblicata non produce errori (tollerate al massimo 2 errori su 100
  richieste).

### Accettazione 6 — Canary

- Deploy canary su 3 host (simulati) con `initial_fraction: 0.34`,
  `step_fraction: 0.34`. Il rollout progredisce a 1/3, poi 2/3, poi 3/3
  dopo healthcheck positivi.
- Introdurre un guasto a metà rollout → rollout interrotto e host già
  deployati rollback-ati.

### Accettazione 7 — MCP completo

Uno script Python usa il client MCP e invoca *tutti* i verbi documentati;
ogni chiamata ritorna un oggetto con la struttura attesa.

### Accettazione 8 — Consumo di token

- `get_deployment_history` ritorna solo gli ultimi N deploy (N
  configurabile, default 20) invece di tutti.
- Gli errori API/MCP hanno *sempre* campo `code` (enum) + `message` +
  (quando applicabile) `suggested_fix`.
- Payload `deploy` verso daemon rimane ≤ 4 MB o fallisce con errore chiaro
  che suggerisce di usare `source.type: git` lato daemon.

### Accettazione 9 — UI

Test e2e Playwright: il flusso utente completo (login no-auth → edit YAML
→ apply → vedi dashboard popolarsi → apri log → force drift → vedi badge).

### Accettazione 10 — Test suites complete

```bash
make test-unit
make test-integration
make test-e2e
make test-ui          # nuovo target Fase 2, esegue Playwright
```

Tutti green.

### Accettazione 11 — Artifact upload + update granulare

- L'agente esegue `upload_artifact` con un tarball locale → riceve
  `artifact_id`.
- `update_component` di un componente esistente con
  `source: {type: artifact, artifact_id: "..."}` → il componente è
  ridistribuito con i bytes dell'artifact, gli altri componenti NON
  vengono toccati.
- Dopo TTL (con TTL ridotto per test) l'artifact è rimosso, nuovi
  deploy con lo stesso `artifact_id` ritornano errore `not_found` chiaro.

### Accettazione 12 — Self-update del daemon

- Partendo da `maestrod 0.1.0`, compilare localmente `maestrod 0.2.0-test`
  (dummy version bump), caricarlo via `upload_artifact`.
- Deploy con `self_update: true` come componente managed dell'host.
- Verifica: dopo lo swap il daemon risulta `0.2.0-test` su `/api/hosts`,
  la disconnessione osservata dal CP dura ≤ 10 s, nessuna perdita di
  stato dei componenti managed dal daemon.
- Fault injection: se il nuovo binario non si riconnette entro 60 s, il
  daemon torna automaticamente a `0.1.0` (rollback).

### Accettazione 13 — Remove componente

- Deploy di un componente → `remove_component` → verifica container/unit
  spariti su host e riga rimossa dallo state store.
- Modificare il YAML rimuovendo un componente, `apply_config?prune=true`
  → componente rimosso. Stesso flow con `prune=false` → componente
  lasciato in piedi (backward compat con Fase 1).

### Accettazione 14 — Diagnostics

- `get_host_diagnostics(host_id)` per entrambi gli host → JSON completo
  con tutti i campi del §J3, dimensione ≤ 2 KB per host, latenza ≤ 500 ms.

## 6. Documenti da produrre alla fine

- `docs/phase-2-completion.md`: sommario, deviazioni, note operative
  aggiornate.
- Aggiornare `README.md` con istruzioni installazione/uso Fase 2.
- Aggiornare `skill/SKILL.md`.

## 7. Cose che l'agente **non** deve fare in Fase 2

- Non introdurre Kubernetes.
- Non introdurre Prometheus/tracing integrati (metriche base già esistenti
  continuano).
- Non introdurre HA del control plane: si accetta singolo nodo.
- Non introdurre RBAC multi-utente: UI resta accessibile senza auth o con
  singolo token admin.
- Non migrare a PostgreSQL: SQLite rimane adeguato in Fase 2.

## 8. Criteri di qualità aggiornati

- Copertura test ≥ 85% Python, ≥ 75% Go.
- Tempo rollback ≤ 15 secondi per componente Docker.
- Tempo di riconnessione daemon ≤ 10 secondi.
- Nessun secret scritto in chiaro su disco (verificato da test dedicato
  che cerca pattern noti dopo un deploy).
