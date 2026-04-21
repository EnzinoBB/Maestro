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
