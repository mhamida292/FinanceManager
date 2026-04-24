import pytest
from cryptography.fernet import Fernet
from django.db import connection, models

from apps.banking.fields import EncryptedTextField


class _FakeModel(models.Model):
    """Ephemeral model used only for field-level roundtrip testing."""
    secret = EncryptedTextField()

    class Meta:
        app_label = "banking"
        managed = False


def test_encrypted_field_roundtrips_plaintext_via_get_prep_and_from_db():
    field = EncryptedTextField()
    plaintext = "https://bridge.simplefin.org/simplefin/access/SECRETTOKEN"
    ciphertext = field.get_prep_value(plaintext)
    assert ciphertext != plaintext
    assert ciphertext.startswith("gAAAA")  # Fernet token prefix
    # from_db_value should decrypt back
    roundtripped = field.from_db_value(ciphertext, None, connection)
    assert roundtripped == plaintext


def test_encrypted_field_none_roundtrips_as_none():
    field = EncryptedTextField()
    assert field.get_prep_value(None) is None
    assert field.from_db_value(None, None, connection) is None


def test_encrypted_field_different_calls_produce_different_ciphertext():
    """Fernet uses a random IV, so two encryptions of the same plaintext differ."""
    field = EncryptedTextField()
    plaintext = "same input"
    first = field.get_prep_value(plaintext)
    second = field.get_prep_value(plaintext)
    assert first != second
    assert field.from_db_value(first, None, connection) == plaintext
    assert field.from_db_value(second, None, connection) == plaintext
