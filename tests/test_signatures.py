import hashlib
import hmac

from flightlog.signatures import verify


def make_signature(payload: bytes, secret: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"),
        msg=payload,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return f"sha256={digest}"


def test_a_correct_signature_returns_true():
    assert verify("Foo", b"Bar", make_signature(b"Bar", "Foo"))


def test_a_incorrect_signature_returns_false():
    assert not verify("Foo", b"Bar", "sha256=Foo")


def test_a_missing_header_returns_false():
    assert not verify("Foo", b"Bar", None)


def test_a_header_without_prefix_returns_false():
    assert not verify("Foo", b"Bar", "Foo")


def test_a_header_with_sha1_header_returns_false():
    assert not verify("Foo", b"Bar", "sha1=Foo")


def test_a_body_changed_by_one_byte_returns_false():
    assert not verify("Foo", b"Baz", make_signature(b"Bar", "Foo"))


def test_header_with_invalid_characters_returns_false():
    assert not verify("Foo", b"Bar", "sha256=é")


def test_github_test_vector_should_return_true():
    secret = "It's a Secret to Everybody"
    payload = "Hello, World!"

    assert verify(
        secret,
        payload.encode("utf-8"),
        "sha256=757107ea0eb2509fc211221cce984b8a37570b6d7586c22c46f4379c8b043e17",
    )
