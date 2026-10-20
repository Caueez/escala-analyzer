"""Persistent sessions, rate-limited login and revocation."""

import secrets
from datetime import timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from escala_analyzer.application.services.identity import Principal
from escala_analyzer.infrastructure.database.connection import Database
from escala_analyzer.infrastructure.database.models import (
    AuditEvent,
    LoginSession,
    RateLimit,
    User,
    timestamp_utc,
    utcnow,
)
from escala_analyzer.infrastructure.security.passwords import Passwords
from escala_analyzer.settings import Settings


class Authentication:
    def __init__(self, database: Database, settings: Settings) -> None:
        self.database = database
        self.settings = settings
        self.passwords = Passwords()

    def consume_limit(self, session: Session, key: str, maximum: int) -> bool:
        key = self.passwords.digest(key)
        now = utcnow()
        record = session.scalar(select(RateLimit).where(RateLimit.key == key).with_for_update())
        if record is None:
            try:
                with session.begin_nested():
                    record = RateLimit(key=key, attempts=0, resets_at=now + timedelta(minutes=15))
                    session.add(record)
                    session.flush()
            except IntegrityError:
                record = session.scalar(
                    select(RateLimit).where(RateLimit.key == key).with_for_update()
                )
        assert record is not None
        if timestamp_utc(record.resets_at) <= now:
            record.attempts = 0
            record.resets_at = now + timedelta(minutes=15)
        record.attempts += 1
        return record.attempts <= maximum

    def login(self, email: str, password: str, address: str) -> tuple[str, str] | str:
        email = email.strip().casefold()
        with self.database.sessions.begin() as session:
            allowed_ip = self.consume_limit(session, "ip:" + address, 60)
            allowed_account = self.consume_limit(session, "email:" + email, 8)
            if not allowed_ip or not allowed_account:
                return "rate_limited"
            user = session.scalar(select(User).where(User.email == email))
            if (
                not self.passwords.verify(password, user.password_hash if user else None)
                or not user
                or not user.active
            ):
                return "invalid_credentials"
            if self.passwords.hasher.check_needs_rehash(user.password_hash):
                user.password_hash = self.passwords.hash(password)
            token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            session.add(
                LoginSession(
                    id=self.passwords.digest(token),
                    user_id=user.id,
                    csrf_hash=self.passwords.digest(csrf),
                    expires_at=utcnow() + timedelta(hours=self.settings.session_hours),
                )
            )
            session.add(
                AuditEvent(
                    organization_id=user.organization_id,
                    actor_id=user.id,
                    action="auth.login",
                    entity_id=user.id,
                )
            )
            return token, csrf

    def resolve(self, token: str | None) -> Principal | None:
        if not token:
            return None
        with self.database.sessions.begin() as session:
            record = session.get(LoginSession, self.passwords.digest(token))
            now = utcnow()
            if not record or timestamp_utc(record.expires_at) <= now:
                return None
            if (
                timestamp_utc(record.last_seen_at)
                + timedelta(minutes=self.settings.session_idle_minutes)
                <= now
            ):
                session.delete(record)
                return None
            user = session.get(User, record.user_id)
            if not user or not user.active:
                return None
            record.last_seen_at = now
            return Principal(
                user.id, user.organization_id, user.role, user.name, record.id, record.csrf_hash
            )

    def logout(self, principal: Principal) -> None:
        with self.database.sessions.begin() as session:
            session.execute(delete(LoginSession).where(LoginSession.id == principal.session_id))
            session.add(
                AuditEvent(
                    organization_id=principal.organization_id,
                    actor_id=principal.user_id,
                    action="auth.logout",
                    entity_id=principal.user_id,
                )
            )

    def change_password(self, principal: Principal, current: str, new: str) -> bool:
        with self.database.sessions.begin() as session:
            user = session.get(User, principal.user_id)
            if not user or not self.passwords.verify(current, user.password_hash):
                return False
            session.execute(
                update(User)
                .where(User.id == user.id)
                .values(password_hash=self.passwords.hash(new))
            )
            session.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
            session.add(
                AuditEvent(
                    organization_id=principal.organization_id,
                    actor_id=user.id,
                    action="auth.password_changed",
                    entity_id=user.id,
                )
            )
            return True
