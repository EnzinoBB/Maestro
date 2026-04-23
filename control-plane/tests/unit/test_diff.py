from app.orchestrator.diff import compute_diff, component_hash


def test_hash_stable():
    a = {"source": {"type": "docker", "image": "nginx"}, "run": {"type": "docker"}}
    b = {"run": {"type": "docker"}, "source": {"type": "docker", "image": "nginx"}}
    assert component_hash(a) == component_hash(b)


def test_hash_changes_when_config_archive_content_hash_changes():
    # component_hash must react to config_archives content changes: without
    # this, a content-only deploy would be misclassified as "unchanged".
    base = {
        "source": {"type": "docker", "image": "caddy"},
        "run": {"type": "docker"},
        "config_archives": [
            {"dest": "/srv", "strategy": "atomic_symlink",
             "mode": 0o755, "tar_b64": "AAA", "content_hash": "aaa"}
        ],
    }
    bumped = dict(base, config_archives=[
        {"dest": "/srv", "strategy": "atomic_symlink",
         "mode": 0o755, "tar_b64": "AAA", "content_hash": "bbb"}
    ])
    assert component_hash(base) != component_hash(bumped)


def test_hash_ignores_tar_b64_blob_if_content_hash_identical():
    # If two payloads share content_hash, the tar_b64 blob (which may differ
    # in representation) must NOT affect the hash.
    base = {
        "source": {"type": "docker", "image": "caddy"},
        "run": {"type": "docker"},
        "config_archives": [
            {"dest": "/srv", "strategy": "atomic_symlink",
             "mode": 0o755, "tar_b64": "xxxxxx", "content_hash": "aaa"}
        ],
    }
    other = dict(base, config_archives=[
        {"dest": "/srv", "strategy": "atomic_symlink",
         "mode": 0o755, "tar_b64": "yyyyyy", "content_hash": "aaa"}
    ])
    assert component_hash(base) == component_hash(other)


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
