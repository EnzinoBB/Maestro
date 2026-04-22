# Installer Scripts & Release Pipeline — Design

**Date:** 2026-04-22
**Status:** Approved (brainstorming phase complete, pending implementation plan)
**Scope:** Make Maestro installation user-friendly on the model of Claude's `install.sh`: a single `curl … | sudo bash` for both the Control Plane and each daemon, backed by a real release pipeline on GitHub and a self-serve install endpoint on the running CP.

---

## 1. Context & goals

Today the user must:

- Build the daemon binary manually (`make build-linux`).
- `scp` the binary and `scripts/install-daemon.sh` to every target host.
- Copy `docker-compose.example.yml` → `docker-compose.yml`, replace `CHANGE_ME` token, `docker compose up`.
- Distribute the token out-of-band and pass it as `--token` to each daemon install.

There is no release channel, no version pinning, no upgrade path, no checksum verification, and the shared token is handled by humans — which means it ends up in shell history and chat logs.

**Goals of this design:**

1. **One-liner install** for both CP and daemon, from a stable public URL.
2. **GitHub as the canonical source of truth**, with versioned releases, cross-arch binaries, and a published Docker image for the CP.
3. **`playmaestro.cloud` as a reference CP** that also acts as a self-serve install source: when an admin installs a daemon against their own CP, the CP serves a pre-configured installer and the binary itself, so the admin doesn't even need to reach GitHub.
4. **Enrollment tokens** (k3s/Tailscale style) replace the shared-token-in-shell-history pattern: the CP mints short-lived, single-use tokens; the daemon trades them at first boot for a permanent, per-host token that the admin never sees.
5. **Full install lifecycle**: install, upgrade, uninstall, for both CP and daemon.
6. **macOS support** for the daemon (Apple Silicon homelab clusters), Docker-workload scope only for v1.

**Non-goals:** see §7.

---

## 2. Architecture overview

Two distribution channels, one source of truth:

- **GitHub Releases** (`https://github.com/EnzinoBB/Maestro`) is the canonical source. A tag `vX.Y.Z` produces: daemon binaries for 4 `OS/arch` targets, a multi-arch Docker image `ghcr.io/enzinobb/maestro-cp:X.Y.Z`, the two installer scripts, and a `SHA256SUMS` file.
- **Reference CP instance** (`https://playmaestro.cloud`, owned by the project) runs the published image and additionally serves, out of itself, `install-daemon.sh` pre-configured with its own URL, plus the bundled daemon binaries. An admin's self-hosted CP (`https://cp.mycompany.example`) gets the same behavior automatically — it's baked into the image.

**The daemon is a bare-metal executable on Linux and macOS. It is never containerized** — it must act on the host (systemd/launchd, Docker socket, filesystem). We distribute binaries only; there is no daemon Docker image.

**Topology:**

```
┌──────────────────────────────┐             ┌──────────────────────────────┐
│ GitHub (EnzinoBB/Maestro)    │             │ Reference CP                 │
│                              │             │ (playmaestro.cloud)          │
│ Releases:                    │             │                              │
│   maestrod-{linux,darwin}-…  │◀─ pulls ────│ Runs ghcr.io/.../maestro-cp  │
│   install-{cp,daemon}.sh     │             │                              │
│   SHA256SUMS                 │             │ Serves:                      │
│                              │             │   GET /install-daemon.sh     │
│ ghcr.io/enzinobb/maestro-cp  │             │     (with CP_URL baked in)   │
└──────────────────────────────┘             │   GET /dist/maestrod-<arch>  │
          ▲                                  │   GET /dist/SHA256SUMS       │
          │ curl …/install-cp.sh             │   POST /api/enrollments      │
          │                                  │   GET  /enroll/<token>       │
          │                                  │   POST /api/enroll/<token>/  │
    ┌─────┴──────┐                           │        consume               │
    │ Admin's VM │                           └──────────────────────────────┘
    │ (CP host)  │                                        ▲
    └────────────┘                                        │ curl …/enroll/<t>
                                                  ┌───────┴──────┐
                                                  │ Target host  │
                                                  │ (daemon)     │
                                                  └──────────────┘
```

---

## 3. Release pipeline (GitHub Actions)

### 3.1 Triggers

- **`release.yml`**: on push of tag matching `v*`.
- **`ci.yml`**: on push/PR to `main` — runs tests, `ruff`, `go vet`, `shellcheck`. Does not publish anything.

### 3.2 `release.yml` jobs

1. **`build-binaries`** (matrix: `linux/amd64`, `linux/arm64`, `darwin/amd64`, `darwin/arm64`)
   - `go build -ldflags="-s -w -X main.version=<tag>"` → `dist/maestrod-<os>-<arch>`
   - Upload as workflow artifact.

2. **`build-image`** (single job, uses `docker buildx`)
   - Build multi-arch `linux/amd64,linux/arm64` image.
   - Copy all freshly built daemon binaries (both `linux/*` and `darwin/*`) into the image at `/opt/maestro-cp/dist/` so the CP can serve them at `/dist/maestrod-{linux,darwin}-{amd64,arm64}`.
   - Push to `ghcr.io/enzinobb/maestro-cp:<tag>` and `ghcr.io/enzinobb/maestro-cp:latest`.
   - Authenticate with `${{ secrets.GITHUB_TOKEN }}` (no PAT needed for GHCR).
   - `permissions: { packages: write, id-token: write, attestations: write }` — emits GitHub-native build provenance (SLSA attestation) for the image.

3. **`release`** (needs: `build-binaries`, `build-image`)
   - Download all binary artifacts.
   - Generate `SHA256SUMS` via `sha256sum dist/* > SHA256SUMS`.
   - Copy `scripts/install-cp.sh` and `scripts/install-daemon.sh` from the tagged commit.
   - Create GitHub Release with body auto-generated from commit messages since last tag (`softprops/action-gh-release`).
   - Upload: all 4 binaries, `SHA256SUMS`, both installer scripts. Emit build attestations for each binary.

### 3.3 Image build

- `control-plane/Dockerfile` is extended to `COPY --from=<binary-stage> dist/maestrod-* /opt/maestro-cp/dist/` (all four `os/arch` combos). The CP's FastAPI app serves `/dist/*` as a static mount.
- Production Dockerfile does **not** pull binaries from GitHub at build time — the binaries are built in the same workflow run and copied in, so image and binaries are always in lockstep.

### 3.4 CI (`ci.yml`)

- `test-unit` (Go + pytest), `lint` (`ruff`, `go vet`), `shellcheck` on `scripts/*.sh`.
- `installer-smoke` (see §6.2).
- No macOS runtime tests yet — we only cross-compile darwin binaries and verify they build; runtime tests are manual for macOS targets in v0.x.

---

## 4. Control Plane installer & token bootstrap

### 4.1 `install-cp.sh`

Invocation:

```bash
curl -fsSL https://github.com/EnzinoBB/Maestro/releases/latest/download/install-cp.sh | sudo bash
```

Flow:

1. **Pre-flight.** Require root. Detect Docker and `docker compose` v2. If missing and `--no-docker-install` was not set, install via `https://get.docker.com`. If set, error out with a clear message listing the missing components.
2. **Layout.** Create `/opt/maestro-cp/` containing a generated `docker-compose.yml` (port, volume, image tag baked in) and a `.env` with `MAESTRO_CP_VERSION=vX.Y.Z` plus non-secret settings.
3. **Start.** `docker compose pull && docker compose up -d`.
4. **Health wait.** Poll `GET http://localhost:<port>/health` for up to 60s.
5. **Report.** Print UI URL and the command to retrieve the auto-generated daemon token:
   ```
   docker compose -f /opt/maestro-cp/docker-compose.yml logs maestro-cp | grep 'DAEMON TOKEN'
   ```

**Flags:**

| Flag | Default | Purpose |
|---|---|---|
| `--version <tag>` | `latest` | Pin a specific release. |
| `--port <N>` | `8000` | Host port to expose. |
| `--data-dir <path>` | `/var/lib/maestro-cp` | Volume mount point. |
| `--upgrade` | — | `docker compose pull && up -d`, preserves volume. |
| `--uninstall` | — | `docker compose down`; keeps volume. |
| `--uninstall --purge` | — | Down + `-v` + `rm -rf /opt/maestro-cp` (explicit confirmation required). |
| `--no-docker-install` | — | Fail if Docker missing instead of auto-installing. |

### 4.2 MySQL-style token bootstrap

The CP image ships with a `docker-entrypoint.sh` wrapper that runs before `uvicorn`:

1. If `MAESTRO_DAEMON_TOKEN` env var is set → use it, no generation, no banner. (Escape hatch for admins who manage secrets externally.)
2. Else if `/data/daemon-token` exists → read it, export as `MAESTRO_DAEMON_TOKEN`. (Normal subsequent starts.)
3. Else → first run: `openssl rand -hex 32`, write to `/data/daemon-token` (mode `0600`), export, and emit a banner to stdout:
   ```
   ===========================================================
     GENERATED MAESTRO DAEMON TOKEN (save this, shown once):
       <64-hex-char-token>
     Also stored at /data/daemon-token inside the container.
   ===========================================================
   ```

The token is persisted on the `/data` volume → restarts preserve it; `--uninstall --purge` wipes it. The token is the **root signing secret** for enrollment tokens; it is never given directly to daemons — daemons only ever see their own permanent, per-host token minted during enrollment.

### 4.3 Endpoints served by the CP (new)

| Endpoint | Purpose |
|---|---|
| `GET /install-daemon.sh` | Returns the installer script with `DEFAULT_CP_URL` string-substituted to the host of the request (`request.url.hostname`). Content-Type `text/x-shellscript`. |
| `GET /dist/maestrod-linux-{amd64,arm64}` | Serves the daemon binary bundled in the image. Static file mount over the directory populated at build time. |
| `GET /dist/maestrod-darwin-{amd64,arm64}` | Same, for macOS. |
| `GET /dist/SHA256SUMS` | Checksums of the bundled binaries. |

These endpoints are public (no auth): they return only public artifacts. The enrollment endpoints (§5) carry the secrets.

---

## 5. Daemon enrollment & installer

### 5.1 Enrollment model (CP side)

New SQL table `host_enrollments`:

| Column | Type | Notes |
|---|---|---|
| `token` | text PK | URL-safe random, 32 bytes. |
| `created_at` | timestamp | |
| `expires_at` | timestamp | Default `created_at + 30m`. |
| `max_uses` | int | Default 1. |
| `used_count` | int | Incremented atomically on consume. |
| `allowed_host_id_pattern` | text nullable | Optional regex limiting which `host_id` may consume. |
| `created_by` | text | `"admin"` for v0.x; real user id in v2. |
| `consumed_by_host_id` | text nullable | Audit. |
| `consumed_at` | timestamp nullable | Audit. |
| `revoked_at` | timestamp nullable | If set, 410 on consume. |

**Versioning note:** the primitive is deliberately shaped to be reusable beyond daemons (future CLI enrollments, agent enrollments). If a second role appears, it becomes a `role` column on the same table, not a parallel system.

### 5.2 CP endpoints (enrollment)

| Endpoint | Auth | Purpose |
|---|---|---|
| `POST /api/enrollments` | Admin UI session | Create enroll token. Body: `{ttl_sec?, max_uses?, host_id_pattern?}`. Returns `{enroll_url, expires_at}`. |
| `GET /api/enrollments` | Admin UI session | List active tokens. |
| `DELETE /api/enrollments/<token>` | Admin UI session | Revoke. |
| `GET /enroll/<token>` | Public (token is the secret) | Serves `install-daemon.sh` with `ENROLL_URL=https://<host>/enroll/<token>` substituted. Does **not** consume the token. |
| `POST /api/enroll/<token>/consume` | Public (token is the secret) | Consume. Body: `{host_id, daemon_version, os, arch, protocol_version: 1}`. Returns `{daemon_token, cp_endpoint}`. Atomic: row-lock, check `used_count < max_uses` and not expired/revoked, increment `used_count`, set audit fields, commit. On failure: 410 Gone. |

**Protocol versioning.** `protocol_version` is passed as a field in the consume body. CP returns HTTP 426 if unsupported. For v0.x only `1` exists.

### 5.3 UI — `/hosts` page (extension)

- Table of registered hosts (already scaffolded conceptually).
- **"Add host"** button → modal with:
  - `host_id` (optional text; if blank, daemon proposes its own `hostname -s`)
  - TTL (select: 15min / 1h / 24h)
  - `max_uses` (default 1)
- Submit → `POST /api/enrollments` → modal shows the enroll URL and a one-liner ready to copy:
  ```
  curl -fsSL https://playmaestro.cloud/enroll/<token> | sudo bash
  ```
  If `host_id` was specified:
  ```
  curl -fsSL https://playmaestro.cloud/enroll/<token> | sudo bash -s -- --host-id <id>
  ```

### 5.4 `install-daemon.sh`

Invocations (all equivalent in outcome, differ in source):

```bash
# via enrollment (typical)
curl -fsSL https://playmaestro.cloud/enroll/<token> | sudo bash -s -- --host-id api-01

# generic (requires manual flags)
curl -fsSL https://github.com/EnzinoBB/Maestro/releases/latest/download/install-daemon.sh | \
  sudo bash -s -- --enroll-url https://playmaestro.cloud/enroll/<token> --host-id api-01
```

Flow:

1. **Pre-flight.** Require root. Detect OS: `Linux` (require `systemd`) or `Darwin` (require `launchctl`). Detect arch: `amd64` or `arm64`. Other combos → fail with clear message.
2. **Parse flags** (see table below). `host_id` defaults to `hostname -s`.
3. **Download binary.** Primary source: `${ENROLL_URL%/enroll/*}/dist/maestrod-<os>-<arch>`. Fallback on failure or `--from-github`: `https://github.com/EnzinoBB/Maestro/releases/download/<version>/maestrod-<os>-<arch>`. Download into a temp file.
4. **Verify SHA256.** Download `SHA256SUMS` from the same source and verify. On mismatch, abort — leave no artifacts behind.
5. **Enroll.** `POST ${ENROLL_URL}/consume` with JSON body `{host_id, daemon_version, os, arch, protocol_version: 1}`. On 410 or any non-2xx, abort with the CP's error body. Parse response for `daemon_token` and `cp_endpoint`.
6. **Install binary.** `install -m 0755` to `/usr/local/bin/maestrod` (Linux) or `/usr/local/bin/maestrod` (macOS — same path).
7. **Write config.** `/etc/maestrod/config.yaml` (Linux) or `/usr/local/etc/maestrod/config.yaml` (macOS), mode `0640`, owner root. Contains `host_id`, `endpoint: <cp_endpoint>`, `token: <daemon_token>`, and platform-forced flags (`systemd_enabled: false` on Darwin).
8. **Install service.**
   - Linux: write `/etc/systemd/system/maestro-daemon.service` (same shape as current `install-daemon.sh`), `systemctl daemon-reload && systemctl enable --now maestro-daemon.service`.
   - macOS: write `/Library/LaunchDaemons/com.maestro.daemon.plist` (system-wide, so it survives logout; requires root), `launchctl load /Library/LaunchDaemons/com.maestro.daemon.plist`.
9. **Verify.** Poll `systemctl is-active` (Linux) or `launchctl list | grep com.maestro.daemon` (macOS) for up to 5s. On success, print status; on failure, dump last 20 lines of logs and exit non-zero.

**Flags:**

| Flag | Default | Purpose |
|---|---|---|
| `--host-id <id>` | `hostname -s` | Host identifier. |
| `--enroll-url <url>` | (embedded for enroll/* download) | For generic installer. |
| `--version <tag>` | (matches script's own tag) | Pin binary version. |
| `--from-github` | — | Force GitHub source, skip CP. |
| `--insecure` | — | Accept self-signed TLS / http CP. Reuses existing daemon flag. |
| `--upgrade` | — | See §5.5. |
| `--uninstall` | — | See §5.6. |

### 5.5 Upgrade

`install-daemon.sh --upgrade [--version vX.Y.Z]`:

1. Read existing `config.yaml` to know the CP endpoint (used as binary source).
2. Download new binary + checksum, verify.
3. `systemctl stop maestro-daemon` (or `launchctl unload`).
4. `install -m 0755` over the existing binary (atomic rename).
5. Start service, verify.

Preserves `config.yaml` and daemon state dir (`/var/lib/maestrod/` on Linux, `/usr/local/var/maestrod/` on macOS).

### 5.6 Uninstall

`install-daemon.sh --uninstall`:

1. Best-effort notify CP: `POST /api/hosts/<host_id>/deregister` with current token. Non-fatal if it fails.
2. Stop + disable service (`systemctl disable --now` / `launchctl unload && rm plist`).
3. Remove binary and service unit/plist.
4. With `--purge`: also remove `/etc/maestrod/` (or macOS equivalent) and `/var/lib/maestrod/`.

---

## 6. Security

### 6.1 Artifact integrity

- Every binary download is followed by `sha256sum -c` against a `SHA256SUMS` file fetched from the same source.
- On mismatch, the installer aborts with no side effects (no partial install left behind).
- `SHA256SUMS` is generated in CI by `sha256sum dist/*` — no custom logic.
- In addition, GitHub-native build provenance (SLSA attestation) is emitted for every binary and for the Docker image. No GPG or cosign for v0.x — this can be layered on later without breaking compatibility.

### 6.2 Transport

- All canonical URLs are HTTPS (GitHub, `playmaestro.cloud`).
- The reference CP runs behind a reverse proxy with Let's Encrypt TLS. Provisioning TLS for `playmaestro.cloud` is **operational**, not part of this design.
- Admins running their own CP in `http://` for dev: pass `--insecure` to daemon installer. The flag already exists in the current `install-daemon.sh`.

### 6.3 Enrollment-token protection

- Short-lived (default 30 min), single-use (default `max_uses=1`).
- Consumed atomically with row-level locking.
- The permanent daemon token is never visible to the admin — it is minted inside the consume response and written directly to the daemon's config.
- CP logs every consume event with `host_id`, source IP, user-agent, and outcome.

### 6.4 Shell-script safety

- Each installer uses `set -euo pipefail`.
- All downloaded content written to temp files in `mktemp -d` dirs with `trap 'rm -rf "$tmpdir"' EXIT`.
- The installer scripts are committed in-repo and subjected to `shellcheck` in CI.

---

## 7. Testing strategy

### 7.1 Unit

- **Go**: consume protocol (happy path, expired, revoked, `max_uses` exceeded, `host_id_pattern` mismatch, protocol_version mismatch).
- **Python**: endpoints (`/api/enrollments`, `/enroll/<token>`, `/api/enroll/<token>/consume`) — status codes, auth, idempotency.

### 7.2 Integration — `installer-smoke`

New CI job:

1. Spawn `ubuntu:22.04` container, `docker:dind` sidecar.
2. Run `install-cp.sh` against the container with local images mounted (or pull from GHCR using a pre-release tag).
3. Extract the generated daemon token from CP logs.
4. Create an enrollment via `POST /api/enrollments`.
5. Spawn a second `ubuntu:22.04` container, simulate systemd with `systemd-docker`-style shim or skip systemd and invoke the daemon directly.
6. Run `install-daemon.sh` inside container 2 against container 1's enroll URL.
7. Assert daemon appears in `GET /api/hosts` with status `active`.

`shellcheck` runs on all scripts before this job.

### 7.3 macOS

For v0.x: CI cross-compiles darwin binaries (`go build GOOS=darwin`) and runs `shellcheck`. Runtime testing on macOS is **manual** and documented in `docs/release-checklist.md`.

### 7.4 Release dry-run

A documented checklist in `docs/release-checklist.md` covering: tag naming, pre-release verification, publishing, smoke-testing the published release on a clean VM, rollback procedure.

---

## 8. Out of scope

- **GPG / cosign signing** — SHA256 + GitHub attestation sufficient for v0.x.
- **Native packages** (`.deb`, `.rpm`, Homebrew formula) — evaluated after v1.0.
- **Windows daemon target** — no sensible systemd/launchd equivalent, marginal use case.
- **macOS Level 2** (daemon manages native launchd services on the host, in addition to Docker) — a separate project; requires a `ServiceRunner` abstraction and a `launchd.go` runner alongside `systemd.go`. Tracked as "macOS: native service runner", deferred until a user asks.
- **Multi-CP / HA** — single CP behind a reverse proxy is sufficient for v0.x.
- **DNS / TLS provisioning** for `playmaestro.cloud` — operational, not scripted by this design.
- **CLI/agent enrollment** — the `host_enrollments` table is shaped to extend to other roles later, but no additional role is introduced now.

---

## 9. Phased delivery

This design is intentionally split into two layers with different timing, because they have very different coupling to Phase 2/3 work.

### 9.1 Layer 1 — Distribution infrastructure (implement NOW, before/parallel to Phase 2)

**Rationale:** zero coupling to data model, auth surface, or runner abstractions. Pure infrastructure that every subsequent phase benefits from (versioned artifacts, reproducible releases, one-command CP install). Unblocks open-source reachability immediately. This work implements ahead-of-schedule what Phase 3 already plans under Gruppo G (§G1) — see §9.3 below for the cross-reference.

**Scope of Layer 1:**
- §3 — Release pipeline (CI + release workflows, build matrix, Docker image, SHA256, GitHub attestations).
- §4.1 — `install-cp.sh` (Docker bootstrap, lifecycle flags, install/upgrade/uninstall).
- §4.2 — MySQL-style token bootstrap at container first-start (single shared token, persisted on volume).
- §4.3 — CP static endpoints: `GET /install-daemon.sh` (with CP URL substitution), `GET /dist/*` (bundled binaries + checksums).
- §5.4 (minimal variant) — `install-daemon.sh` **without enrollment**: accepts `--endpoint`, `--host-id`, `--token` as today's script does; downloads binary from CP or GitHub; installs systemd (Linux) / launchd (macOS) unit; verifies SHA256. This is the current `install-daemon.sh` extended for cross-platform + auto-download + checksum + upgrade/uninstall flags.
- §5.5 — Daemon upgrade flow.
- §5.6 — Daemon uninstall flow.
- Daemon code: darwin platform support (forced `systemd_enabled: false`, Docker runner on Docker Desktop socket).
- Docs: README quickstart rewritten around one-liner install; `docs/release-checklist.md`.

**What Layer 1 does NOT deliver yet (deferred to Layer 2):**
- No `host_enrollments` table, no `/api/enrollments` endpoints, no `/enroll/<token>` page.
- No "Add host" UI modal.
- Daemon token distribution remains manual (admin copies the shared token from CP logs and passes it via `--token` on daemon install, exactly as today — just with a much better install UX around it).

**Outcome at end of Layer 1:** open-source users can go from "I found this on GitHub" to "I have a running CP and a registered daemon" with two `curl | sudo bash` commands and one copy-pasted token. This is a usability leap without touching the auth model.

### 9.2 Layer 2 — Enrollment primitives (deferred to Phase 3)

**Rationale:** touches data model (new table), public API surface (new endpoints), auth semantics (token issuance, revocation, audit). These are exactly the areas Phase 3 reshapes via mTLS (E1), user authn (E2), and RBAC (E3). Designing enrollment now and then retrofitting to match Phase 3's auth model is wasted work — or worse, introduces backcompat constraints that slow Phase 3.

**Scope of Layer 2 (deferred, integrated into Phase 3):**
- §5.1 — `host_enrollments` table and migrations.
- §5.2 — `/api/enrollments`, `/api/enrollments/<token>`, `/enroll/<token>`, `/api/enroll/<token>/consume` endpoints.
- §5.3 — `/hosts` UI page with "Add host" modal and enrollment management.
- §5.4 (full variant) — `install-daemon.sh` enrollment flow: `curl …/enroll/<token> | sudo bash` becomes the canonical daemon install path; the consume response carries the permanent daemon credentials (which, in Phase 3, are mTLS cert + key instead of a shared token).

**Natural synergies in Phase 3:**
- **E1 (mTLS)**: the enrollment consume step becomes the delivery channel for the daemon's mTLS keypair. Today `docs/phase-3-production.md` §E1 handwaves "il comando `install-daemon.sh` accetta il pacchetto cert" — Layer 2 is exactly that channel, implemented properly.
- **E2 (OIDC) / E3 (RBAC)**: admin actions on `/api/enrollments` become RBAC-gated (only users with `host.create` permission can mint enrollment tokens); creation is logged to audit with real `actor_id`.
- **G (Packaging)**: the existing Layer 1 CI pipeline extends in Phase 3 with `.deb`/`.rpm` (G1), Helm chart (G2), `docker-compose.prod.yml` (G3). Layer 1 leaves the release workflow structured so these additions are incremental.

### 9.3 Cross-references to phase-3-production.md

When Phase 3 starts, `docs/phase-3-production.md` will be updated to reflect that:

- **§G1 (CI + release pipeline)**: status "already implemented in Layer 1 (2026-04-22 design)". The only remaining G1 items for Phase 3 are `.deb`/`.rpm` packaging of the daemon.
- **§E1 (mTLS)**: the "package cert delivery" mechanism is specified as the enrollment protocol from the 2026-04-22 design (Layer 2). The consume response, which in Layer 1 returns `{daemon_token}`, extends to `{daemon_cert, daemon_key, ca_cert}` in Phase 3.
- **§G4 (upgrade script)**: builds on the `install-{cp,daemon}.sh --upgrade` paths delivered in Layer 1.

### 9.4 Implementation scope summary — Layer 1 only

For the **Layer 1** implementation plan (the plan to be written immediately after this design), the work breaks into these components:

1. **CI / release pipeline** — `.github/workflows/{ci,release}.yml`, build matrix, Docker image build, SHA256 generation, attestation wiring.
2. **CP image changes** — `docker-entrypoint.sh` with MySQL-style token bootstrap, static `/dist` mount, bundled binaries in the image.
3. **CP static endpoints** — `GET /install-daemon.sh` (templated), `GET /dist/*`.
4. **`install-cp.sh`** — new script, lifecycle flags.
5. **`install-daemon.sh` (minimal)** — rewrite of current script: auto-download binary, verify SHA256, cross-platform (Linux systemd + macOS launchd), upgrade/uninstall. Keeps `--token` flag for now.
6. **Daemon code** — handle `darwin` platform: force `systemd_enabled: false`, ensure existing Docker runner works identically on macOS.
7. **Docs** — README quickstart rewritten around the new one-liner install, `docs/release-checklist.md` for maintainer release flow, update of `docs/phase-3-production.md` to cross-reference this design.

Ordering and granularity are left to the implementation plan (writing-plans).
