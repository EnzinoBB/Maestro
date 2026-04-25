"""Password hashing with PBKDF2-SHA256 (stdlib, no new deps).

Format: "pbkdf2_sha256$<iterations>$<salt_b64>$<hash_b64>"

PBKDF2 is conservative but fine for M5 v2; we can migrate to bcrypt
or argon2 in a future milestone by extending verify() to recognize
other prefixes and reissue on login.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os


_ITERATIONS = 600_000
_SALT_BYTES = 16
_DKLEN = 32


def hash_password(password: str) -> str:
    if not isinstance(password, str) or not password:
        raise ValueError("password must be a non-empty string")
    salt = os.urandom(_SALT_BYTES)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS, dklen=_DKLEN)
    return (
        "pbkdf2_sha256$"
        f"{_ITERATIONS}$"
        f"{base64.b64encode(salt).decode('ascii')}$"
        f"{base64.b64encode(dk).decode('ascii')}"
    )


def verify_password(password: str, encoded: str) -> bool:
    if not password or not encoded:
        return False
    try:
        scheme, iters_s, salt_b64, hash_b64 = encoded.split("$", 3)
    except ValueError:
        return False
    if scheme != "pbkdf2_sha256":
        return False
    try:
        iters = int(iters_s)
        salt = base64.b64decode(salt_b64.encode("ascii"))
        expected = base64.b64decode(hash_b64.encode("ascii"))
    except (ValueError, TypeError):
        return False
    if iters < 1_000 or iters > 10_000_000:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters, dklen=len(expected))
    return hmac.compare_digest(dk, expected)
