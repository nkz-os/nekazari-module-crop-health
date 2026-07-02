"""Tests for soil-module gateway headers."""

import hashlib
import hmac
import time

from app.services.soil_headers import soil_module_headers


def test_soil_module_headers_includes_hmac(monkeypatch):
    monkeypatch.setenv("HMAC_SECRET", "test-hmac-secret")
    headers = soil_module_headers("montiko")
    assert headers["X-Tenant-ID"] == "montiko"
    assert headers["X-User-ID"] == "crop-health-worker"
    sig_header = headers["X-Auth-Signature"]
    sig, ts = sig_header.split(":")
    payload = f"|montiko|{ts}"
    expected = hmac.new(
        b"test-hmac-secret",
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()
    assert sig == expected
    assert abs(int(time.time()) - int(ts)) < 5


def test_soil_module_headers_without_secret(monkeypatch):
    monkeypatch.delenv("HMAC_SECRET", raising=False)
    headers = soil_module_headers("montiko")
    assert "X-Auth-Signature" not in headers
