"""Pydantic models for `deployment.yaml` — Fase 1 subset of maestro/v1."""
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# ---- hosts -----------------------------------------------------------------

class DaemonOverride(_Base):
    endpoint_override: str | None = None
    install_method: Literal["auto", "manual"] = "auto"


class HostSpec(_Base):
    type: Literal["linux", "kubernetes"] = "linux"
    address: str | None = None
    port: int = 22
    user: str = "deploy"
    tags: list[str] = Field(default_factory=list)
    daemon: DaemonOverride | None = None
    # kubernetes (fase 3) — accettati ma non usati in fase 1
    kubeconfig_ref: str | None = None
    context: str | None = None
    namespace: str | None = None


# ---- components ------------------------------------------------------------

class SourceSpec(_Base):
    type: Literal["git", "docker", "archive"]
    # git
    repo: str | None = None
    ref: str | None = None
    credentials_ref: str | None = None
    subpath: str | None = None
    # docker
    image: str | None = None
    tag: str | None = None
    pull_policy: Literal["always", "if_not_present", "never"] = "if_not_present"
    # archive
    path: str | None = None

    @model_validator(mode="after")
    def _check(self):
        if self.type == "git" and not self.repo:
            raise ValueError("source.git requires 'repo'")
        if self.type == "docker" and not self.image:
            raise ValueError("source.docker requires 'image'")
        if self.type == "archive" and not self.path:
            raise ValueError("source.archive requires 'path'")
        return self


class BuildStep(_Base):
    command: str
    env: dict[str, str] = Field(default_factory=dict)
    working_dir: str | None = None
    timeout: str = "300s"


class ConfigTemplate(_Base):
    source: str
    dest: str
    mode: int = 0o640


class ConfigSpec(_Base):
    templates: list[ConfigTemplate] = Field(default_factory=list)
    vars: dict[str, Any] = Field(default_factory=dict)
    secrets: dict[str, str] = Field(default_factory=dict)  # fase 2+, ignorati in 1


class SystemdRun(_Base):
    type: Literal["systemd"]
    unit_name: str | None = None
    command: str
    working_directory: str | None = None
    user: str | None = None
    group: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    restart: Literal["no", "on-failure", "always"] = "on-failure"
    restart_sec: int = 5


class DockerRun(_Base):
    type: Literal["docker"]
    image: str | None = None
    container_name: str | None = None
    ports: list[str] = Field(default_factory=list)
    volumes: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    networks: list[str] = Field(default_factory=list)
    restart: Literal["no", "on-failure", "always", "unless-stopped"] = "unless-stopped"
    command: list[str] | None = None
    resources: dict[str, Any] | None = None


RunSpec = SystemdRun | DockerRun


class HttpHealth(_Base):
    type: Literal["http"]
    url: str
    expect_status: int = 200
    expect_body_contains: str | None = None
    interval: str = "10s"
    timeout: str = "5s"
    start_period: str = "15s"
    retries: int = 3


class TcpHealth(_Base):
    type: Literal["tcp"]
    port: int
    interval: str = "10s"
    timeout: str = "5s"
    start_period: str = "15s"
    retries: int = 3


class CommandHealth(_Base):
    type: Literal["command"]
    command: str
    interval: str = "10s"
    timeout: str = "5s"
    start_period: str = "15s"
    retries: int = 3


HealthcheckSpec = HttpHealth | TcpHealth | CommandHealth


class ReloadTriggers(_Base):
    code: Literal["hot", "cold"] = "cold"
    config: Literal["hot", "cold"] = "cold"
    dependencies: Literal["hot", "cold"] = "cold"


class ComponentSpec(_Base):
    description: str | None = None
    source: SourceSpec
    build: list[BuildStep] = Field(default_factory=list)
    config: ConfigSpec = Field(default_factory=ConfigSpec)
    run: RunSpec = Field(discriminator="type")
    deploy_mode: Literal["cold", "hot", "blue_green"] = "cold"
    reload_triggers: ReloadTriggers | None = None
    depends_on: list[str] = Field(default_factory=list)
    healthcheck: HealthcheckSpec | None = Field(default=None, discriminator="type")
    resources: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _mode_fase1(self):
        # fase 1: solo cold è ammesso. hot/blue_green vengono accettati ma
        # trattati come cold dal motore; segnaliamo solo in validate().
        return self


# ---- deployment ------------------------------------------------------------

class CanaryCfg(_Base):
    initial_fraction: float = 0.2
    step_fraction: float = 0.3
    verify_duration: str = "2m"


class DeploymentBinding(_Base):
    host: str
    components: list[str]
    depends_on_hosts: list[str] = Field(default_factory=list)
    strategy: Literal["sequential", "parallel", "canary", "blue_green"] = "sequential"
    canary: CanaryCfg | None = None


# ---- defaults --------------------------------------------------------------

class Defaults(_Base):
    component: dict[str, Any] = Field(default_factory=dict)
    host: dict[str, Any] = Field(default_factory=dict)


# ---- top level -------------------------------------------------------------

class DeploymentSpec(_Base):
    api_version: str = Field(alias="api_version")
    project: str
    description: str | None = None
    hosts: dict[str, HostSpec] = Field(default_factory=dict)
    components: dict[str, ComponentSpec] = Field(default_factory=dict)
    deployment: list[DeploymentBinding] = Field(default_factory=list)
    defaults: Defaults | None = None
    credentials_ref: str | None = None

    @field_validator("api_version")
    @classmethod
    def _api_ver(cls, v: str) -> str:
        if v not in ("maestro/v1", "maestro/v1beta", "maestro/v1ga"):
            raise ValueError(f"unsupported api_version: {v}")
        return v
