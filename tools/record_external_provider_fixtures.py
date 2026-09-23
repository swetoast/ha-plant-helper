#!/usr/bin/env python3
"""Record sanitized external-provider fixtures for Plant Helper.

Credentials are read from environment variables only and are never written.
The recorder uses only Python's standard library so it can run outside Home Assistant.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
USER_AGENT = "Plant-Helper-Fixture-Recorder/0.0.17"
SECRET_QUERY_FIELDS = {"key", "token", "api_key", "apikey", "access_token"}


def sanitize_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return value
    query = [
        (key, "[redacted]" if key.casefold() in SECRET_QUERY_FIELDS else item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
    ]
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))


def sanitize(value: Any, secrets: tuple[str, ...]) -> Any:
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            if key.casefold() in SECRET_QUERY_FIELDS or key.casefold() == "authorization":
                clean[key] = "[redacted]"
            else:
                clean[key] = sanitize(item, secrets)
        return clean
    if isinstance(value, list):
        return [sanitize(item, secrets) for item in value]
    if isinstance(value, str):
        clean = value
        for secret in secrets:
            if secret:
                clean = clean.replace(secret, "[redacted]")
        return sanitize_url(clean)
    return value


def request_json(url: str, *, secrets: tuple[str, ...] = ()) -> dict[str, Any]:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    status: int
    raw: bytes
    try:
        with urlopen(request, timeout=30) as response:
            status = response.status
            raw = response.read()
    except HTTPError as error:
        status = error.code
        raw = error.read()
    except (URLError, TimeoutError) as error:
        reason = getattr(error, "reason", str(error))
        raise RuntimeError(f"request failed: {reason}") from error

    try:
        body: Any = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"provider returned non-JSON HTTP {status}") from error
    return {"http_status": status, "body": sanitize(body, secrets)}


def write_fixture(relative_path: str, payload: Any) -> Path:
    path = FIXTURES / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def record_open_meteo() -> Path:
    params = {
        "latitude": "57.7210",
        "longitude": "12.9401",
        "hourly": "temperature_2m,relative_humidity_2m,precipitation,shortwave_radiation,et0_fao_evapotranspiration",
        "forecast_hours": "24",
        "timezone": "UTC",
    }
    result = request_json("https://api.open-meteo.com/v1/forecast?" + urlencode(params))
    if result["http_status"] != 200:
        raise RuntimeError(f"Open-Meteo returned HTTP {result['http_status']}")
    return write_fixture("open_meteo/boras_three_day_forecast.json", result["body"])


def require_secret(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required for this recording")
    return value


def record_perenual(relative_path: str, species_id: int) -> Path:
    key = require_secret("PERENUAL_API_KEY")
    url = f"https://perenual.com/api/v2/species/details/{species_id}?" + urlencode({"key": key})
    result = request_json(url, secrets=(key,))
    return write_fixture(relative_path, result)


def record_trefle() -> Path:
    token = require_secret("TREFLE_API_KEY")
    params = {"q": "Monstera deliciosa", "limit": "3", "token": token}
    result = request_json(
        "https://trefle.io/api/v1/species/search?" + urlencode(params),
        secrets=(token,),
    )
    return write_fixture("trefle/monstera_deliciosa_details.json", result)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "providers",
        nargs="+",
        choices=("open-meteo", "perenual-free", "perenual-paid", "trefle", "all"),
    )
    parser.add_argument("--perenual-free-id", type=int, default=1)
    parser.add_argument("--perenual-paid-id", type=int, default=5257)
    args = parser.parse_args()

    selected = {"open-meteo", "perenual-free", "perenual-paid", "trefle"} if "all" in args.providers else set(args.providers)
    actions = {
        "open-meteo": record_open_meteo,
        "perenual-free": lambda: record_perenual("perenual/free_details_success.json", args.perenual_free_id),
        "perenual-paid": lambda: record_perenual("perenual/paid_details_restricted.json", args.perenual_paid_id),
        "trefle": record_trefle,
    }
    failed = False
    for provider in ("open-meteo", "perenual-free", "perenual-paid", "trefle"):
        if provider not in selected:
            continue
        try:
            path = actions[provider]()
            print(f"recorded {provider}: {path.relative_to(ROOT)}")
        except RuntimeError as error:
            failed = True
            print(f"failed {provider}: {error}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
