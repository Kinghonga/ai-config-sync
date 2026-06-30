from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

ALGORITHM = "aes-256-gcm"
KDF = "pbkdf2-sha256"
ITERATIONS = 600_000
SALT_BYTES = 16
NONCE_BYTES = 12
KEY_BYTES = 32

# Standalone-compatible XOR algorithm. The standalone ai-sync.py uses this
# because it cannot depend on the `cryptography` library. The pip version can
# decrypt packages produced by the standalone version via this fallback path.
# Limitation: the standalone version cannot decrypt packages produced by the
# pip version (AES-256-GCM); re-export with the standalone script instead.
XOR_ALGORITHM = "xor-hmac-sha256"
XOR_HMAC_KEY_BYTES = 32
XOR_STREAM_KEY_BYTES = 32
XOR_DERIVED_LENGTH = XOR_HMAC_KEY_BYTES + XOR_STREAM_KEY_BYTES


def _b64e(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _b64d(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"), validate=True)


def derive_key(passphrase: str, salt: bytes, iterations: int = ITERATIONS) -> bytes:
    if not passphrase:
        raise ValueError("passphrase must not be empty")
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=KEY_BYTES, salt=salt, iterations=iterations)
    return kdf.derive(passphrase.encode("utf-8"))


def _derive_xor_keys(passphrase: str, salt: bytes) -> tuple[bytes, bytes]:
    raw = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, ITERATIONS, dklen=XOR_DERIVED_LENGTH)
    return raw[:XOR_HMAC_KEY_BYTES], raw[XOR_HMAC_KEY_BYTES:]


def _xor_crypt(data: bytes, key: bytes) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < len(data):
        block = hashlib.sha256(key + counter.to_bytes(8, "big")).digest()
        need = min(len(block), len(data) - len(out))
        for i in range(need):
            out.append(data[len(out)] ^ block[i])
        counter += 1
    return bytes(out)


def _decrypt_xor(encrypted: dict[str, Any], passphrase: str) -> dict[str, Any]:
    salt = _b64d(encrypted["salt"])
    nonce = _b64d(encrypted["nonce"])
    ciphertext = _b64d(encrypted["ciphertext"])
    tag_expected = encrypted.get("tag", "")
    hmac_key, stream_key = _derive_xor_keys(passphrase, salt)
    tag_actual = hmac.new(hmac_key, ciphertext, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(tag_expected, tag_actual):
        raise ValueError("could not decrypt credentials; check passphrase")
    mixed_stream = hashlib.sha256(stream_key + nonce).digest() + stream_key
    plaintext = _xor_crypt(ciphertext, mixed_stream)
    return json.loads(plaintext.decode("utf-8"))


def encrypt_credentials(credentials: dict[str, Any], passphrase: str) -> dict[str, Any]:
    salt = os.urandom(SALT_BYTES)
    nonce = os.urandom(NONCE_BYTES)
    key = derive_key(passphrase, salt)
    plaintext = json.dumps(credentials, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, None)
    return {
        "algorithm": ALGORITHM,
        "kdf": KDF,
        "iterations": ITERATIONS,
        "salt": _b64e(salt),
        "nonce": _b64e(nonce),
        "ciphertext": _b64e(ciphertext),
    }


def decrypt_credentials(encrypted: dict[str, Any] | None, passphrase: str | None) -> dict[str, Any]:
    if encrypted is None:
        return {}
    if not passphrase:
        raise ValueError("passphrase is required to decrypt credentials")
    algorithm = encrypted.get("algorithm")
    if algorithm == XOR_ALGORITHM:
        return _decrypt_xor(encrypted, passphrase)
    if algorithm != ALGORITHM:
        raise ValueError(f"unsupported credential encryption algorithm: {algorithm}")
    if encrypted.get("kdf") != KDF:
        raise ValueError("unsupported credential encryption metadata")
    iterations = int(encrypted.get("iterations", 0))
    salt = _b64d(encrypted["salt"])
    nonce = _b64d(encrypted["nonce"])
    ciphertext = _b64d(encrypted["ciphertext"])
    key = derive_key(passphrase, salt, iterations)
    try:
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, None)
    except Exception as exc:  # pragma: no cover - cryptography-specific subtype not stable
        raise ValueError("could not decrypt credentials; check passphrase") from exc
    return json.loads(plaintext.decode("utf-8"))
