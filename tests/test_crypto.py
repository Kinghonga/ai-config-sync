from __future__ import annotations

from ai_config_sync.crypto import decrypt_credentials, encrypt_credentials


def test_encrypt_decrypt_roundtrip_hides_plaintext():
    creds = {"opencode:sense-nova": {"options": {"apiKey": "SECRET_VALUE"}}}
    encrypted = encrypt_credentials(creds, "pw")
    assert encrypted["algorithm"] == "aes-256-gcm"
    assert encrypted["kdf"] == "pbkdf2-sha256"
    assert encrypted["iterations"] == 600000
    assert "SECRET_VALUE" not in encrypted["ciphertext"]
    assert decrypt_credentials(encrypted, "pw") == creds
