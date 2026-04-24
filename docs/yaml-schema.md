# YAML Schema — deployment.yaml

This document defines the formal schema of the project's configuration file
(`deployment.yaml`). Keys are grouped into sections and each field indicates
the phase in which it is introduced.

## Version

The schema is versioned. The root field `api_version` is required and allows
evolution without breaking compatibility.

```yaml
api_version: maestro/v1
```

Valid values:
- `maestro/v1` — introduced in Phase 1
- `maestro/v1beta` — Phase 2 fields
- `maestro/v1ga` — Phase 3 fields (K8s, advanced rollout)

A `maestro/v1` file must remain acceptable in later phases as well (additive
only).

## Top-level structure

```yaml
api_version: maestro/v1
project: <string>              # Project name (required)
description: <string>          # Optional

hosts: { ... }                 # Target machines
components: { ... }            # Component definitions
deployment: [ ... ]            # Component → host assignments

defaults: { ... }              # Defaults for components/hosts (optional)
credentials_ref: <string>      # Reference to the credentials file (optional)
```

## `hosts`

Map `<host_id>: <HostSpec>`.

```yaml
hosts:
  api-server:
    type: linux                 # linux | kubernetes (Phase 3)
    address: 10.0.0.10          # linux only
    port: 22                    # SSH, default 22 (Phase 1 does not use SSH but keeps it)
    user: deploy                # Remote user for setup operations
    daemon:
      endpoint_override: null   # Override of the control plane URL for the daemon
      install_method: auto      # auto | manual
    tags: [prod, eu-west]       # Free-form, usable for selection
```

### HostSpec for Kubernetes (Phase 3)

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

Map `<component_id>: <ComponentSpec>`.

```yaml
components:
  api:
    description: REST API service
    source:               { ... }     # Where to get the code/image from
    build:                [ ... ]     # Build steps (optional)
    config:               { ... }     # Config and templates (optional)
    run:                  { ... }     # How to run it
    deploy_mode: hot                  # hot | cold | blue_green
    reload_triggers:                  # What forces cold even if deploy_mode=hot
      code: cold
      config: hot
      dependencies: cold
      content: hot                   # fires when a config.files entry changes
    tests:                { ... }     # (Phase 2)
    depends_on: [db]                  # Logical dependencies between components
    healthcheck:          { ... }
    resources:            { ... }     # Optional limits (Phase 2 for Docker)
```

### `source`

```yaml
# Option A: Git
source:
  type: git
  repo: https://github.com/org/api.git
  ref: main                 # branch, tag, or commit SHA
  credentials_ref: git.github-org   # vault reference
  subpath: services/api     # optional, if the component is a subdirectory

# Option B: Pre-built Docker image
source:
  type: docker
  image: myregistry.io/api
  tag: "1.4.2"
  pull_policy: if_not_present   # always | if_not_present | never

# Option C: Local archive (useful for bootstrap)
source:
  type: archive
  path: ./artifacts/api.tar.gz
```

### `build`

List of shell steps executed in the component's directory on the host (for
`git` or `archive` sources). Ignored for `docker`.

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
    working_dir: web        # relative to the component root
```

### `config`

Application configuration rendered before the deployment.

```yaml
config:
  templates:
    - source: configs/api.env.j2     # relative to the component root
      dest: /etc/my-app/api.env      # where it ends up on the host
      mode: 0640
  vars:
    DB_HOST: "{{ hosts['db-server'].address }}"
    DB_PORT: 5432
    LOG_LEVEL: info
  secrets:
    DB_PASSWORD: "{{ vault://db/password }}"
    JWT_SECRET: "{{ vault://jwt/secret }}"
```

Variables support references to `hosts`, `components`, global `vars`, and
secrets via `vault://`.

```yaml
config:
  templates:
    - source: configs/api.env.j2
      dest: /etc/my-app/api.env
      mode: 0640
  files:
    - source: ./assets            # directory or single file
      dest: /var/www/assets
      strategy: atomic_symlink    # overwrite | atomic | atomic_symlink
      mode: 0755
```

`config.files` materializes verbatim files or directories (no Jinja2
rendering) on the target host. Three strategies:
- `overwrite` — direct copy, non-atomic.
- `atomic` — write to `.tmp` + rename, atomic per path.
- `atomic_symlink` — extract to `<dest>/releases/<hash>/` and flip
  `<dest>/current`. Zero-downtime; rollback via `request.rollback` flips
  back to the previous release. Default strategy for directory sources.

### `run`

Specifies how the daemon must run the component. The type determines the
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
  image: "{{ source.image }}:{{ source.tag }}"   # resolved by the control plane
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
  command: ["serve", "--port", "8080"]    # CMD override
  resources:                               # Phase 2
    memory: 512m
    cpus: "0.5"
```

#### kubernetes (Phase 3)

```yaml
run:
  type: kubernetes
  manifest_template: deploy/api.yaml.j2
  # or:
  helm:
    chart: ./charts/api
    values:
      image:
        tag: "{{ source.tag }}"
```

### `reload_triggers`

Controls which change types trigger a cold restart even when `deploy_mode` is
set to `hot`.

```yaml
reload_triggers:
  code: cold
  config: hot
  dependencies: cold
  content: hot                   # fires when a config.files entry changes
```

### `healthcheck`

```yaml
healthcheck:
  type: http                   # http | tcp | command
  # For http
  url: http://localhost:8080/health
  expect_status: 200
  expect_body_contains: "ok"   # optional
  # For tcp
  # port: 5432
  # For command
  # command: /usr/local/bin/check.sh
  interval: 10s
  timeout: 5s
  start_period: 20s            # grace time before being considered unhealthy
  retries: 3
```

### `tests` (Phase 2)

```yaml
tests:
  unit:
    command: npm test
    when: pre_deploy           # pre_deploy | post_deploy
    timeout: 300s
    blocking: true             # if true, a failure blocks the deploy
  integration:
    command: npm run test:integration
    when: post_deploy
    requires: [db, redis]      # waits until they are running
    blocking: true
  smoke:
    type: http
    url: http://localhost:8080/health
    expect_status: 200
    when: post_deploy
    blocking: false
```

### `depends_on` and ordering

`depends_on` expresses logical dependencies between components; the control
plane builds the graph and deploys in topological order. A cycle is a
validation error.

## `deployment`

List of host → component bindings with an optional rollout strategy.

```yaml
deployment:
  - host: db-server
    components: [db]
    strategy: sequential         # default
  - host: api-server
    components: [api]
    depends_on_hosts: [db-server]   # waits until the deployments on those hosts are green
    strategy: sequential
  - host: web-cluster            # virtual group (Phase 2)
    components: [web]
    strategy: canary
    canary:
      initial_fraction: 0.2
      step_fraction: 0.3
      verify_duration: 2m
```

### Available rollout strategies

- `sequential` — deploy one at a time with a healthcheck between each
  (default)
- `parallel` — all at once
- `canary` — initial fraction, verify, expand (Phase 2)
- `blue_green` — at host level, if the component supports `blue_green`
  (Phase 2)

## `defaults`

Default values applied to all components or hosts that do not override them.

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

Pointer to the credentials file/backend. If absent, the control plane looks
for `credentials.yaml` in the same directory as the `deployment.yaml`.

```yaml
credentials_ref: ./credentials.yaml        # local encrypted file
# or
credentials_ref: vault://hashi/team-a      # vault backend (Phase 2)
```

## Interpolable variables

The `{{ ... }}` (Jinja2) syntax can reference:

- `hosts['<id>'].address`, `.port`, `.tags`, etc.
- `components['<id>'].<any resolved field>`
- `config.vars.<name>` (of the current component)
- `vault://<path>` — resolved at runtime by the credential backend
- `env.<VAR>` — control-plane environment variable (discouraged outside
  development)

## Validation

The control plane validates:

- Syntactic conformance to the schema (types, required fields).
- Referential integrity (`depends_on` points to existing components; every
  `deployment.host` exists in `hosts`; every `deployment.components` exists
  in `components`).
- Absence of cycles in the dependency graph.
- Resolvability of `{{ ... }}` references via a dry-run pass.
- Presence of the referenced secrets in the credential backend.

A file that fails validation is rejected with a structured error that
includes the field path and the reason.

## Complete example (minimal)

```yaml
api_version: maestro/v1
project: demo-stack
description: Example stack with API + DB

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
