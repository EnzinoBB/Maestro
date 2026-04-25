from app.config.cross_deploy_validator import (
    check_cross_deploy_conflicts,
)
from app.config.loader import parse_deployment


_BASE = """api_version: maestro/v1
project: base
hosts:
  h1: {type: linux, address: 1.2.3.4}
components:
  web:
    source: {type: docker, image: nginx}
    run:
      type: docker
      ports: ["80:80"]
deployment:
  - host: h1
    components: [web]
"""


_OTHER_SAME_ID = """api_version: maestro/v1
project: other
hosts:
  h1: {type: linux, address: 1.2.3.4}
components:
  web:
    source: {type: docker, image: httpd}
    run: {type: docker}
deployment:
  - host: h1
    components: [web]
"""


_OTHER_DIFF_ID_SAME_PORT = """api_version: maestro/v1
project: other
hosts:
  h1: {type: linux, address: 1.2.3.4}
components:
  api:
    source: {type: docker, image: httpd}
    run:
      type: docker
      ports: ["80:8080"]
deployment:
  - host: h1
    components: [api]
"""


_OTHER_DIFFERENT_HOST = """api_version: maestro/v1
project: other
hosts:
  h2: {type: linux, address: 5.6.7.8}
components:
  web:
    source: {type: docker, image: httpd}
    run: {type: docker}
deployment:
  - host: h2
    components: [web]
"""


def test_no_conflict_when_other_deploy_on_different_host():
    mine = parse_deployment(_BASE)
    others = {"other_id": parse_deployment(_OTHER_DIFFERENT_HOST)}
    conflicts = check_cross_deploy_conflicts(mine, others)
    assert conflicts == []


def test_component_id_collision_same_host():
    mine = parse_deployment(_BASE)
    others = {"other_id": parse_deployment(_OTHER_SAME_ID)}
    conflicts = check_cross_deploy_conflicts(mine, others)
    assert len(conflicts) == 1
    c = conflicts[0]
    assert c.kind == "component_id_collision"
    assert c.host == "h1"
    assert c.component_id == "web"
    assert c.other_deploy_id == "other_id"


def test_host_port_collision_same_host():
    mine = parse_deployment(_BASE)
    others = {"other_id": parse_deployment(_OTHER_DIFF_ID_SAME_PORT)}
    conflicts = check_cross_deploy_conflicts(mine, others)
    assert len(conflicts) == 1
    c = conflicts[0]
    assert c.kind == "host_port_collision"
    assert c.host == "h1"
    assert c.host_port == 80


def test_self_overlap_is_ignored():
    mine = parse_deployment(_BASE)
    others = {}
    assert check_cross_deploy_conflicts(mine, others) == []
