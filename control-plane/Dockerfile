# syntax=docker/dockerfile:1.6
# ---- Stage 1: cross-compile daemon binaries ----
FROM golang:1.22-alpine AS daemon-builder
ARG VERSION=dev
WORKDIR /src
COPY daemon/go.mod daemon/go.sum ./
RUN go mod download
COPY daemon/ ./
RUN set -eu; \
    mkdir -p /out; \
    for os in linux darwin; do \
      for arch in amd64 arm64; do \
        CGO_ENABLED=0 GOOS=$os GOARCH=$arch \
          go build -trimpath -ldflags="-s -w -X main.Version=${VERSION}" \
          -o /out/maestrod-${os}-${arch} ./cmd/maestrod; \
      done; \
    done; \
    cd /out && sha256sum maestrod-* > SHA256SUMS

# ---- Stage 2: CP runtime ----
FROM python:3.12-slim

WORKDIR /app
# NOTE: this list must stay in sync with control-plane/pyproject.toml
# [project.dependencies]. A proper "pip install ." would be cleaner but is
# blocked by readme = "../README.md" in pyproject (outside build context);
# revisit as part of Phase 3 packaging hardening.
RUN pip install --no-cache-dir fastapi 'uvicorn[standard]' pydantic pyyaml jinja2 \
    sqlalchemy aiosqlite websockets httpx click mcp python-multipart

COPY control-plane/app/ ./app/
COPY control-plane/web/ ./web/
COPY control-plane/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
COPY scripts/install-daemon.sh /opt/maestro-cp/scripts/install-daemon.sh
COPY --from=daemon-builder /out/ /opt/maestro-cp/dist/

RUN chmod +x /usr/local/bin/docker-entrypoint.sh \
             /opt/maestro-cp/scripts/install-daemon.sh

EXPOSE 8000
ENV PYTHONUNBUFFERED=1 \
    MAESTRO_DIST_DIR=/opt/maestro-cp/dist \
    MAESTRO_INSTALL_SCRIPT=/opt/maestro-cp/scripts/install-daemon.sh

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
