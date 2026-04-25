from app.config.hashing import components_hash_from_rendered


def test_hash_is_stable_across_dict_order():
    a = {
        ("h1", "c1"): {"component_hash": "AAA", "run": {"type": "docker"}},
        ("h2", "c2"): {"component_hash": "BBB", "run": {"type": "docker"}},
    }
    b = {
        ("h2", "c2"): {"component_hash": "BBB", "run": {"type": "docker"}},
        ("h1", "c1"): {"component_hash": "AAA", "run": {"type": "docker"}},
    }
    assert components_hash_from_rendered(a) == components_hash_from_rendered(b)


def test_hash_changes_when_component_hash_changes():
    a = {("h1", "c1"): {"component_hash": "AAA"}}
    b = {("h1", "c1"): {"component_hash": "ZZZ"}}
    assert components_hash_from_rendered(a) != components_hash_from_rendered(b)


def test_hash_changes_when_placement_changes():
    a = {("h1", "c1"): {"component_hash": "AAA"}}
    b = {("h2", "c1"): {"component_hash": "AAA"}}
    assert components_hash_from_rendered(a) != components_hash_from_rendered(b)


def test_empty_rendered_produces_stable_hash():
    h1 = components_hash_from_rendered({})
    h2 = components_hash_from_rendered({})
    assert h1 == h2
    assert len(h1) == 64
