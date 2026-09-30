from cryptography.fernet import Fernet

from privacy_proxy.vault.crypto import VaultCrypto


def test_encrypt_and_decrypt():
    key = Fernet.generate_key().decode()
    crypto = VaultCrypto(key)

    original = "김민수"

    encrypted = crypto.encrypt(original)
    decrypted = crypto.decrypt(encrypted)

    assert encrypted != original
    assert decrypted == original


def test_lookup_key_is_deterministic():
    key = Fernet.generate_key().decode()
    crypto = VaultCrypto(key)

    lookup1 = crypto.make_lookup_key("김민수")
    lookup2 = crypto.make_lookup_key("김민수")

    assert lookup1 == lookup2


def test_different_original_has_different_lookup_key():
    key = Fernet.generate_key().decode()
    crypto = VaultCrypto(key)

    lookup1 = crypto.make_lookup_key("김민수")
    lookup2 = crypto.make_lookup_key("이영희")

    assert lookup1 != lookup2
