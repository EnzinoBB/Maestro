# playmaestro.cloud — Reference deploy

**Live:** https://www.playmaestro.cloud/ — verified 2026-04-23.

Deploys the root-level `website/` directory as a static site at
`https://www.playmaestro.cloud/`, served by Caddy-in-Docker with automatic
Let's Encrypt HTTPS. This example exercises the `config.files` primitive
(atomic_symlink strategy) and is the reference Phase 1 deploy for a
content-first (no-build, no-systemd) component.

Phase 1 notes:
- `deploy_mode: cold` is required (the `hot` mode is declared in the schema
  but the Phase 1 engine rejects it; atomic semantics for content come from
  `config.files[].strategy: atomic_symlink`, not from `deploy_mode`).
- `reload_triggers.content` is accepted by the schema (added in this branch)
  but not yet consumed by the daemon's phase dispatcher; it's a Phase 2 hook.

## One-time host preparation

See `docs/superpowers/specs/2026-04-23-playmaestro-cloud-deploy-design.md §4`.
Three commands on host1:

```bash
sudo usermod -aG docker agent   # log out/in required
sudo ufw allow 80/tcp && sudo ufw allow 443/tcp
mkdir -p /home/agent/playmaestro/{site/releases,caddy/data}
```

## Deploy

From a workstation, with CP reachable:

```bash
python3 scripts/maestro-deploy.py \
  --yaml examples/playmaestro-cloud/deployment.yaml \
  --cp http://109.199.123.26:8000
```

The client script bundles `Caddyfile.j2` into `template_store` and `website/`
into `files_store` (as a deterministic tar) and POSTs to `/api/config/apply`.

## Rollback

Zero-downtime content rollback re-flips `/home/agent/playmaestro/site/current`
to the previous release under `releases/`. No container restart required.

## Kill-switch

```bash
ssh agent@109.199.123.26 docker stop caddy-playmaestro
```

Ports 80/443 go unbound. Restore with `docker start caddy-playmaestro`.
