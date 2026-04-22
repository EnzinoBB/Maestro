# Maestro — root Makefile.
# Fase 1 implementation.

.PHONY: help build build-daemon build-linux build-control-plane \
        test-unit test-integration test-e2e dev clean lint

help:
	@echo "Available targets:"
	@echo "  make build                - build daemon + CP sanity check"
	@echo "  make build-daemon         - native go build of maestrod (dist/maestrod)"
	@echo "  make build-linux          - cross-compile maestrod for linux/amd64"
	@echo "  make build-control-plane  - python compile + ruff checks"
	@echo "  make test-unit            - unit tests (python + go)"
	@echo "  make test-integration     - integration tests (go)"
	@echo "  make test-e2e             - end-to-end tests (requires docker)"
	@echo "  make dev                  - start control plane locally"
	@echo "  make clean                - remove build artifacts"

build: build-linux build-control-plane

build-daemon:
	cd daemon && CGO_ENABLED=0 go build -o ../dist/maestrod ./cmd/maestrod

build-linux:
	cd daemon && CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -ldflags="-s -w" \
		-o ../dist/maestrod-linux-amd64 ./cmd/maestrod

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
