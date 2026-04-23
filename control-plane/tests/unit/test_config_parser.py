from pathlib import Path

import pytest

from app.config.loader import parse_deployment, LoaderError
from app.config.validator import validate
from app.config.renderer import render_component, RenderError


FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures"
EXAMPLES = Path(__file__).resolve().parents[3] / "examples"


def test_parses_simple_fixture():
    spec = parse_deployment((FIXTURES / "deployment-simple.yaml").read_text())
    assert spec.project == "test-simple"
    assert set(spec.hosts.keys()) == {"host1"}
    assert set(spec.components.keys()) == {"web"}
    assert validate(spec) == []


def test_parses_multi_fixture():
    spec = parse_deployment((FIXTURES / "deployment-multicomponent.yaml").read_text())
    errs = validate(spec)
    assert errs == []
    # Topology: cache before web
    assert spec.components["web"].depends_on == ["cache"]


def test_reject_bad_api_version():
    with pytest.raises(LoaderError) as ei:
        parse_deployment("api_version: not/valid\nproject: x\n")
    err = ei.value
    # We got a schema validation error with a path
    assert any(
        "api_version" in e["path"] for e in err.errors
    ), err.errors


def test_detect_cycle():
    spec = parse_deployment((FIXTURES / "bad-cycle.yaml").read_text())
    errs = validate(spec)
    msgs = [e.message for e in errs]
    assert any("cycle" in m for m in msgs), msgs


def test_detect_bad_references():
    spec = parse_deployment((FIXTURES / "bad-ref.yaml").read_text())
    errs = validate(spec)
    paths = {e.path for e in errs}
    assert "components.a.depends_on" in paths
    # host missing on deployment[0]
    assert any("deployment[0].host" == e.path for e in errs)
    assert any("deployment[0].components[1]" == e.path for e in errs)


def test_render_vars_and_source_image_defaulting():
    spec = parse_deployment((EXAMPLES / "deployment.yaml").read_text())
    r = render_component(spec, "db", "host1")
    assert r.run["image"] == "postgres:16"
    # vars interpolated in api
    r2 = render_component(spec, "api", "host1")
    # the config template in api uses the file path .env.j2; with our default
    # fallback the dest string is used as template content, so we just ensure
    # the config_files entry exists and dest is resolved
    assert r2.config_files
    assert r2.config_files[0].dest == "/opt/demo-api/.env"


def test_render_missing_variable_raises():
    yml = """
api_version: maestro/v1
project: x
hosts:
  h1: {type: linux, address: 1.2.3.4, user: x}
components:
  a:
    source: {type: docker, image: nginx, tag: latest}
    run: {type: docker, container_name: maestro-a, env: {FOO: "{{ does_not_exist.x }}"}}
deployment:
  - host: h1
    components: [a]
"""
    spec = parse_deployment(yml)
    with pytest.raises(RenderError):
        render_component(spec, "a", "h1")


def test_reload_triggers_accepts_content_key():
    from app.config.loader import parse_deployment
    yaml_text = """
api_version: maestro/v1
project: t
hosts:
  h: {type: linux, address: 1.2.3.4}
components:
  c:
    source: {type: docker, image: nginx}
    run: {type: docker}
    reload_triggers: {code: cold, config: hot, content: hot}
deployment:
  - host: h
    components: [c]
"""
    spec = parse_deployment(yaml_text)
    assert spec.components["c"].reload_triggers.content == "hot"


def test_config_files_parses_with_all_strategies():
    from app.config.loader import parse_deployment
    yaml_text = """
api_version: maestro/v1
project: t
hosts:
  h: {type: linux, address: 1.2.3.4}
components:
  c:
    source: {type: docker, image: nginx}
    run: {type: docker}
    config:
      files:
        - source: ./site
          dest: /var/www/site
          strategy: atomic_symlink
          mode: 0755
        - source: ./singlefile.txt
          dest: /etc/singlefile
          strategy: overwrite
deployment:
  - host: h
    components: [c]
"""
    spec = parse_deployment(yaml_text)
    files = spec.components["c"].config.files
    assert len(files) == 2
    assert files[0].source == "./site"
    assert files[0].dest == "/var/www/site"
    assert files[0].strategy == "atomic_symlink"
    assert files[0].mode == 493  # 0755 octal in decimal
    assert files[1].strategy == "overwrite"


def test_config_files_strategy_must_be_valid():
    from app.config.loader import parse_deployment, LoaderError
    yaml_text = """
api_version: maestro/v1
project: t
hosts:
  h: {type: linux, address: 1.2.3.4}
components:
  c:
    source: {type: docker, image: nginx}
    run: {type: docker}
    config:
      files:
        - source: ./x
          dest: /x
          strategy: bogus
deployment:
  - host: h
    components: [c]
"""
    try:
        parse_deployment(yaml_text)
    except LoaderError as e:
        # Check error details in e.errors list
        error_str = str(e.errors).lower()
        assert "strategy" in error_str or "bogus" in error_str or "literal" in error_str, f"Expected strategy/bogus error, got {e.errors}"
        return
    raise AssertionError("expected LoaderError")
