# YAML Schema — deployment.yaml

Questo documento definisce lo schema formale del file di configurazione del
progetto (`deployment.yaml`). Le chiavi sono divise in sezioni e ogni campo
indica la fase in cui viene introdotto.

## Versione

Lo schema è versionato. Il campo radice `api_version` è obbligatorio e permette
evoluzione senza rompere compatibilità.

```yaml
api_version: maestro/v1
```

Valori validi:
- `maestro/v1` — introdotto in Fase 1
- `maestro/v1beta` — campi di Fase 2
- `maestro/v1ga` — campi di Fase 3 (K8s, advanced rollout)

Un file `maestro/v1` deve rimanere accettabile anche nelle fasi successive (solo
additiva).

## Struttura di primo livello

```yaml
api_version: maestro/v1
project: <string>              # Nome del progetto (obbligatorio)
description: <string>          # Opzionale

hosts: { ... }                 # Macchine target
components: { ... }            # Definizioni dei componenti
deployment: [ ... ]            # Assegnazione componenti → host

defaults: { ... }              # Valori di default per componenti/host (opz.)
credentials_ref: <string>      # Riferimento al file credenziali (opz.)
```

## `hosts`

Mappa `<id_host>: <HostSpec>`.

```yaml
hosts:
  api-server:
    type: linux                 # linux | kubernetes (Fase 3)
    address: 10.0.0.10          # Solo per linux
    port: 22                    # SSH, default 22 (Fase 1 non usa SSH ma lo tiene)
    user: deploy                # Utente remoto per operazioni di setup
    daemon:
      endpoint_override: null   # Override URL del control plane per il daemon
      install_method: auto      # auto | manual
    tags: [prod, eu-west]       # Libere, usabili per selezione
```

### HostSpec per Kubernetes (Fase 3)

```yaml
hosts:
  k8s-prod:
    type: kubernetes
    kubeconfig_ref: vault://kube/prod
    context: production
    namespace: default
    tags: [prod, k8s]
```

## `components`

Mappa `<id_componente>: <ComponentSpec>`.

```yaml
components:
  api:
    description: REST API service
    source:               { ... }     # Da dove prendere il codice/immagine
    build:                [ ... ]     # Passi di build (opz.)
    config:               { ... }     # Config e template (opz.)
    run:                  { ... }     # Come avviarlo
    deploy_mode: hot                  # hot | cold | blue_green
    reload_triggers:                  # Cosa forza cold anche se deploy_mode=hot
      code: cold
      config: hot
      dependencies: cold
    tests:                { ... }     # (Fase 2)
    depends_on: [db]                  # Dipendenze logiche fra componenti
    healthcheck:          { ... }
    resources:            { ... }     # Limiti opzionali (Fase 2 per Docker)
```

### `source`

```yaml
# Opzione A: Git
source:
  type: git
  repo: https://github.com/org/api.git
  ref: main                 # branch, tag, o commit SHA
  credentials_ref: git.github-org   # riferimento nel vault
  subpath: services/api     # opzionale, se il componente è una sottocartella

# Opzione B: Docker image pre-built
source:
  type: docker
  image: myregistry.io/api
  tag: "1.4.2"
  pull_policy: if_not_present   # always | if_not_present | never

# Opzione C: Archivio locale (utile per bootstrap)
source:
  type: archive
  path: ./artifacts/api.tar.gz
```

### `build`

Lista di step shell eseguiti nella directory del componente sul host (per
sorgenti `git` o `archive`). Ignorato per `docker`.

```yaml
build:
  - command: npm ci
  - command: npm run build
  - command: make binary
    env:
      GOOS: linux
      GOARCH: amd64
  - command: ./generate-assets.sh
    timeout: 600s           # default 300s
    working_dir: web        # relativo alla root del componente
```

### `config`

Configurazione applicativa renderizzata prima del deploy.

```yaml
config:
  templates:
    - source: configs/api.env.j2     # relativo alla root del componente
      dest: /etc/my-app/api.env      # dove finisce sul host
      mode: 0640
  vars:
    DB_HOST: "{{ hosts['db-server'].address }}"
    DB_PORT: 5432
    LOG_LEVEL: info
  secrets:
    DB_PASSWORD: "{{ vault://db/password }}"
    JWT_SECRET: "{{ vault://jwt/secret }}"
```

Le variabili supportano riferimenti a `hosts`, `components`, `vars` globali, e
segreti via `vault://`.

### `run`

Specifica come il daemon deve eseguire il componente. Il tipo determina il
runner.

#### systemd

```yaml
run:
  type: systemd
  unit_name: my-api              # default: <component_id>
  command: /opt/my-api/bin/api --config /etc/my-app/api.env
  working_directory: /opt/my-api
  user: api-user
  group: api-user
  env:
    RUST_LOG: info
  restart: on-failure            # no | on-failure | always
  restart_sec: 5
```

#### docker

```yaml
run:
  type: docker
  image: "{{ source.image }}:{{ source.tag }}"   # risolto dal control plane
  container_name: api
  ports:
    - "8080:8080"
    - "127.0.0.1:9090:9090"
  volumes:
    - "/var/lib/my-app:/data"
  env:
    LOG_LEVEL: "{{ config.vars.LOG_LEVEL }}"
  networks:
    - app-net
  restart: unless-stopped
  command: ["serve", "--port", "8080"]    # override CMD
  resources:                               # Fase 2
    memory: 512m
    cpus: "0.5"
```

#### kubernetes (Fase 3)

```yaml
run:
  type: kubernetes
  manifest_template: deploy/api.yaml.j2
  # oppure:
  helm:
    chart: ./charts/api
    values:
      image:
        tag: "{{ source.tag }}"
```

### `healthcheck`

```yaml
healthcheck:
  type: http                   # http | tcp | command
  # Per http
  url: http://localhost:8080/health
  expect_status: 200
  expect_body_contains: "ok"   # opzionale
  # Per tcp
  # port: 5432
  # Per command
  # command: /usr/local/bin/check.sh
  interval: 10s
  timeout: 5s
  start_period: 20s            # tempo concesso prima di considerare unhealthy
  retries: 3
```

### `tests` (Fase 2)

```yaml
tests:
  unit:
    command: npm test
    when: pre_deploy           # pre_deploy | post_deploy
    timeout: 300s
    blocking: true             # se true, un fail blocca il deploy
  integration:
    command: npm run test:integration
    when: post_deploy
    requires: [db, redis]      # attende che siano running
    blocking: true
  smoke:
    type: http
    url: http://localhost:8080/health
    expect_status: 200
    when: post_deploy
    blocking: false
```

### `depends_on` e ordinamento

`depends_on` esprime dipendenze logiche fra componenti; il control plane
costruisce il grafo e deploya in ordine topologico. Un ciclo è errore di
validazione.

## `deployment`

Lista di binding host → componenti con strategia di rollout opzionale.

```yaml
deployment:
  - host: db-server
    components: [db]
    strategy: sequential         # default
  - host: api-server
    components: [api]
    depends_on_hosts: [db-server]   # attende che i deploy su quegli host siano green
    strategy: sequential
  - host: web-cluster            # gruppo virtuale (Fase 2)
    components: [web]
    strategy: canary
    canary:
      initial_fraction: 0.2
      step_fraction: 0.3
      verify_duration: 2m
```

### Strategie di rollout disponibili

- `sequential` — deploy uno alla volta con healthcheck fra uno e l'altro
  (default)
- `parallel` — tutti insieme
- `canary` — frazione iniziale, verify, espandi (Fase 2)
- `blue_green` — a livello di host, se il componente supporta `blue_green`
  (Fase 2)

## `defaults`

Valori di default applicati a tutti i componenti o host che non li sovrascrivono.

```yaml
defaults:
  component:
    deploy_mode: cold
    healthcheck:
      interval: 10s
      retries: 3
  host:
    user: deploy
```

## `credentials_ref`

Puntatore al file/backend delle credenziali. Se assente, il control plane cerca
`credentials.yaml` nella stessa cartella del `deployment.yaml`.

```yaml
credentials_ref: ./credentials.yaml        # file locale cifrato
# oppure
credentials_ref: vault://hashi/team-a      # backend vault (Fase 2)
```

## Variabili interpolabili

La sintassi `{{ ... }}` (Jinja2) può riferirsi a:

- `hosts['<id>'].address`, `.port`, `.tags` ecc.
- `components['<id>'].<qualunque campo risolto>`
- `config.vars.<nome>` (del componente corrente)
- `vault://<path>` — risolto a runtime dal credential backend
- `env.<VAR>` — variabile d'ambiente del control plane (uso sconsigliato fuori
  dallo sviluppo)

## Validazione

Il control plane valida:

- Conformità sintattica allo schema (tipi, campi obbligatori).
- Integrità referenziale (`depends_on` punta a componenti esistenti; ogni
  `deployment.host` esiste in `hosts`; ogni `deployment.components` esiste in
  `components`).
- Assenza di cicli nelle dipendenze.
- Risolvibilità dei riferimenti `{{ ... }}` con un passaggio di dry-run.
- Presenza dei segreti referenziati nel credential backend.

Un file che fallisce la validazione viene rifiutato con errore strutturato
che include path del campo e motivo.

## Esempio completo (minimale)

```yaml
api_version: maestro/v1
project: demo-stack
description: Stack di esempio con API + DB

hosts:
  host1:
    type: linux
    address: 192.168.1.10
    user: deploy

components:
  db:
    source:
      type: docker
      image: postgres
      tag: "16"
    run:
      type: docker
      container_name: db
      ports: ["5432:5432"]
      env:
        POSTGRES_PASSWORD: "{{ vault://db/password }}"
        POSTGRES_DB: appdb
    healthcheck:
      type: tcp
      port: 5432
      interval: 10s
    deploy_mode: cold

  api:
    source:
      type: git
      repo: https://github.com/example/api.git
      ref: main
    build:
      - command: npm ci
      - command: npm run build
    config:
      templates:
        - source: .env.j2
          dest: ./.env
      vars:
        DB_HOST: "{{ hosts['host1'].address }}"
        DB_PORT: 5432
      secrets:
        DB_PASSWORD: "{{ vault://db/password }}"
    run:
      type: systemd
      unit_name: demo-api
      command: node dist/server.js
      working_directory: /opt/demo-api
      user: deploy
    healthcheck:
      type: http
      url: http://localhost:3000/health
      expect_status: 200
    depends_on: [db]
    deploy_mode: cold

deployment:
  - host: host1
    components: [db, api]
    strategy: sequential
```
