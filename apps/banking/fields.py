from cryptography.fernet import Fernet
from django.conf import settings
from django.db import models


class EncryptedTextField(models.TextField):
    """Transparently encrypts content at rest using Fernet (symmetric AES-128-CBC + HMAC).

    Reads and writes plaintext in Python; stores base64-encoded Fernet tokens in the DB.
    Loses all content if ``FIELD_ENCRYPTION_KEY`` is rotated — back up the key separately.
    """

    description = "Text field encrypted at rest with Fernet."

    def _get_fernet(self) -> Fernet:
        key = settings.FIELD_ENCRYPTION_KEY
        if isinstance(key, str):
            key = key.encode()
        return Fernet(key)

    def from_db_value(self, value, expression, connection):
        if value is None:
            return value
        return self._get_fernet().decrypt(value.encode()).decode()

    def to_python(self, value):
        if value is None or not isinstance(value, str):
            return value
        # Already-plaintext (e.g. from a form) passes through unchanged.
        return value

    def get_prep_value(self, value):
        if value is None:
            return value
        return self._get_fernet().encrypt(str(value).encode()).decode()
