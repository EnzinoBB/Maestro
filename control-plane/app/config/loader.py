"""Load deployment.yaml from file or string into a DeploymentSpec."""
from __future__ import annotations

from pathlib import Path
import yaml
from pydantic import ValidationError as PydanticValidationError

from .schema import DeploymentSpec


class LoaderError(Exception):
    def __init__(self, message: str, errors: list[dict] | None = None):
        super().__init__(message)
        self.errors = errors or []


def parse_deployment(text: str) -> DeploymentSpec:
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise LoaderError(f"YAML parse error: {e}") from e
    if not isinstance(raw, dict):
        raise LoaderError("top-level YAML must be a mapping")
    try:
        return DeploymentSpec.model_validate(raw)
    except PydanticValidationError as e:
        errs = [
            {
                "path": ".".join(str(p) for p in err["loc"]),
                "message": err["msg"],
                "type": err["type"],
            }
            for err in e.errors()
        ]
        raise LoaderError("schema validation failed", errors=errs) from e


def load_deployment(path: Path | str) -> DeploymentSpec:
    p = Path(path)
    return parse_deployment(p.read_text(encoding="utf-8"))
