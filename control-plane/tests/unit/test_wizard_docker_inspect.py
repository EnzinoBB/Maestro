from app.wizard.docker_inspect import parse_docker_inspect, DockerSuggestions


_DOCKER_INSPECT_OUTPUT = """
[
  {
    "Id": "sha256:abc",
    "RepoTags": ["nginx:1.25"],
    "Config": {
      "ExposedPorts": {"80/tcp": {}, "443/tcp": {}},
      "Env": [
        "PATH=/usr/local/sbin",
        "NGINX_VERSION=1.25.0",
        "MAESTRO_IGNORE=should_not_appear"
      ],
      "Volumes": {"/var/cache/nginx": {}}
    }
  }
]
"""


def test_parse_extracts_ports_env_volumes():
    sug = parse_docker_inspect(_DOCKER_INSPECT_OUTPUT)
    assert isinstance(sug, DockerSuggestions)
    assert sug.exposed_ports == [80, 443]
    assert any(e["key"] == "NGINX_VERSION" and e["value"] == "1.25.0" for e in sug.env)
    assert sug.volumes == ["/var/cache/nginx"]


def test_parse_returns_empty_on_malformed_json():
    sug = parse_docker_inspect("not json")
    assert sug.exposed_ports == []
    assert sug.env == []
    assert sug.volumes == []


def test_parse_returns_empty_on_empty_array():
    sug = parse_docker_inspect("[]")
    assert sug.exposed_ports == []


def test_parse_handles_missing_config_sections():
    out = '[{"Id": "x", "Config": {}}]'
    sug = parse_docker_inspect(out)
    assert sug.exposed_ports == []
    assert sug.env == []
    assert sug.volumes == []


def test_parse_skips_non_tcp_ports():
    out = '[{"Config": {"ExposedPorts": {"80/tcp": {}, "9000/udp": {}}}}]'
    sug = parse_docker_inspect(out)
    assert sug.exposed_ports == [80]
