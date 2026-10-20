"""Argon2id hashing and opaque, server-side session token digests."""

import hashlib
import secrets
from threading import BoundedSemaphore

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError


class Passwords:
    def __init__(self) -> None:
        self._capacity = BoundedSemaphore(2)
        self.hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
        self.dummy_hash = self.hasher.hash(secrets.token_urlsafe(32))

    def hash(self, password: str) -> str:
        if not 12 <= len(password) <= 128:
            raise ValueError("A senha deve ter entre 12 e 128 caracteres.")
        with self._capacity:
            return self.hasher.hash(password)

    def verify(self, password: str, encoded: str | None) -> bool:
        try:
            with self._capacity:
                return (
                    self.hasher.verify(encoded or self.dummy_hash, password) and encoded is not None
                )
        except (VerificationError, InvalidHashError):
            return False

    @staticmethod
    def digest(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()
