"""API keys per connector (ADR-0005): `fl_<prefix>_<secret>`, stored as a SHA-256 hash.

A plain SHA-256 is enough: the secret is 256 random bits, so there is nothing to guess and
no dictionary to try. Passwords are short and human, which is why they need a slow hash.
"""

import datetime
import hashlib
import hmac
import re
import secrets

from flightlog.application.ports import UnitOfWork
from flightlog.contracts.connectors import ConnectorRef, IssuedKey, RevokeOutcome
from flightlog.domain import Connector

KEY_SCHEME = "fl"
_PREFIX = re.compile(r"[0-9a-f]{8}")


class ConnectorNameTaken(ValueError):
    """Names are never reused, not even after a revoke: audit rows refer to them."""


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def issue_key(name: str, uow: UnitOfWork, now: datetime.datetime) -> IssuedKey:
    """Create a connector with a new key and return the key. It can't be shown again."""
    name = name.strip()
    if not name:
        raise ValueError("a connector needs a name")
    if uow.connectors.get_by_name(name) is not None:
        raise ConnectorNameTaken(f"a connector named {name!r} exists already")

    prefix = secrets.token_hex(4)
    while uow.connectors.get_by_prefix(prefix) is not None:  # 1 in 4 billion, but cheap
        prefix = secrets.token_hex(4)
    # token_urlsafe may contain "_", so a key is split on its first two underscores only.
    key = f"{KEY_SCHEME}_{prefix}_{secrets.token_urlsafe(32)}"

    uow.connectors.add(Connector(name, prefix, hash_key(key), created_at=now))
    uow.commit()
    return IssuedKey(name=name, prefix=prefix, key=key)


def authenticate(raw_key: str, uow: UnitOfWork) -> ConnectorRef | None:
    """The active connector this key belongs to, or None. Reads only, commits nothing.

    The prefix finds the row; the hash decides. compare_digest takes the same time however
    many characters match, so response times don't reveal how close a guess was.
    """
    scheme, _, rest = raw_key.partition("_")
    prefix, _, secret = rest.partition("_")
    if scheme != KEY_SCHEME or not _PREFIX.fullmatch(prefix) or not secret:
        return None

    connector = uow.connectors.get_by_prefix(prefix)
    if connector is None or not hmac.compare_digest(connector.key_hash, hash_key(raw_key)):
        return None
    if not connector.is_active:
        return None
    return ConnectorRef(id=connector.id, name=connector.name)


def revoke_key(name: str, uow: UnitOfWork, now: datetime.datetime) -> RevokeOutcome:
    """Revoke the key of the connector with this name (the CLI)."""
    return _revoke(uow.connectors.get_by_name(name), uow, now)


def revoke_connector(connector_id: int, uow: UnitOfWork, now: datetime.datetime) -> RevokeOutcome:
    """Revoke the key of the connector with this id (the admin page)."""
    return _revoke(uow.connectors.get(connector_id), uow, now)


def _revoke(connector: Connector | None, uow: UnitOfWork, now: datetime.datetime) -> RevokeOutcome:
    """Safe to repeat: a second revoke changes nothing."""
    if connector is None:
        return RevokeOutcome.NOT_FOUND
    if not connector.is_active:
        return RevokeOutcome.ALREADY_REVOKED
    connector.revoke(now)
    uow.commit()
    return RevokeOutcome.REVOKED
