# Release Checklist

This document guides a maintainer through cutting a Maestro release. Automation
does the heavy lifting; the checklist exists to catch the things automation
can't verify.

## Preconditions

- [ ] `main` is green on CI.
- [ ] Local working tree is clean and on `main`: `git status` shows no changes.
- [ ] You've pulled: `git pull --ff-only origin main`.
- [ ] `CHANGELOG.md` (if maintained) is updated with user-facing changes since the last tag.

## Local verification

- [ ] `make test-unit` passes.
- [ ] `make build-all && make checksums` succeeds; `dist/` contains 4 binaries + `SHA256SUMS`.
- [ ] `make build-image` succeeds and the resulting container starts: `docker run --rm -p 18000:8000 ghcr.io/enzinobb/maestro-cp:dev &` then `curl http://localhost:18000/healthz` returns `{"ok":true}`.
- [ ] `shellcheck scripts/install-cp.sh scripts/install-daemon.sh control-plane/docker-entrypoint.sh` is clean.

## Tag and push

- [ ] Pick the next semver tag. For a bugfix release: `vX.Y.Z+1`. For a feature: `vX.Y+1.0`.
- [ ] `git tag -a vX.Y.Z -m "Release vX.Y.Z"`.
- [ ] `git push origin vX.Y.Z`.

## Automated release

Watch the Actions tab. The `Release` workflow should:

- [ ] Build all 4 binaries.
- [ ] Build the multi-arch image and push `ghcr.io/enzinobb/maestro-cp:vX.Y.Z` + `:latest`.
- [ ] Create a GitHub Release with binaries + `SHA256SUMS` + both installer scripts.
- [ ] Emit build attestations for binaries and image.

Total runtime should be 5–10 minutes.

## Post-release

- [ ] Smoke-test the published release from a clean VM:
  ```
  curl -fsSL https://github.com/EnzinoBB/Maestro/releases/download/vX.Y.Z/install-cp.sh | sudo bash
  ```
- [ ] Upgrade the reference CP on `playmaestro.cloud`:
  ```
  ssh admin@playmaestro.cloud sudo /opt/maestro-cp/install-cp.sh --upgrade
  ```
  (If the script was removed from the install dir, re-download: `curl -fsSL https://github.com/EnzinoBB/Maestro/releases/download/vX.Y.Z/install-cp.sh | sudo bash -s -- --upgrade`.)
- [ ] Verify `https://playmaestro.cloud/dist/maestrod-linux-amd64` returns the new binary (checksum matches the release).
- [ ] Announce the release: README already links to `releases/latest`; no code change needed unless there's a migration note.

## Rollback

- [ ] Pin the previous tag: `curl -fsSL …/vX.Y.Z-1/install-cp.sh | sudo bash -s -- --upgrade --version vX.Y.Z-1`.
- [ ] Document the reason in a GitHub issue and draft a fix.
