from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "tools" / "record_external_provider_fixtures.py"
SPEC = importlib.util.spec_from_file_location("fixture_recorder", MODULE_PATH)
assert SPEC and SPEC.loader
RECORDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RECORDER)


def test_sanitize_removes_credentials_from_nested_values_and_urls():
    secret = "private-key-value"
    payload = {
        "token": secret,
        "nested": [{"url": f"https://example.invalid/image.jpg?token={secret}&size=large"}],
        "message": f"credential={secret}",
    }
    clean = RECORDER.sanitize(payload, (secret,))
    serialized = str(clean)
    assert secret not in serialized
    assert clean["token"] == "[redacted]"
    assert "token=%5Bredacted%5D" in clean["nested"][0]["url"]


def test_sanitize_url_leaves_non_urls_unchanged():
    assert RECORDER.sanitize_url("Monstera deliciosa") == "Monstera deliciosa"
