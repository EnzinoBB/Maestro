"""Tests for ComponentSpec.metrics (M2.8)."""
import pytest

from app.config.loader import parse_deployment, LoaderError


_BASE_YAML = """api_version: maestro/v1
project: t
hosts:
  h: {type: linux, address: 1.2.3.4}
components:
  app:
    source: {type: docker, image: my/app}
    run: {type: docker}
    metrics:
      endpoint: "http://127.0.0.1:9100/metrics"
      allow: ["http_requests_total", "process_cpu_seconds_total"]
deployment:
  - host: h
    components: [app]
"""


def test_metrics_field_parses_with_allow_list():
    spec = parse_deployment(_BASE_YAML)
    comp = spec.components["app"]
    assert comp.metrics is not None
    assert comp.metrics.endpoint == "http://127.0.0.1:9100/metrics"
    assert comp.metrics.allow == ["http_requests_total", "process_cpu_seconds_total"]


def test_metrics_omitted_means_none():
    yaml = """api_version: maestro/v1
project: t
hosts: {h: {type: linux, address: 1.2.3.4}}
components:
  app:
    source: {type: docker, image: my/app}
    run: {type: docker}
deployment:
  - host: h
    components: [app]
"""
    spec = parse_deployment(yaml)
    assert spec.components["app"].metrics is None


def test_metrics_rejects_empty_allow_list():
    yaml = _BASE_YAML.replace(
        'allow: ["http_requests_total", "process_cpu_seconds_total"]',
        "allow: []",
    )
    with pytest.raises(LoaderError):
        parse_deployment(yaml)


def test_metrics_rejects_non_http_endpoint():
    yaml = _BASE_YAML.replace(
        '"http://127.0.0.1:9100/metrics"',
        '"file:///etc/passwd"',
    )
    with pytest.raises(LoaderError):
        parse_deployment(yaml)


def test_metrics_rejects_missing_endpoint():
    yaml = _BASE_YAML.replace(
        'endpoint: "http://127.0.0.1:9100/metrics"',
        'endpoint: ""',
    )
    with pytest.raises(LoaderError):
        parse_deployment(yaml)
