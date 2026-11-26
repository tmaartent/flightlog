import hashlib
import hmac


def make_signature(payload: bytes, secret: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"),
        msg=payload,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return f"sha256={digest}"


def csrf_token(client) -> str:
    """The CSRF token of a test client's session, created if the session has none yet."""
    with client.session_transaction() as session:
        return session.setdefault("csrf_token", "test-csrf-token")
