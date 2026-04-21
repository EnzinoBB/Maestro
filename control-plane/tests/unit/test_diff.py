from app.orchestrator.diff import compute_diff, component_hash


def test_hash_stable():
    a = {"source": {"type": "docker", "image": "nginx"}, "run": {"type": "docker"}}
    b = {"run": {"type": "docker"}, "source": {"type": "docker", "image": "nginx"}}
    assert component_hash(a) == component_hash(b)


def test_create_update_unchanged_remove():
    desired = {
        ("h1", "a"): {"source": {"x": 1}},          # new
        ("h1", "b"): {"source": {"x": 2}, "run": {"image": "nginx:1"}},  # updated
        ("h1", "c"): {"source": {"z": 3}},          # same
    }
    observed = {
        ("h1", "b"): "old-hash",
        ("h1", "c"): component_hash({"source": {"z": 3}}),
        ("h1", "d"): "gone",                         # removed
    }
    d = compute_diff(desired, observed)
    actions = {(c.component_id): c.action for c in d.changes}
    assert actions["a"] == "create"
    assert actions["b"] == "update"
    assert actions["c"] == "unchanged"
    assert actions["d"] == "remove"
