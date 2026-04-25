import pytest
from app.auth.passwords import hash_password, verify_password


def test_hash_then_verify_roundtrip():
    h = hash_password("s3cret!")
    assert h.startswith("pbkdf2_sha256$")
    assert verify_password("s3cret!", h)


def test_hash_includes_iteration_and_salt():
    h1 = hash_password("abc")
    h2 = hash_password("abc")
    # Two distinct salts → two different hashes
    assert h1 != h2
    assert verify_password("abc", h1)
    assert verify_password("abc", h2)


def test_wrong_password_fails():
    h = hash_password("correct")
    assert not verify_password("wrong", h)


def test_empty_password_rejected_on_hash():
    with pytest.raises(ValueError):
        hash_password("")


def test_verify_rejects_malformed_encoded():
    assert not verify_password("anything", "not a valid hash")
    assert not verify_password("anything", "")
    assert not verify_password("anything", "bcrypt$x$y$z")


def test_verify_rejects_extreme_iterations():
    # Tampering with iteration count outside accepted bounds
    h = hash_password("abc")
    parts = h.split("$")
    bad = f"{parts[0]}$99999999999$"+parts[2]+"$"+parts[3]
    assert not verify_password("abc", bad)
