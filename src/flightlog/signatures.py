import hashlib
import hmac


def verify(secret: str, body: bytes, header: str | None) -> bool:
    if not header:
        return False
    if not header.startswith("sha256="):
        return False

    hash_object = hmac.new(secret.encode("utf-8"), msg=body, digestmod=hashlib.sha256)
    expected_signature = "sha256=" + hash_object.hexdigest()

    return hmac.compare_digest(expected_signature.encode("utf-8"), header.encode("utf-8"))
