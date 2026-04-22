# Maestro — root Makefile.
# Fase 1 implementation.

.PHONY: help build build-daemon build-all build-linux build-control-plane \
        checksums build-image test-unit test-integration test-e2e dev clean lint

VERSION ?= dev
LDFLAGS := -s -w -X main.Version=$(VERSION)

help:
	@echo "Available targets:"
	@echo "  make build                - build daemon + CP sanity check"
	@echo "  make build-daemon         - native go build of maestrod (dist/maestrod)"
	@echo "  make build-all            - cross-compile maestrod for linux+darwin × amd64+arm64"
	@echo "  make checksums            - write dist/SHA256SUMS"
	@echo "  make build-image          - build local CP Docker image"
	@echo "  make build-control-plane  - python compile + ruff checks"
	@echo "  make test-unit            - unit tests (python + go)"
	@echo "  make test-integration     - integration tests (go)"
	@echo "  make test-e2e             - end-to-end tests (requires docker)"
	@echo "  make dev                  - start control plane locally"
	@echo "  make clean                - remove build artifacts"

build: build-daemon build-control-plane

build-daemon:
	cd daemon && CGO_ENABLED=0 go build -ldflags="$(LDFLAGS)" \
		-o ../dist/maestrod ./cmd/maestrod

# Cross-compile all release targets. Matches the CI release matrix.
build-all:
	@mkdir -p dist
	cd daemon && CGO_ENABLED=0 GOOS=linux  GOARCH=amd64 go build -ldflags="$(LDFLAGS)" \
		-o ../dist/maestrod-linux-amd64 ./cmd/maestrod
	cd daemon && CGO_ENABLED=0 GOOS=linux  GOARCH=arm64 go build -ldflags="$(LDFLAGS)" \
		-o ../dist/maestrod-linux-arm64 ./cmd/maestrod
	cd daemon && CGO_ENABLED=0 GOOS=darwin GOARCH=amd64 go build -ldflags="$(LDFLAGS)" \
		-o ../dist/maestrod-darwin-amd64 ./cmd/maestrod
	cd daemon && CGO_ENABLED=0 GOOS=darwin GOARCH=arm64 go build -ldflags="$(LDFLAGS)" \
		-o ../dist/maestrod-darwin-arm64 ./cmd/maestrod

# Deprecated alias; kept for muscle memory of Phase 1.
build-linux: build-all

# Generate SHA256SUMS for all binaries in dist/.
checksums:
	cd dist && sha256sum maestrod-* > SHA256SUMS

# Build the CP multi-arch Docker image locally (single-arch: host arch).
# Used mostly for local verification; CI uses docker buildx for multi-arch.
build-image:
	docker build -f control-plane/Dockerfile \
		--build-arg VERSION=$(VERSION) \
		-t ghcr.io/enzinobb/maestro-cp:$(VERSION) .

build-control-plane:
	cd control-plane && python -m compileall app -q

test-unit:
	cd daemon && CGO_ENABLED=0 go test ./...
	cd control-plane && python -m pytest tests/unit -q

test-integration:
	cd daemon && CGO_ENABLED=0 go test ./test/integration/... -count=1 -v
	cd control-plane && python -m pytest tests/integration -q

test-e2e:
	python -m pytest tests/e2e -q

dev:
	cd control-plane && uvicorn app.main:app --reload --port 8000

clean:
	rm -rf dist
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true

lint:
	cd daemon && go vet ./...
	cd control-plane && ruff check app/ || true
