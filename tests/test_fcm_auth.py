"""The FCM credential path, proven without Firebase.

fcm.py mints its own OAuth2 bearer instead of pulling in google-auth. That is the
one piece that cannot be exercised without a real service account, so this test
generates an RSA key locally, stubs the token endpoint, and then VERIFIES the
signature of the assertion we actually sent — a wrong key, a wrong claim or a
broken base64url encoding all fail here instead of at 2 a.m. in production.
"""
import base64
import json

import pytest


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


@pytest.fixture()
def service_account(tmp_path, monkeypatch):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    sa = {
        "type": "service_account",
        "project_id": "recruit-test-123",
        "client_email": "recruit@recruit-test-123.iam.gserviceaccount.com",
        "private_key": pem,
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    p = tmp_path / "sa.json"
    p.write_text(json.dumps(sa))

    # Settings is a frozen dataclass, so patch the RESOLVER rather than the config.
    import app.fcm as fcm
    monkeypatch.setattr(fcm, "_sa_path", lambda: p)

    # reset the process-level token cache between tests
    monkeypatch.setattr(fcm, "_cached_token", "", raising=False)
    monkeypatch.setattr(fcm, "_cached_exp", 0.0, raising=False)
    monkeypatch.setattr(fcm, "_cached_project", "", raising=False)
    return key, sa


def test_jwt_assertion_is_correctly_signed(service_account, monkeypatch):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    import app.fcm as fcm

    captured: dict = {}

    class FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self):
            return json.dumps({"access_token": "ya29.fake", "expires_in": 3600}).encode()

    def fake_urlopen(req, timeout=10):
        captured["url"] = req.full_url
        captured["body"] = req.data
        captured["headers"] = dict(req.headers)
        return FakeResp()

    monkeypatch.setattr(fcm.urllib.request, "urlopen", fake_urlopen)

    token, project = fcm._access_token()
    assert token == "ya29.fake"
    assert project == "recruit-test-123"
    assert captured["url"] == "https://oauth2.googleapis.com/token"

    # the form body carries our assertion
    from urllib.parse import parse_qs
    form = parse_qs(captured["body"].decode())
    assert form["grant_type"] == ["urn:ietf:params:oauth:grant-type:jwt-bearer"]
    assertion = form["assertion"][0]

    header_b64, claims_b64, sig_b64 = assertion.split(".")
    header = json.loads(_b64d(header_b64))
    claims = json.loads(_b64d(claims_b64))
    assert header == {"alg": "RS256", "typ": "JWT"}
    assert claims["iss"] == "recruit@recruit-test-123.iam.gserviceaccount.com"
    assert claims["scope"] == "https://www.googleapis.com/auth/firebase.messaging"
    assert claims["aud"] == "https://oauth2.googleapis.com/token"
    assert claims["exp"] - claims["iat"] == 3600

    # the signature must verify against the key we handed it
    service_account[0].public_key().verify(
        _b64d(sig_b64),
        f"{header_b64}.{claims_b64}".encode(),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )


def test_token_is_cached_not_minted_per_send(service_account, monkeypatch):
    import app.fcm as fcm
    calls = {"n": 0}

    class FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self):
            calls["n"] += 1
            return json.dumps({"access_token": "ya29.cached", "expires_in": 3600}).encode()

    monkeypatch.setattr(fcm.urllib.request, "urlopen", lambda req, timeout=10: FakeResp())
    fcm._access_token()
    fcm._access_token()
    fcm._access_token()
    assert calls["n"] == 1, "access token must be reused until it nears expiry"


def test_missing_service_account_disables_native_push(monkeypatch):
    import app.fcm as fcm
    monkeypatch.setattr(fcm, "_sa_path", lambda: None)
    assert fcm.enabled() is False
    assert fcm.send(None, {}) == {"sent": 0, "failed": 0, "pruned": 0}
