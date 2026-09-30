"""L6 암복호화 / lookup key 생성.

- 원문 암호화: AES-256-GCM (nonce 랜덤, AAD로 세션/네임스페이스에 바인딩)
- Redis 키: 원문을 그대로 키에 넣지 않고 HMAC-SHA256 으로 해시
- 마스터키 하나에서 HKDF로 용도별 서브키를 분리(암호화용 / lookup용)
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_FORMAT_VERSION = b"\x01"  # 키 로테이션 대비 버전 바이트
_NONCE_LEN = 12
_KEY_LEN = 32  # AES-256


class VaultCryptoError(Exception):
    """키 형식 오류 / 복호화 실패. 메시지에 평문·키를 절대 넣지 않는다."""


def _derive(master_key: bytes, info: bytes) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=_KEY_LEN,
        salt=None,
        info=info,
    ).derive(master_key)


class VaultCrypto:
    def __init__(self, master_key: bytes) -> None:
        if len(master_key) != _KEY_LEN:
            raise VaultCryptoError("VAULT_ENCRYPTION_KEY must decode to 32 bytes")
        self._aead = AESGCM(_derive(master_key, b"privacy-proxy/vault/enc/v1"))
        self._lookup_key = _derive(master_key, b"privacy-proxy/vault/lookup/v1")

    # ---- 키 로딩 -------------------------------------------------------
    @classmethod
    def from_base64(cls, encoded: str) -> VaultCrypto:
        try:
            raw = base64.urlsafe_b64decode(encoded.strip() + "=" * (-len(encoded.strip()) % 4))
        except (binascii.Error, ValueError) as exc:
            raise VaultCryptoError("VAULT_ENCRYPTION_KEY is not valid base64") from exc
        return cls(raw)

    @staticmethod
    def generate_key() -> str:
        """.env 에 넣을 새 키 생성: python -c 'from privacy_proxy.vault.crypto import VaultCrypto as V; print(V.generate_key())'"""
        return base64.urlsafe_b64encode(os.urandom(_KEY_LEN)).decode()

    # ---- 암복호화 ------------------------------------------------------
    def encrypt(self, plaintext: str, *, aad: str) -> str:
        nonce = os.urandom(_NONCE_LEN)
        ct = self._aead.encrypt(nonce, plaintext.encode("utf-8"), aad.encode("utf-8"))
        return base64.urlsafe_b64encode(_FORMAT_VERSION + nonce + ct).decode()

    def decrypt(self, token: str, *, aad: str) -> str:
        try:
            blob = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
            if blob[:1] != _FORMAT_VERSION:
                raise VaultCryptoError("unsupported ciphertext version")
            nonce, ct = blob[1 : 1 + _NONCE_LEN], blob[1 + _NONCE_LEN :]
            return self._aead.decrypt(nonce, ct, aad.encode("utf-8")).decode("utf-8")
        except (InvalidTag, binascii.Error, ValueError) as exc:
            raise VaultCryptoError("decryption failed") from exc

    # ---- lookup key ----------------------------------------------------
    def lookup_key(self, *parts: str) -> str:
        """(session, namespace, normalized_value) 등을 HMAC 해시. 구분자 충돌 방지를 위해 \\x1f 사용."""
        msg = "\x1f".join(parts).encode("utf-8")
        return hmac.new(self._lookup_key, msg, hashlib.sha256).hexdigest()
