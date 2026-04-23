# playmaestro.cloud — Static Website Deploy Design

**Date:** 2026-04-23
**Status:** Approved (brainstorming phase complete, pending implementation plan)
**Scope:** Deploy the static website in `website/` (HTML/CSS/JS, ~50 KB) to host1 (109.199.123.26) at `https://www.playmaestro.cloud/`, using Maestro itself for the deploy-and-reload loop and Caddy-in-Docker for web serving plus automatic TLS. Manual host preparation is kept to the bare minimum (Docker group membership + firewall); everything repeatable goes through Maestro's control plane → daemon path.

This spec also formalizes a new generic primitive in the Maestro schema — `config.files` — that emerged from this use case but is broadly reusable for any component that needs verbatim file artifacts mounted into a container.

---

## 1. Context & goals

The user purchased `playmaestro.cloud` and pointed DNS to `109.199.123.26` (host1, which already runs the Maestro control plane and a daemon). The site is three static files and needs HTTPS.

**Two intertwined goals:**

1. **Operational:** `https://www.playmaestro.cloud/` serves the content of `website/` with a valid Let's Encrypt certificate, apex → www redirect, gzip, and sane security headers.
2. **Product:** exercise Maestro on a real deploy that is **not** "build and run a server binary" — the dominant pattern of the demo stacks so far. Surface the gaps between the current primitives and what this class of use case requires, and formalize those gaps as generalized primitives (per the repeated user directive: generalize, don't special-case).

**Non-goals:**

- CI/CD integration (no GitHub Action that auto-deploys on `website/` changes — manual invocation via Maestro CLI is Phase 1 behavior).
- Staging / multi-env (one host, one site, one domain).
- Authoring workflow improvements for the site itself.
- Replacing Apache or certbot anywhere else in the project.

---

## 2. Architecture overview

One host, one component, two volumes, one container. The manual / Maestro-managed split is deliberately lopsided toward Maestro:

```
┌────────────────────────────────────────────────────────────────────────┐
│ host1 (109.199.123.26)                                                 │
│                                                                         │
│ [MANUAL — 1-time, ≤ 3 commands]       [MAESTRO — fully repeatable]    │
│ ─────────────────────────────────     ──────────────────────────────   │
│ usermod -aG docker agent              component: caddy-playmaestro     │
│ ufw allow 80/tcp && ufw allow 443     ├─ source: docker image          │
│ mkdir -p playmaestro/{site,caddy}     ├─ config.templates: Caddyfile   │
│                                        ├─ config.files:   website/ →   │
│                                        │    atomic_symlink swap       │
│                                        ├─ run: docker                  │
│                                        │    (ports 80/443, 3 volumes)  │
│                                        ├─ healthcheck: https 200      │
│                                        └─ reload_triggers for hot     │
│                                                                         │
│ /home/agent/playmaestro/                                                │
│   site/releases/<hash>/                ← extracted tarballs             │
│   site/current -> releases/<hash>      ← atomic symlink                 │
│   caddy/Caddyfile                      ← rendered from template         │
│   caddy/data/                          ← Let's Encrypt cert store       │
└────────────────────────────────────────────────────────────────────────┘
```

**Design invariants:**

- **No distro pollution.** No `apache2`, no `certbot`, no custom systemd units beyond what Docker itself installs. If host1 is reimaged, the manual part takes three commands; the rest is one `maestro deploy`.
- **Daemon runs unprivileged.** `agent` gets `docker` group membership but no `sudo` grants. This keeps the daemon within Maestro's non-privileged-by-default posture.
- **Content swap is atomic and zero-downtime.** Symlink flip + volume layout (see §5.3) means a content deploy does not restart Caddy and does not produce a half-rendered page to any concurrent request.
- **Certificate is portable.** `caddy/data/` is a plain directory on the host; tarballing it moves the domain's Let's Encrypt state to any other host. No `/etc/letsencrypt` lock-in.

---

## 3. New primitive: `config.files`

### 3.1 Motivation

The current `ComponentSpec` schema (`docs/yaml-schema.md`) assumes every component either has a `source` that produces a single artifact (git build, Docker image, archive) plus optional `config.templates` for rendered config files. A static website served by a container needs **both** a container image (Caddy) **and** a body of verbatim files (the website) mounted into that container's volume. Today this forces one of three ugly workarounds:

- Two components (`website-content` with no `run`, plus `caddy` with `depends_on`) — runs into the "files-only component has no `run.type`" gap.
- Bake the site into a custom Docker image (a build-step layer) — couples deploys of content changes to image rebuilds and pushes.
- Smuggle the site files through `config.templates` one by one — abuse of semantics; breaks for binary assets.

Each is a special case. The generalization underneath is: **a component can need arbitrary file material materialized on the host, independent of whether it has a `source` that builds/pulls code or an image**. That's the primitive below.

### 3.2 Schema extension

Under an existing component's `config` block, alongside `templates`:

```yaml
config:
  templates:
    - source: ...
      dest: ...
  files:                                    # NEW
    - source: <path>                        # directory, *.tar.gz, *.zip, or single file
      dest: <host path>                     # where it lands on the target host
      strategy: overwrite|atomic|atomic_symlink   # default: overwrite for files, atomic_symlink for directories
      mode: 0755                            # optional; for single-file sources sets the file mode;
                                            # for directory sources applies to the top-level dest directory,
                                            # and contents preserve source permissions (tar-like semantics)
      owner: agent                          # optional, requires sudo if not the daemon user
  vars: ...
  secrets: ...
```

**Semantics per strategy:**

| Strategy | Behavior | Atomic? | Typical use |
|---|---|---|---|
| `overwrite` | `rm -rf dest && copy/extract source to dest` | No (window of inconsistency) | Pre-start setup, dev environments |
| `atomic` | Write to `dest.tmp` + `rename(dest.tmp, dest)` | Yes for single file; for dirs uses `rename` of the whole dir (requires dest parent exists) | Single-file configs that must never be half-written |
| `atomic_symlink` | Extract to `<dest>/releases/<hash>/`, flip `<dest>/current → releases/<hash>` | Yes for any size of directory; O(1) rollback | Content bodies, asset bundles, release-per-deploy patterns |

**Hash input for `atomic_symlink`:** content hash of the source archive/directory (sha256 of the tar stream, not of the deployment timestamp) so that identical content = same release directory and redeploys are idempotent.

### 3.3 Retention & rollback

For `atomic_symlink`, the daemon keeps the last N releases in `releases/`. **In Phase 1 this is hardcoded N=5** inside the daemon. `request.rollback` with `steps_back: k` re-flips `current` to the release that was active `k` deploys ago. Older releases are garbage collected oldest-first when count exceeds N. Phase 2 exposes the value as a per-entry setting (`config.files[].retain: <int>`).

### 3.4 Interaction with `reload_triggers`

`config.files` changes fire a new trigger key: `content`. A component's `reload_triggers` can declare:

```yaml
reload_triggers:
  code: cold
  config: hot
  content: hot             # NEW
```

Where `content: hot` means "don't restart the process, just flip the symlink and the runtime picks it up" (works for Caddy, Nginx, and any server that re-reads filesystem on each request). `content: cold` would restart the runtime (needed for servers that cache filesystem at boot).

### 3.5 Implementation phases

- **Phase 1 (this spec):** Proposal and reference implementation in the `examples/playmaestro-cloud/` use case. The CP schema validator is extended to accept `config.files` with the three strategies; the daemon implements `atomic_symlink` end-to-end (the other two fall out naturally).
- **Phase 2:** Formalize in `docs/yaml-schema.md`, add schema tests, add `content` as a first-class trigger key, document rollback semantics.

Out of scope for this spec: retroactively migrating any other Maestro example to use `config.files`.

---

## 4. Manual host1 setup (one-time)

Performed manually as `agent` on `109.199.123.26`. Idempotent; running the block twice is safe.

```bash
# 1. Add agent to docker group so the Maestro daemon can manage containers.
#    Requires logout/login for the membership to take effect.
sudo usermod -aG docker agent
id agent | grep -q '(docker)' || { echo "re-login agent"; exit 1; }

# 2. Firewall (Ubuntu ufw).
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw reload

# 3. Create the playmaestro root. Maestro won't mkdir top-level host paths.
mkdir -p /home/agent/playmaestro/site/releases
mkdir -p /home/agent/playmaestro/caddy/data
```

**Pre-deploy checks** (run before invoking Maestro, fail-loud if any is false):

- `docker --version` returns a version string; daemon talks to the socket as `agent`.
- `dig www.playmaestro.cloud +short` and `dig playmaestro.cloud +short` both return `109.199.123.26`.
- `ss -tlnp | grep -E ':80|:443'` is empty (nothing else is bound).
- `ufw status` shows 80/tcp and 443/tcp as ALLOW.

---

## 5. Maestro deployment manifest

### 5.1 Repo layout additions

```
examples/playmaestro-cloud/
├── deployment.yaml          # the manifest, §5.2
├── Caddyfile.j2             # template rendered by config.templates, §5.4
└── README.md                # how to deploy, gap documentation, rollback runbook
```

The site content itself lives at `website/` in the repo root and is referenced from the manifest via a relative path.

### 5.2 `deployment.yaml`

```yaml
api_version: maestro/v1
project: playmaestro-cloud
description: Static website www.playmaestro.cloud served by Caddy with automatic Let's Encrypt HTTPS

hosts:
  host1:
    type: linux
    address: 109.199.123.26
    user: agent
    tags: [prod, web]

components:
  caddy-playmaestro:
    description: Caddy reverse proxy + static file server with auto-HTTPS
    source:
      type: docker
      image: caddy
      tag: "2-alpine"
      pull_policy: if_not_present
    config:
      templates:
        - source: Caddyfile.j2
          dest: /home/agent/playmaestro/caddy/Caddyfile
          mode: 0644
      files:
        - source: ../../website
          dest: /home/agent/playmaestro/site
          strategy: atomic_symlink
          mode: 0755
      vars:
        primary_host: www.playmaestro.cloud
        apex_host: playmaestro.cloud
    run:
      type: docker
      container_name: caddy-playmaestro
      image: "{{ source.image }}:{{ source.tag }}"
      ports:
        - "80:80"
        - "443:443"
      volumes:
        - "/home/agent/playmaestro/site:/srv-root:ro"
        - "/home/agent/playmaestro/caddy/data:/data"
        - "/home/agent/playmaestro/caddy/Caddyfile:/etc/caddy/Caddyfile:ro"
      restart: unless-stopped
    deploy_mode: hot
    reload_triggers:
      code: cold
      config: hot
      content: hot
    healthcheck:
      type: http
      url: https://www.playmaestro.cloud/
      expect_status: 200
      interval: 30s
      timeout: 10s
      start_period: 60s
      retries: 3

deployment:
  - host: host1
    components: [caddy-playmaestro]
    strategy: sequential
```

### 5.3 Volume mount detail (load-bearing)

The container mounts `/home/agent/playmaestro/site` (parent of `current`) — **not** `/home/agent/playmaestro/site/current`. This is necessary for atomic swaps to be visible inside the running container:

- Docker resolves symlinks at mount time. If we bound `site/current` directly, the container would see the resolved inode of whichever release was current at container start; subsequent flips of `current` on the host would **not** propagate.
- By mounting the parent, Caddy sees a live `/srv-root/` on every request and follows `/srv-root/current` each time. A symlink flip on the host is observed by the next request into the container.

Caddy's `root` directive in the Caddyfile is therefore `/srv-root/current`, not `/srv`.

### 5.4 `Caddyfile.j2`

```caddy
{{ vars.primary_host }} {
    root * /srv-root/current
    file_server
    encode gzip

    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        X-Content-Type-Options nosniff
        Referrer-Policy strict-origin-when-cross-origin
    }
}

{{ vars.apex_host }} {
    redir https://{{ vars.primary_host }}{uri} permanent
}
```

Caddy handles HTTP→HTTPS redirect implicitly (any request on :80 for a site block also defined on :443 gets a 308 to HTTPS). Certificate acquisition for `playmaestro.cloud` and `www.playmaestro.cloud` is automatic on first request to each hostname over HTTPS; Caddy uses the HTTP-01 challenge on :80.

---

## 6. Deploy flow walkthrough

From `maestro deploy` issued by the user against the control plane on host1, the sequence on the daemon side:

1. **Pull image** (`source.type: docker`). Skipped if already present at this tag per `pull_policy: if_not_present`.
2. **Render template** (`config.templates`). Caddyfile written to `caddy/Caddyfile` (atomic via write-tmp + rename).
3. **Materialize files** (`config.files`, strategy `atomic_symlink`).
   - Compute `<hash>` as the sha256 of the normalized tar stream of `source` (see §3.2) — deterministic across identical content regardless of wallclock.
   - If `site/releases/<hash>/` already exists → skip extraction. **Idempotent: identical content = identical release directory = same `current` target, flip is a no-op.**
   - Otherwise: extract `source` into `site/releases/<hash>/`, apply `mode` to the top-level directory.
   - Atomically flip `site/current → releases/<hash>` via `rename(2)`.
4. **Determine reload scope** from `reload_triggers`:
   - If only `content` changed (same image, same Caddyfile) → flip already done, no container action needed. `reload_triggers.content: hot` is satisfied by the symlink flip alone.
   - If `config` (Caddyfile) changed → `docker exec caddy-playmaestro caddy reload --config /etc/caddy/Caddyfile` (Caddy's graceful reload; no dropped connections).
   - If `code` (image tag) changed → `docker stop` + `docker run` with new image (cold).
5. **Healthcheck.** Poll `https://www.playmaestro.cloud/` every 30 s with `start_period: 60s` grace for first cert acquisition. Fail after 3 consecutive non-200s.
6. **GC old releases.** After successful healthcheck, prune `releases/` to keep N=5 newest by mtime.

First-ever deploy path (no container running, no cert): step 4 becomes `docker run`, step 5's grace period absorbs ACME challenge latency.

---

## 7. Validation plan

**Post-deploy (automated via healthcheck + manual spot-check):**

1. `curl -sI https://www.playmaestro.cloud/` — `HTTP/2 200`, `content-type: text/html`, `strict-transport-security` present.
2. `curl -sI http://www.playmaestro.cloud/` — `308` redirect to `https://`.
3. `curl -sI https://playmaestro.cloud/` — `301` redirect to `https://www.playmaestro.cloud/`.
4. `echo | openssl s_client -connect www.playmaestro.cloud:443 -servername www.playmaestro.cloud 2>/dev/null | openssl x509 -noout -issuer` — `issuer` contains `O = Let's Encrypt` (intermediate CN will be something like `R3`/`R10`/`R11` depending on which LE intermediate Caddy got at acquisition time; the specific identifier doesn't matter, the `O` match does).
5. `curl -s https://www.playmaestro.cloud/ | diff - website/index.html` — byte-equal.
6. Browser load — cert green, site renders, no mixed-content warnings in console.

**Idempotency check:** running `maestro deploy` a second time without any change must:

- Not re-extract the website (same hash → same `releases/<hash>/`, already present).
- Not re-render the Caddyfile (or at most write identical bytes and not reload).
- Not restart the container.
- Healthcheck still green.

---

## 8. Rollback & kill-switch

**Content rollback (most common):**
```
# via Maestro CLI (uses request.rollback from docs/protocol.md §4)
maestro rollback caddy-playmaestro --steps-back 1
```
Effect: symlink flip back to the previous release under `site/releases/`. O(1), zero downtime.

**Full rollback (Caddyfile + content):** re-apply the previous `deployment.yaml` via `maestro deploy`.

**Kill-switch (domain down NOW):**
```
ssh agent@109.199.123.26 docker stop caddy-playmaestro
```
Ports 80/443 go unbound. DNS still resolves but returns connection refused. Nothing in `/etc/*` to clean up. To restore: `docker start caddy-playmaestro`.

**Certificate recovery:** `caddy/data/` is the source of truth. Snapshot with `tar czf cert-backup-$(date +%s).tar.gz -C /home/agent/playmaestro caddy/data`. Restore by extracting into the same path and starting the container.

---

## 9. Gaps surfaced and future work

The brainstorming deliberately stress-tested the current Maestro schema. The gaps that did **not** survive the switch from Apache-native to Caddy-in-Docker (so are **not** pursued further):

- Narrow `sudo` allowlist primitive — obsoleted by `agent` in the `docker` group.
- Shared system service reload (reload an externally-owned systemd unit) — obsoleted; Caddy is Maestro-owned.
- `source.type: system_package` — obsoleted for this use case.
- `run.type: files_only` — obsoleted by the `config.files` generalization (§3).

The gaps that **do** remain and become Phase 2 work:

1. **`config.files` primitive** — §3 above. This is the single real primitive this use case introduces. It formalizes and generalizes the file-material-as-first-class-citizen concept.
2. **`reload_triggers: content` key** — small addition, follows from `config.files` (§3.4).
3. **Retention policy for release symlinks** (§3.3). Today ad-hoc; formalize as a component-level setting (`config.files[].retain: 5`).

These are tracked in the Phase 2 roadmap as a single cluster — they share implementation surface (daemon-side extraction, atomicity, retention) and should land together.

---

## 10. Out of scope

- Caching headers beyond the defaults (no `Cache-Control` strategy yet — can be added later in the Caddyfile).
- CSP headers beyond the minimum — the site is static with no third-party embeds, so no Content-Security-Policy for v1.
- WWW-canonical vs apex-canonical debate — www is chosen (see Caddyfile); revisit if/when the site grows SEO-sensitive.
- Multi-host failover / load balancing — single-host deploy.
- Monitoring / alerting on cert expiry — Caddy renews 30 days before expiry; if that fails, the healthcheck in §6 step 5 catches it after expiry, which is late but acceptable for a portfolio site. Upgrade path: daemon surfaces Caddy's own metrics (Phase 3).

---

## 11. Decision log

Key choices made during brainstorming (2026-04-23), recorded for traceability:

- **Caddy over Apache.** Auto-HTTPS eliminates certbot lifecycle, and Caddy-in-Docker eliminates distro-level installs. Apache would have surfaced four gaps (sudoers, shared-service reload, `source.type: system_package`, files-only component); Caddy surfaces one (`config.files`) — which is the one worth formalizing.
- **One component, not two** (`caddy-playmaestro` not `website-content` + `caddy`). Two components would have forced either `run.type: files_only` as a new primitive or `depends_on` orchestration for what is logically one deployment unit. One component + `config.files` expresses the same thing cleanly and reuses the existing reload-trigger mechanism.
- **Volume mount parent, not `current`.** Docker symlink-resolution-at-mount-time requires this (§5.3). Non-negotiable for atomic content swap to work at all.
- **`agent` in `docker` group, no sudo.** Preserves Maestro's non-privileged-daemon stance; passwordless sudo would be a camel's-nose-in-the-tent.
- **Portable cert store under `/home/agent/`**, not `/etc/letsencrypt/`. Makes the deploy pure user-space and the cert trivially movable.
